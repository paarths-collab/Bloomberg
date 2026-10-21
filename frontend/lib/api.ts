/* eslint-disable @typescript-eslint/no-explicit-any -- response shapes the backend leaves loose are typed `any` on purpose */
/**
 * Typed client for the FastAPI backend.
 *
 * Contract rules
 * - Every backend route the client calls is declared once in ./api-routes.json
 *   (id -> { method, path }). URLs are built ONLY from that file; there are no
 *   hand-written paths in this module. backend/tests/test_frontend_contract.py
 *   asserts every entry exists on backend.main.app with the same method/path.
 * - API_BASE is the relative "/api" by default: Next.js rewrites /api/* to the
 *   backend (see next.config.js). Set NEXT_PUBLIC_API_BASE to call a backend
 *   directly (it must include the "/api" segment, e.g. https://host/api).
 * - Investor-profile (paper portfolio) routes require `Authorization: Bearer
 *   <token>`. The token is an anonymous guest token from POST /api/auth/guest,
 *   cached in localStorage (all storage access is guarded). On a 401 the request
 *   is retried once with the current cached token if another call already
 *   refreshed it; only when the failing token is still the cached one is a new
 *   guest token forced. `user_id` is never sent: the backend derives identity
 *   from the token.
 *   Known limitation (frontend follow-up): the backend has no token-refresh
 *   endpoint, so a refresh (on expiry or a 401) mints a NEW guest identity via
 *   POST /api/auth/guest. The previous paper portfolio becomes unreachable from
 *   this client after that point.
 *
 * Route resolution notes (chosen from the BACKEND, not guessed):
 * - sentimentAPI.analyze(symbol, market) -> GET /api/chat/sentiment/analyze/{symbol}?market=
 *   The page passes a market and reads sentiment.overall / market_data / news /
 *   supply_chain. Only the GET handler accepts `market` (it appends ".NS" for
 *   india); POST /analyze takes just {symbol}, /quick/{symbol} returns a minimal
 *   shape without market_data/news/supply_chain. The GET response (and the
 *   service's fallback payload) contains exactly the keys the page normalises.
 * - investorProfileAPI.getPortfolio() -> GET /api/portfolio/api/investor-profile/portfolio
 *   /api/profile/portfolio is a thin alias of the same shared handler (see
 *   backend/profile/main.py), so either matches the shape the dashboard and
 *   portfolio pages read (holdings[], total_value, total_invested, total_pl,
 *   total_pl_pct). The nested path is the primary implementation.
 * - fundamentalsAPI.getOverview(symbol) -> GET /api/fundamentals/summary/{symbol}
 *   The peers page reads name/price/marketCap/exchange/sector/industry/currency/
 *   website/description/metrics.{peRatio,...}: the shape of
 *   get_fundamentals_summary(). backend/main.py declares this top-level route as
 *   the compatibility alias for the frontend's /api/fundamentals/* calls
 *   (/api/technical/fundamentals/summary/{symbol} is the same handler).
 * - socialAPI.getNews(query, limit) / getNewsCached(query, limit)
 *   -> GET /api/news/live?query=&limit= (and &cached_only=true).
 *   The news page reads `res.articles`; /api/news/latest returns a bare list,
 *   while /api/news/live returns {articles: [...]} and is the one that supports
 *   cached_only (used for the page's cached fallback). limit is bounded 1..50.
 * - treemapAPI.getIndexStocks(index, market, includePrices)
 *   -> GET /api/sectors/treemap/index/{index_id}?market=&include_prices=true|false
 *   The sectors page calls it twice: false (fast constituent skeleton) then true
 *   (live prices), matching the handler's `include_prices: bool` query param.
 * - fredAPI -> /api/fred/latest-live | latest-cached?series_ids=A,B (top-level
 *   mount, per the comment in backend/main.py); /api/markets/fred/* duplicates it.
 * - researchAPI -> /api/research/* (backend/research). /api/chat/api/research/*
 *   is an accidental duplicate mount of the legacy router and is not used.
 *   The report endpoints return downloadUrl WITHOUT the "/api" prefix
 *   (e.g. "/research/report/download/x.html"), which is why pages build
 *   `${API_BASE}${downloadUrl}` and why API_BASE must end in "/api".
 */

import routes from './api-routes.json'

// ─── Routes ──────────────────────────────────────────────────────────────────

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
type RouteDef = { method: string; path: string }

export type RouteId = keyof typeof routes
type RestRouteId = Exclude<RouteId, 'ws.live'>

/** Prefix shared by every REST route in api-routes.json. */
const ROUTE_PREFIX = '/api'

type QueryValue = string | number | boolean | null | undefined | ReadonlyArray<string | number>
type Query = Record<string, QueryValue>
type PathParams = Record<string, string | number>

const trimTrailingSlash = (s: string) => s.replace(/\/+$/, '')

/** Base for REST calls. Relative "/api" unless NEXT_PUBLIC_API_BASE is set. */
export const API_BASE: string =
  trimTrailingSlash(process.env.NEXT_PUBLIC_API_BASE || '') || ROUTE_PREFIX

function fillPath(template: string, params: PathParams = {}): string {
  return template.replace(/\{([^}]+)\}/g, (_m, name: string) => {
    const value = params[name]
    if (value === undefined || value === null || value === '') {
      throw new Error(`Missing path parameter "${name}" for ${template}`)
    }
    return encodeURIComponent(String(value))
  })
}

function encodeQuery(query?: Query): string {
  if (!query) return ''
  const sp = new URLSearchParams()
  for (const [key, raw] of Object.entries(query)) {
    if (raw === undefined || raw === null) continue
    const value = Array.isArray(raw) ? raw.join(',') : String(raw)
    if (Array.isArray(raw) && raw.length === 0) continue
    sp.append(key, value)
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

function routeDef(id: RestRouteId): RouteDef {
  const def = routes[id] as RouteDef
  if (!def.path.startsWith(`${ROUTE_PREFIX}/`)) {
    throw new Error(`Route ${id} is not a REST route under ${ROUTE_PREFIX}`)
  }
  return def
}

/** Full URL (API_BASE + route path with params and query) for a route id. */
export function buildUrl(id: RestRouteId, params?: PathParams, query?: Query): string {
  const def = routeDef(id)
  return `${API_BASE}${fillPath(def.path, params).slice(ROUTE_PREFIX.length)}${encodeQuery(query)}`
}

/**
 * ws(s):// URL for a websocket path such as "/ws/live".
 *
 * Resolution: NEXT_PUBLIC_BACKEND_URL (http(s) is mapped to ws(s)) when set;
 * otherwise the page's own origin, which only reaches the backend if the host
 * proxies WebSocket upgrades. Next.js rewrites do not proxy upgrades, so on
 * serverless hosts NEXT_PUBLIC_BACKEND_URL MUST be set for WebSockets to work.
 */
export function getWsUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`
  const backend = process.env.NEXT_PUBLIC_BACKEND_URL
  if (backend) {
    return `${trimTrailingSlash(backend).replace(/^http/i, 'ws')}${p}`
  }
  if (typeof window !== 'undefined' && window.location) {
    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
    return `${scheme}://${window.location.host}${p}`
  }
  return `ws://127.0.0.1:8001${p}`
}

// ─── Errors ──────────────────────────────────────────────────────────────────

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown
  constructor(message: string, status: number, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** Turn FastAPI `detail` (string | validation list | object) or `message` into text. */
function detailToMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (typeof d === 'string') return d
        if (d && typeof d === 'object') {
          const item = d as { msg?: unknown; loc?: unknown }
          const where = Array.isArray(item.loc)
            ? item.loc.filter((x) => x !== 'body' && x !== 'query').join('.')
            : ''
          const msg = typeof item.msg === 'string' ? item.msg : ''
          return where && msg ? `${where}: ${msg}` : msg || where
        }
        return ''
      })
      .filter(Boolean)
      .join('; ')
  }
  if (detail && typeof detail === 'object') {
    const o = detail as { message?: unknown; detail?: unknown }
    if (typeof o.message === 'string') return o.message
    if (typeof o.detail === 'string') return o.detail
  }
  return ''
}

const NETWORK_ERROR_RE =
  /failed to fetch|networkerror|network request failed|load failed|fetch failed|econnrefused|socket hang up/i

export function isLikelyNetworkError(err: unknown): boolean {
  if (err instanceof ApiError) return err.status === 0
  if (err instanceof TypeError) return true // fetch() rejects with TypeError when there is no response
  if (err instanceof Error) return NETWORK_ERROR_RE.test(err.message)
  if (typeof err === 'string') return NETWORK_ERROR_RE.test(err)
  return false
}

export function extractErrorMessage(err: unknown, fallback = 'Something went wrong'): string {
  if (isLikelyNetworkError(err)) {
    return 'Unable to reach the server. Check that the backend is running and try again.'
  }
  if (err instanceof ApiError) return err.message || fallback
  if (err instanceof Error) return err.message.trim() || fallback
  if (typeof err === 'string') return err.trim() || fallback
  if (err && typeof err === 'object') {
    const o = err as { detail?: unknown; message?: unknown }
    const text = detailToMessage(o.detail) || detailToMessage(o.message)
    if (text) return text
  }
  return fallback
}

// ─── Guest token (paper-portfolio auth) ──────────────────────────────────────

const TOKEN_STORAGE_KEY = 'boomerang.guestToken.v1'
const TOKEN_EXPIRY_SKEW_MS = 60_000

type StoredToken = { access_token: string; expires_at?: string }

let memoryToken: StoredToken | null = null
let tokenInflight: Promise<string> | null = null

function tokenIsFresh(t: StoredToken | null): t is StoredToken {
  if (!t || typeof t.access_token !== 'string' || !t.access_token) return false
  if (!t.expires_at) return true
  const exp = Date.parse(t.expires_at)
  return Number.isNaN(exp) || exp - TOKEN_EXPIRY_SKEW_MS > Date.now()
}

function readStoredToken(): StoredToken | null {
  try {
    if (typeof window === 'undefined' || !window.localStorage) return null
    const raw = window.localStorage.getItem(TOKEN_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredToken
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

function writeStoredToken(t: StoredToken | null): void {
  try {
    if (typeof window === 'undefined' || !window.localStorage) return
    if (t) window.localStorage.setItem(TOKEN_STORAGE_KEY, JSON.stringify(t))
    else window.localStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {
    // Storage blocked/full/unavailable: keep the in-memory token only.
  }
}

/**
 * Bearer token for the current anonymous guest identity. Issues one via
 * POST /api/auth/guest the first time (or when forceRefresh is set / the cached
 * token is expired) and caches it in memory + localStorage.
 */
export async function getGuestToken(forceRefresh = false): Promise<string> {
  if (!forceRefresh) {
    if (tokenIsFresh(memoryToken)) return memoryToken.access_token
    const stored = readStoredToken()
    if (tokenIsFresh(stored)) {
      memoryToken = stored
      return stored.access_token
    }
  }
  if (tokenInflight) return tokenInflight

  tokenInflight = (async () => {
    memoryToken = null
    writeStoredToken(null)
    const data = await request<{ access_token?: string; expires_at?: string }>('auth.guest', { auth: false })
    if (!data || typeof data.access_token !== 'string' || !data.access_token) {
      throw new ApiError('Guest token response was missing access_token', 502, data)
    }
    const token: StoredToken = { access_token: data.access_token, expires_at: data.expires_at }
    memoryToken = token
    writeStoredToken(token)
    return token.access_token
  })()
  try {
    return await tokenInflight
  } finally {
    tokenInflight = null
  }
}

// ─── Transport ───────────────────────────────────────────────────────────────

type RequestOptions = {
  params?: PathParams
  query?: Query
  body?: unknown
  /** Attach the guest bearer token (and refresh + retry once on a 401). */
  auth?: boolean
  signal?: AbortSignal
}

async function readBody(res: Response): Promise<unknown> {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

async function send(id: RestRouteId, opts: RequestOptions, token: string | null): Promise<Response> {
  const def = routeDef(id)
  const headers: Record<string, string> = { Accept: 'application/json' }
  const init: RequestInit = { method: def.method as HttpMethod, headers, signal: opts.signal }
  if (opts.body !== undefined && def.method !== 'GET') {
    headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(opts.body)
  }
  if (token) headers.Authorization = `Bearer ${token}`
  return fetch(buildUrl(id, opts.params, opts.query), init)
}

async function request<T>(id: RestRouteId, opts: RequestOptions = {}): Promise<T> {
  let token = opts.auth ? await getGuestToken() : null
  let res = await send(id, opts, token)

  if (res.status === 401 && opts.auth) {
    // Another call may already have refreshed the cached token; if so, retry with it
    // instead of minting yet another guest identity. Force a new token only when the
    // failing token is still the cached one.
    const cached = memoryToken
    token =
      tokenIsFresh(cached) && cached.access_token !== token
        ? cached.access_token
        : await getGuestToken(true)
    res = await send(id, opts, token)
  }

  const payload = await readBody(res)
  if (!res.ok) {
    const record = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : null
    const detail = record ? (record.detail ?? record.message ?? record.error) : payload
    const message =
      detailToMessage(detail) ||
      (typeof payload === 'string' && payload.trim() ? payload.trim().slice(0, 300) : '') ||
      `Request failed (${res.status}${res.statusText ? ` ${res.statusText}` : ''})`
    throw new ApiError(message, res.status, detail)
  }
  return payload as T
}

// ─── Shared types ────────────────────────────────────────────────────────────

/** Markets the backend accepts, in the casing each endpoint expects. */
export type MarketCode = 'us' | 'india'

export type Candle = {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume?: number
  [key: string]: unknown
}

// Chat / agents ---------------------------------------------------------------

/** Loose by design: the agent pipelines return heterogeneous JSON. */
export type SuperAgentResponse = Record<string, unknown>

export type SuperAgentRequest = {
  query: string
  ticker?: string
  market?: string
  portfolio?: Record<string, number>
  session_id?: string
  approved_plan?: Record<string, unknown>
}

export type MultiPovRequest = {
  symbol: string
  market?: string
  context?: string
}

export type AgentPov = {
  agent: string
  provider: string
  verdict: string
  confidence: number
  reasoning: string
  key_factors: string[]
}

export type MultiPovResponse = {
  symbol: string
  bull: AgentPov
  bear: AgentPov
  neutral: AgentPov
  [key: string]: unknown
}

// Sentiment / research --------------------------------------------------------

export type SentimentAnalysisResponse = {
  symbol: string
  name?: string
  market?: string
  price?: number | null
  day_change?: number | null
  day_change_pct?: number | null
  recommendation: string
  outlook: string
  sentiment: { overall: number; summary: string; [key: string]: unknown }
  reddit_sentiment: { score: number; mentions: number; [key: string]: unknown }
  market_data: Record<string, any>
  news: { articles: any[]; [key: string]: unknown }
  supply_chain: { customers: any[]; suppliers: any[]; [key: string]: unknown }
  // The service attaches provider-specific extras; keep them reachable.
  [key: string]: any
}

export type ReportResponse = {
  success?: boolean
  filename?: string
  /** Path WITHOUT the "/api" prefix, e.g. "/research/report/download/x.html". */
  downloadUrl?: string
  [key: string]: unknown
}

export type ResearchReportRequest = {
  symbol: string
  market?: string
  format?: 'quantstats'
  range?: string
  benchmark?: string
}

export type InterpretImageRequest = {
  symbol: string
  market?: MarketCode
  imageDataUrl: string
  context?: Record<string, unknown>
}

export type AnalysisResponse = { analysis: string; [key: string]: unknown }

// Backtest --------------------------------------------------------------------

export type BacktestRunRequest = {
  symbol: string
  market?: string
  strategy?: string
  strategies?: string[]
  range?: string
  interval?: string
  /** Flat strategy params, or keyed by strategy id. */
  params?: Record<string, unknown>
  start?: string
  end?: string
  /** Passed through when the caller supplies it; the backend defaults it otherwise. */
  initial_capital?: number
  commission_bps?: number
  slippage_bps?: number
  seed?: number
  lookback_days?: number
}

export type BacktestMetrics = Record<string, any>
export type BacktestTrade = Record<string, any>
export type BacktestMonteCarlo = Record<string, any>

export type BacktestSingleResponse = {
  symbol?: string
  strategy?: string
  /** Absent on single-strategy responses. */
  mode?: string
  initialCapital?: number
  metrics?: BacktestMetrics
  chartData?: Array<Record<string, any>>
  trades?: BacktestTrade[]
  equity_curve?: Array<Record<string, any>>
  monteCarlo?: BacktestMonteCarlo | null
  assumptions?: Record<string, unknown>
  [key: string]: unknown
}

export type BacktestMultiStrategyDetail = {
  name?: string
  color?: string
  /** null when that strategy failed; see `error`. */
  metrics?: BacktestMetrics | null
  trades?: BacktestTrade[]
  monteCarlo?: BacktestMonteCarlo | null
  equityCurve?: Array<{ date: string; value: number }>
  error?: string
  [key: string]: unknown
}

export type BacktestMultiStrategyResponse = {
  symbol?: string
  mode: 'multi_strategy'
  strategies: Record<string, BacktestMultiStrategyDetail>
  combinedChartData?: Array<Record<string, any>>
  benchmarkCurve?: Array<{ date: string; value: number }>
  ranking?: Array<{ strategy: string; return: number }>
  initialCapital?: number
  assumptions?: Record<string, unknown>
  [key: string]: unknown
}

export type BacktestRunResponse = BacktestSingleResponse | BacktestMultiStrategyResponse

export type BacktestInterpretRequest = {
  symbol: string
  market: 'US' | 'IN'
  selectedStrategies: string[]
  summary: Record<string, unknown>
}

export type BacktestInterpretImageRequest = {
  symbol: string
  market: 'US' | 'IN'
  selectedStrategies: string[]
  imageDataUrl: string
  context?: Record<string, unknown>
}

export type QuantstatsReportRequest = {
  symbol: string
  strategy: string
  range?: string
  params?: Record<string, unknown>
  benchmark?: string
  initial_capital?: number
  commission_bps?: number
  slippage_bps?: number
}

// Markets / macro / sectors ---------------------------------------------------

export type MarketOverviewResponse = {
  indices: Record<string, { price?: number | null; change_pct?: number | null; [key: string]: unknown }>
  [key: string]: unknown
}

export type CandlesResponse = {
  symbol: string
  market: string
  data: Candle[]
}

export type FredLatestResponse = {
  data: Record<string, { value?: number | null; change_pct?: number | null; [key: string]: unknown }>
  [key: string]: unknown
}

// Peers / fundamentals / news -------------------------------------------------

export type PeerRow = {
  symbol: string
  name?: string | null
  price?: number | null
  pe?: number | null
  market_cap?: number | null
  div_yield?: number | null
  net_profit_q?: number | null
  profit_q_var?: number | null
  sales_q?: number | null
  sales_q_var?: number | null
  roce?: number | null
  [key: string]: unknown
}

export type PeerComparisonResponse = {
  symbol?: string
  count?: number
  rows: PeerRow[]
  partial?: boolean
  message?: string
  [key: string]: unknown
}

export type FundamentalsSummaryResponse = {
  symbol?: string
  name?: string | null
  sector?: string | null
  industry?: string | null
  description?: string | null
  price?: number | null
  marketCap?: number | null
  currency?: string | null
  exchange?: string | null
  website?: string | null
  metrics?: Record<string, unknown>
  [key: string]: unknown
}

export type NewsArticle = {
  title?: string
  url?: string
  date?: string
  source?: string
  [key: string]: unknown
}

export type NewsResponse = {
  status?: string
  query?: string
  cached?: boolean
  stale?: boolean
  articles: NewsArticle[]
  [key: string]: unknown
}

// Paper portfolio (auth required) ---------------------------------------------

export type PortfolioHolding = {
  symbol: string
  quantity: number
  avg_price: number
  total_invested: number
  /** null when no live price is available (price_status === 'unavailable'). */
  current_price: number | null
  current_value: number | null
  pl: number | null
  pl_pct: number | null
  price_status: 'live' | 'unavailable' | string
}

export type PortfolioResponse = {
  holdings: PortfolioHolding[]
  total_invested: number
  /** Totals are null unless every holding could be priced. */
  total_value: number | null
  total_pl: number | null
  total_pl_pct: number | null
  valuation_complete: boolean
  unpriced_symbols: string[]
}

// ─── API objects ─────────────────────────────────────────────────────────────

export const superAgentAPI = {
  run: (body: SuperAgentRequest) =>
    request<SuperAgentResponse>('chat.superAgent', { body }),
}

export const stockAdvisorAPI = {
  multiPov: (body: MultiPovRequest) =>
    request<MultiPovResponse>('chat.stockAdvisorMultiPov', { body }),
}

export const sentimentAPI = {
  analyze: (symbol: string, market?: string) =>
    request<SentimentAnalysisResponse>('chat.sentimentAnalyze', {
      params: { symbol },
      query: { market },
    }),
}

export const researchAPI = {
  generateReport: (body: ResearchReportRequest) =>
    request<ReportResponse>('research.report', { body }),
  /** URL (not a fetch) of a generated report, for an <a href> / window.open. */
  downloadReport: (filename: string) =>
    buildUrl('research.reportDownload', { filename }),
  interpretImage: (body: InterpretImageRequest) =>
    request<AnalysisResponse>('research.interpretImage', { body }),
}

export const backtestAPI = {
  run: (body: BacktestRunRequest) =>
    request<BacktestRunResponse>('backtest.run', { body }),
  interpret: (body: BacktestInterpretRequest) =>
    request<AnalysisResponse>('backtest.interpret', { body }),
  interpretImage: (body: BacktestInterpretImageRequest) =>
    request<AnalysisResponse>('backtest.interpretImage', { body }),
  quantstatsReport: (body: QuantstatsReportRequest) =>
    request<ReportResponse>('backtest.quantstatsReport', { body }),
  downloadReport: (filename: string) =>
    buildUrl('backtest.reportDownload', { filename }),
}

export const marketAPI = {
  getOverview: () => request<MarketOverviewResponse>('markets.overview'),
  getCandles: (symbol: string, interval = '1d', range = '1y', market = 'US') =>
    request<CandlesResponse>('markets.candles', {
      params: { symbol },
      query: { interval, range, market },
    }),
}

export const fredAPI = {
  getLatestLive: (seriesIds?: string[]) =>
    request<FredLatestResponse>('fred.latestLive', { query: { series_ids: seriesIds } }),
  getLatestCached: (seriesIds?: string[]) =>
    request<FredLatestResponse>('fred.latestCached', { query: { series_ids: seriesIds } }),
}

export const treemapAPI = {
  getIndices: (market = 'india') =>
    request<any>('sectors.treemapIndices', { query: { market } }),
  getIndicesLive: (market = 'india') =>
    request<any>('sectors.treemapIndicesLive', { query: { market } }),
  getIndexStocks: (indexId: string, market = 'india', includePrices = true) =>
    request<any>('sectors.treemapIndex', {
      params: { index_id: indexId },
      query: { market, include_prices: includePrices },
    }),
  getStockDetails: (symbol: string, market = 'india') =>
    request<any>('sectors.treemapStock', { params: { symbol }, query: { market } }),
}

export const peersAPI = {
  compare: (symbol: string, limit = 12) =>
    request<PeerComparisonResponse>('peers.compare', { params: { symbol }, query: { limit } }),
}

export const fundamentalsAPI = {
  getOverview: (symbol: string) =>
    request<FundamentalsSummaryResponse>('fundamentals.summary', { params: { symbol } }),
}

export const socialAPI = {
  getNews: (query = 'stock market', limit = 10) =>
    request<NewsResponse>('news.live', { query: { query, limit } }),
  getNewsCached: (query = 'stock market', limit = 10) =>
    request<NewsResponse>('news.live', { query: { query, limit, cached_only: true } }),
}

export const investorProfileAPI = {
  /** Requires auth: sends the guest bearer token, refreshing it once on a 401. */
  getPortfolio: () =>
    request<PortfolioResponse>('investorProfile.portfolio', { auth: true }),
}

// ─── Formatting ──────────────────────────────────────────────────────────────

const PLACEHOLDER = '—'

/**
 * Compact, currency-prefixed number for the sectors detail panel.
 * marketCode 'IN' -> rupees in Indian units (L = lakh, Cr = crore, L Cr = lakh crore);
 * anything else -> dollars with K/M/B/T. Missing/non-finite values give "—".
 * The page strips the currency symbol for volumes via .replace(currency, '').
 */
export function formatLargeNumber(value: number | null | undefined, marketCode: string = 'US'): string {
  if (value === null || value === undefined || typeof value !== 'number' || !Number.isFinite(value)) {
    return PLACEHOLDER
  }
  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  const two = (n: number) => n.toFixed(2)

  if (String(marketCode).toUpperCase() === 'IN') {
    const c = '₹'
    if (abs >= 1e12) return `${sign}${c}${two(abs / 1e12)}L Cr`
    if (abs >= 1e7) return `${sign}${c}${two(abs / 1e7)}Cr`
    if (abs >= 1e5) return `${sign}${c}${two(abs / 1e5)}L`
    return `${sign}${c}${abs.toLocaleString('en-IN')}`
  }

  const c = '$'
  if (abs >= 1e12) return `${sign}${c}${two(abs / 1e12)}T`
  if (abs >= 1e9) return `${sign}${c}${two(abs / 1e9)}B`
  if (abs >= 1e6) return `${sign}${c}${two(abs / 1e6)}M`
  if (abs >= 1e3) return `${sign}${c}${two(abs / 1e3)}K`
  return `${sign}${c}${abs.toLocaleString('en-US')}`
}
