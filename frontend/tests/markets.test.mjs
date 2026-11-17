import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import React from 'react'
import * as jsxRuntime from 'react/jsx-runtime'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const source = fs.readFileSync(new URL('../app/markets/page.tsx', import.meta.url), 'utf8')

// Hard-coded prices/changes that used to be shown when the live fetch returned nothing.
const REMOVED_STATIC_VALUES = [
  '5,842.47', '5842.47', '20,378.92', '22,402.40', '43,192.05', '73,877.30',
  '2,242.10', '81.42', '86.50', '25.14', '1.0842', '149.85', '1.2741', '4.24', '16.31', '104.12',
]

// Loads the page in a VM. The page can only export its default component (a Next.js rule), so the
// small pure helpers are read from the same VM context instead of from exports.
function loadMarkets() {
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText
  const clientModule = { exports: {} }
  const context = vm.createContext({
    module: clientModule, exports: clientModule.exports,
    console,
    require: name => {
      if (name === 'react') return React
      if (name === 'react/jsx-runtime') return jsxRuntime
      if (name === '@/lib/api') return {}
      throw new Error(`Unexpected dependency: ${name}`)
    },
  })
  vm.runInContext(compiled, context)
  const helpers = vm.runInContext(
    '({ buildPayload, emptyPayload, hasAnyPrice, deriveMarketStatus, normalizePayload, formatPrice, formatChange, MarketCard })',
    context,
  )
  return { Page: clientModule.exports.default, helpers }
}

test('markets renders Unavailable before any data, without hard-coded prices or fake sync state', () => {
  const { Page } = loadMarkets()
  // `<style jsx global>` is compiled by Next at build time; plain React only warns about its props.
  const originalError = console.error
  console.error = () => {}
  let html
  try {
    html = renderToStaticMarkup(React.createElement(Page))
  } finally {
    console.error = originalError
  }
  assert.match(html, /Unavailable/)
  assert.doesNotMatch(html, /Live Syncing/)
  assert.doesNotMatch(html, /<svg|recharts/)
  for (const value of REMOVED_STATIC_VALUES) assert.ok(!html.includes(value), `unexpected static value ${value}`)
  // The badge must not claim "Live" without a successful fetch.
  assert.doesNotMatch(html, />Live</)
  assert.match(html, />Loading</)
})

test('empty or failed responses produce no values and an Unavailable status', () => {
  const { helpers } = loadMarkets()
  const payload = helpers.buildPayload({}, {})
  assert.equal(helpers.hasAnyPrice(payload), false)
  const items = [...payload.globalIndices, ...payload.commodities, ...payload.fxPairs, ...payload.macroRates]
  assert.ok(items.length > 0)
  for (const item of items) {
    assert.equal(item.price, null)
    assert.equal(item.change_percent, null)
  }
  // Non-numeric / missing garbage is also treated as missing, never defaulted.
  const garbage = helpers.buildPayload({ SP500: { value: 'x', change_pct: null }, VIXCLS: {} }, { '^NSEI': null })
  assert.equal(helpers.hasAnyPrice(garbage), false)
  assert.equal(helpers.deriveMarketStatus({ fetchOk: false, hasData: false }), 'unavailable')
  assert.equal(helpers.deriveMarketStatus({ fetchOk: true, hasData: false }), 'unavailable')
  assert.equal(helpers.formatPrice(payload.globalIndices[0], '$'), 'Unavailable')
  assert.equal(helpers.formatChange(payload.globalIndices[0]), 'Unavailable')
  const html = renderToStaticMarkup(React.createElement(helpers.MarketCard, { item: payload.macroRates[1], symbol: '' }))
  assert.match(html, /Unavailable/)
  assert.doesNotMatch(html, /16\.31|<svg/)
})

test('real returned values are mapped and rendered; only missing ones are Unavailable', () => {
  const { helpers } = loadMarkets()
  const payload = helpers.buildPayload(
    {
      SP500: { value: 1234.56, change_pct: -0.37 },
      VIXCLS: { value: 21.5, change_pct: 2 },
      DEXJPUS: { value: 140.25, change_pct: 0.5 },
    },
    { '^NSEI': { price: 9876.5, change_pct: 1.25 }, 'GC=F': { price: 3100.1, change_pct: 0.1 } },
  )
  assert.equal(helpers.hasAnyPrice(payload), true)
  const byId = Object.fromEntries(
    [...payload.globalIndices, ...payload.commodities, ...payload.fxPairs, ...payload.macroRates].map(i => [i.id, i]),
  )
  assert.equal(byId.SPX.price, 1234.56)
  assert.equal(byId.NIFTY.price, 9876.5)
  assert.equal(byId.GOLD.price, 3100.1)
  assert.equal(byId.VIX.price, 21.5)
  assert.equal(byId.USDJPY.change_percent, -0.5) // quoted inverse of the FRED series
  assert.equal(byId.NDX.price, null)
  assert.equal(byId.BSESN.price, null)
  assert.equal(byId.DXY.price, null)

  assert.equal(helpers.formatPrice(byId.SPX, '$'), '$1,234.56')
  assert.equal(helpers.formatChange(byId.SPX), '-0.37%')
  assert.equal(helpers.formatChange(byId.NIFTY), '+1.25%')
  const card = renderToStaticMarkup(React.createElement(helpers.MarketCard, { item: byId.SPX, symbol: '$' }))
  assert.match(card, /\$1,234\.56/)
  assert.match(card, /-0\.37%/)
  const missing = renderToStaticMarkup(React.createElement(helpers.MarketCard, { item: byId.NDX, symbol: '$' }))
  assert.match(missing, /Unavailable/)
})

test('status badge reflects real state only', () => {
  const { helpers } = loadMarkets()
  assert.equal(helpers.deriveMarketStatus({ fetchOk: true, hasData: true }), 'live')
  assert.equal(helpers.deriveMarketStatus({ fetchOk: true, hasData: true, cachedFlag: false }), 'live')
  assert.equal(helpers.deriveMarketStatus({ fetchOk: true, hasData: true, cachedFlag: true }), 'cached')
  assert.equal(helpers.deriveMarketStatus({ fetchOk: true, hasData: true, fromStoredSnapshot: true }), 'cached')
  assert.equal(helpers.deriveMarketStatus({ fetchOk: false, hasData: true }), 'unavailable')
})

test('stored snapshots never resurrect placeholder prices', () => {
  const { helpers } = loadMarkets()
  assert.equal(helpers.normalizePayload(null), null)
  assert.equal(helpers.normalizePayload({}), null)
  // A snapshot with no usable prices is rejected so the page falls back to Unavailable.
  assert.equal(helpers.normalizePayload({ globalIndices: [{ id: 'SPX', name: 'x', price: 0, change_percent: 0 }] }), null)
  const ok = helpers.normalizePayload({ globalIndices: [{ id: 'SPX', name: 'S&P 500', price: 1234.56, change_percent: 0.1 }] })
  assert.equal(ok.globalIndices[0].price, 1234.56)
  assert.equal(ok.globalIndices[1].price, null)
  assert.ok(/bloomberg_market_data_v2/.test(source))
})
