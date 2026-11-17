import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import ts from 'typescript'
import { fileURLToPath } from 'node:url'

const directory = path.dirname(fileURLToPath(import.meta.url))

function client(initial, fetch) {
  const storage = new Map(initial ? [['boomerang.guestToken.v1', JSON.stringify(initial)]] : [])
  const clientModule = { exports: {} }
  const source = fs.readFileSync(path.join(directory, '../lib/api.ts'), 'utf8')
  vm.runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true },
  }).outputText, {
    module: clientModule, exports: clientModule.exports, process: { env: {} }, URLSearchParams, fetch, Error, TypeError,
    window: { localStorage: {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    } },
    require: () => JSON.parse(fs.readFileSync(path.join(directory, '../lib/api-routes.json'), 'utf8')),
  })
  return { api: clientModule.exports, storage }
}

const response = (body, status = 200) => ({ status, ok: status < 400, text: async () => JSON.stringify(body) })

test('expired guest credentials renew once and retain identity for concurrent calls', async () => {
  const calls = []
  const { api, storage } = client({ access_token: 'old', refresh_token: 'recovery', expires_at: '2000-01-01' }, async (url, init) => {
    calls.push([url, init])
    if (url.endsWith('/auth/refresh')) {
      return response({ access_token: 'renewed', refresh_token: 'recovery', expires_at: '2100-01-01' })
    }
    assert.equal(init.headers.Authorization, 'Bearer renewed')
    return response({ holdings: [{ symbol: 'TEST' }] })
  })
  await Promise.all([api.investorProfileAPI.getPortfolio(), api.investorProfileAPI.getPortfolio()])
  assert.equal(calls.filter(([url]) => url.endsWith('/auth/refresh')).length, 1)
  assert.equal(calls.some(([url]) => url.endsWith('/auth/guest')), false)
  assert.equal(JSON.parse(calls[0][1].body).refresh_token, 'recovery')
  assert.equal(JSON.parse(storage.get('boomerang.guestToken.v1')).access_token, 'renewed')
})

test('401 from refresh discards the credential, mints one new guest and retries once', async () => {
  const calls = []
  const { api, storage } = client({ access_token: 'old', refresh_token: 'stale', expires_at: '2000-01-01' }, async (url, init) => {
    calls.push([url, init])
    if (url.endsWith('/auth/refresh')) return response({ detail: 'Guest credentials could not be renewed' }, 401)
    if (url.endsWith('/auth/guest')) {
      return response({ access_token: 'fresh', refresh_token: 'fresh-recovery', expires_at: '2100-01-01' })
    }
    return init.headers.Authorization === 'Bearer fresh' ? response({ holdings: [] }) : response({}, 401)
  })
  await api.investorProfileAPI.getPortfolio()
  const urls = calls.map(([url]) => url)
  assert.deepEqual(urls.slice(0, 2), ['/api/auth/refresh', '/api/auth/guest'])
  assert.equal(urls.filter(url => url.endsWith('/auth/refresh')).length, 1)
  assert.equal(urls.filter(url => url.endsWith('/auth/guest')).length, 1)
  assert.equal(urls.length, 3) // refresh, guest, one successful request retry
  assert.equal(calls[2][1].headers.Authorization, 'Bearer fresh')
  const stored = JSON.parse(storage.get('boomerang.guestToken.v1'))
  assert.equal(stored.access_token, 'fresh')
  assert.equal(stored.refresh_token, 'fresh-recovery')
})

test('request that gets a 401 with a still-fresh token recovers via refresh 401 then one guest', async () => {
  const calls = []
  const { api, storage } = client({ access_token: 'rotated', refresh_token: 'rotated', expires_at: '2100-01-01' }, async (url, init) => {
    calls.push(url)
    if (url.endsWith('/auth/refresh')) return response({ detail: 'nope' }, 401)
    if (url.endsWith('/auth/guest')) return response({ access_token: 'fresh', refresh_token: 'r2', expires_at: '2100-01-01' })
    return init.headers.Authorization === 'Bearer fresh' ? response({ holdings: [] }) : response({}, 401)
  })
  await api.investorProfileAPI.getPortfolio()
  assert.equal(calls.length, 4) // original request, refresh, guest, one retry
  assert.deepEqual(calls.slice(1, 3), ['/api/auth/refresh', '/api/auth/guest'])
  assert.equal(calls[0], calls[3])
  assert.equal(calls.filter(url => url.endsWith('/auth/guest')).length, 1)
  assert.equal(JSON.parse(storage.get('boomerang.guestToken.v1')).access_token, 'fresh')
})

test('a 403 from refresh is also definitive', async () => {
  const urls = []
  const { api } = client({ access_token: 'old', expires_at: '2000-01-01' }, async url => {
    urls.push(url)
    if (url.endsWith('/auth/refresh')) return response({ detail: 'forbidden' }, 403)
    if (url.endsWith('/auth/guest')) return response({ access_token: 'fresh', expires_at: '2100-01-01' })
    return response({ holdings: [] })
  })
  await api.investorProfileAPI.getPortfolio()
  assert.equal(urls.filter(url => url.endsWith('/auth/guest')).length, 1)
})

test('concurrent callers during a 401 refresh share one refresh and one guest call', async () => {
  const urls = []
  let releaseRefresh
  const gate = new Promise(resolve => { releaseRefresh = resolve })
  const { api } = client({ access_token: 'old', refresh_token: 'stale', expires_at: '2000-01-01' }, async (url, init) => {
    urls.push(url)
    if (url.endsWith('/auth/refresh')) {
      await gate
      return response({ detail: 'Guest credentials could not be renewed' }, 401)
    }
    if (url.endsWith('/auth/guest')) return response({ access_token: 'fresh', refresh_token: 'r', expires_at: '2100-01-01' })
    assert.equal(init.headers.Authorization, 'Bearer fresh')
    return response({ holdings: [] })
  })
  const calls = Promise.all([
    api.investorProfileAPI.getPortfolio(), api.investorProfileAPI.getPortfolio(), api.getGuestToken(),
  ])
  await new Promise(resolve => setTimeout(resolve, 10))
  releaseRefresh()
  await calls
  assert.equal(urls.filter(url => url.endsWith('/auth/refresh')).length, 1)
  assert.equal(urls.filter(url => url.endsWith('/auth/guest')).length, 1)
})

test('a failing /guest after a 401 refresh does not loop and reports a replacement failure', async () => {
  const urls = []
  const { api, storage } = client({ access_token: 'old', expires_at: '2000-01-01' }, async url => {
    urls.push(url)
    return url.endsWith('/auth/refresh') ? response({ detail: 'bad' }, 401) : response({ detail: 'Too many requests. Please try again later.' }, 429)
  })
  await assert.rejects(api.investorProfileAPI.getPortfolio(), /no longer valid.*new one could not be started.*wait a while/s)
  assert.deepEqual(urls, ['/api/auth/refresh', '/api/auth/guest'])
  assert.equal(storage.has('boomerang.guestToken.v1'), false)
  // the next call is a first-time client: straight to /guest, still no refresh loop
  await assert.rejects(api.investorProfileAPI.getPortfolio())
  assert.deepEqual(urls.slice(2), ['/api/auth/guest'])
})

test('a 401 from /guest itself never loops', async () => {
  const urls = []
  const { api } = client(null, async url => { urls.push(url); return response({ detail: 'nope' }, 401) })
  await assert.rejects(api.getGuestToken(), /nope/)
  assert.deepEqual(urls, ['/api/auth/guest'])
})

for (const [label, status, message] of [
  ['5xx', 503, /could not renew your session right now.*saved session was kept/s],
  ['429', 429, /Too many session renewal attempts.*saved session was kept/s],
]) {
  test(`${label} from refresh preserves the credential and creates no guest`, async () => {
    const original = { access_token: 'old', refresh_token: 'recovery', expires_at: '2000-01-01' }
    const urls = []
    const { api, storage } = client(original, async url => {
      urls.push(url)
      return response({ detail: 'transient' }, status)
    })
    await assert.rejects(api.investorProfileAPI.getPortfolio(), message)
    assert.deepEqual(urls, ['/api/auth/refresh'])
    assert.deepEqual(JSON.parse(storage.get('boomerang.guestToken.v1')), original)
  })
}

test('network failure during refresh preserves the credential, creates no guest and reads as a network error', async () => {
  const original = { access_token: 'old', refresh_token: 'recovery', expires_at: '2000-01-01' }
  const urls = []
  const { api, storage } = client(original, async url => {
    urls.push(url)
    throw new TypeError('Failed to fetch')
  })
  await assert.rejects(api.investorProfileAPI.getPortfolio(), err => {
    assert.equal(api.isLikelyNetworkError(err), true)
    assert.match(api.extractErrorMessage(err), /Unable to reach the server/)
    return true
  })
  assert.deepEqual(urls, ['/api/auth/refresh'])
  assert.deepEqual(JSON.parse(storage.get('boomerang.guestToken.v1')), original)
})

test('401 retries renew the same saved credential', async () => {
  let requests = 0
  const { api } = client({ access_token: 'old', refresh_token: 'recovery', expires_at: '2100-01-01' }, async (url, init) => {
    if (url.endsWith('/auth/refresh')) {
      assert.equal(JSON.parse(init.body).refresh_token, 'recovery')
      return response({ access_token: 'new', refresh_token: 'recovery', expires_at: '2100-01-01' })
    }
    requests++
    return init.headers.Authorization === 'Bearer old' ? response({}, 401) : response({ holdings: [] })
  })
  await api.investorProfileAPI.getPortfolio()
  assert.equal(requests, 2)
})

test('only a first-time client issues a new guest identity', async () => {
  const urls = []
  const { api } = client(null, async url => {
    urls.push(url)
    return response({ access_token: 'first', refresh_token: 'recovery', expires_at: '2100-01-01' })
  })
  assert.equal(await api.getGuestToken(), 'first')
  assert.deepEqual(urls, ['/api/auth/guest'])
})
