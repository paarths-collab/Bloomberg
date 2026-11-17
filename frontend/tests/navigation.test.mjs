import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

const navigationModule = { exports: {} }
vm.runInNewContext(ts.transpileModule(fs.readFileSync(new URL('../lib/navigation.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports: navigationModule.exports })
const { navigation, primaryNavigation } = navigationModule.exports

test('every navigation destination exists and appears once', () => {
  assert.equal(new Set(navigation.map(item => item.href)).size, navigation.length)
  for (const item of navigation) {
    assert.ok(fs.existsSync(new URL(`../app${item.href === '/' ? '' : item.href}/page.tsx`, import.meta.url)), item.href)
  }
  assert.deepEqual(Array.from(primaryNavigation, item => item.href), ['/', '/portfolio', '/help'])
})

test('retired placeholder pages are absent', () => {
  for (const route of ['blog', 'ecosystem', 'network', 'profile', 'settings']) {
    assert.equal(fs.existsSync(new URL(`../app/${route}/page.tsx`, import.meta.url)), false)
  }
})
