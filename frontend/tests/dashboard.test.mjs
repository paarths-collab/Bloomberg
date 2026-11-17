import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import React from 'react'
import * as jsxRuntime from 'react/jsx-runtime'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

test('dashboard renders unavailable data before fetching, without sample balances or prices', () => {
  const source = fs.readFileSync(new URL('../app/dashboard/page.tsx', import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText
  const clientModule = { exports: {} }
  vm.runInNewContext(compiled, {
    module: clientModule, exports: clientModule.exports,
    require: name => {
      if (name === 'react') return React
      if (name === 'react/jsx-runtime') return jsxRuntime
      if (name === '@/lib/api') return {}
      throw new Error(`Unexpected dependency: ${name}`)
    },
  })
  const html = renderToStaticMarkup(React.createElement(clientModule.exports.default))
  assert.match(html, /Unavailable/)
  assert.match(html, /Watchlist data unavailable/)
  assert.doesNotMatch(html, /NVDA|68,345|87\.5%|5,842\.47|SYNC_OK/)
})
