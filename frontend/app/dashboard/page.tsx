'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { marketAPI, fredAPI, investorProfileAPI, extractErrorMessage } from '@/lib/api'

// ─── Constants ────────────────────────────────────────────────────────────────

const CARD = "system-card group relative p-6 rounded-2xl border border-white/20 bg-white/[0.03] backdrop-blur-xl hover:border-indigo-400/40 hover:bg-white/5 transition-all duration-500 overflow-hidden hover:-translate-y-1"
const CARD_GLOW = "system-card group relative p-6 rounded-2xl border border-white/25 bg-white/[0.035] backdrop-blur-xl shadow-[0_0_24px_rgba(99,102,241,0.06)] hover:shadow-[0_0_32px_rgba(99,102,241,0.12)] hover:border-indigo-400/50 hover:bg-white/8 transition-all duration-500 overflow-hidden hover:-translate-y-1"

// ─── Market Data ──────────────────────────────────────────────────────────────
const INDICES_US = [
  { symbol: 'SPY', name: 'S&P 500', price: null as number | null, change: null as number | null, pct: null as number | null },
  { symbol: 'QQQ', name: 'NASDAQ', price: null as number | null, change: null as number | null, pct: null as number | null },
  { symbol: 'DJI', name: 'Dow Jones', price: null as number | null, change: null as number | null, pct: null as number | null },
  { symbol: 'VIX', name: 'Volatility', price: null as number | null, change: null as number | null, pct: null as number | null },
]

const INDICES_IN = [
  { symbol: 'NIFTY', name: 'Nifty 50', price: null as number | null, change: null as number | null, pct: null as number | null },
  { symbol: 'SENSEX', name: 'Sensex', price: null as number | null, change: null as number | null, pct: null as number | null },
  { symbol: 'BANK', name: 'Bank Nifty', price: null as number | null, change: null as number | null, pct: null as number | null },
  { symbol: 'MIDCAP', name: 'Midcap 100', price: null as number | null, change: null as number | null, pct: null as number | null },
]

const FRED = [
  { id: 'FEDFUNDS', title: 'Fed Funds Rate', value: null as number | null, unit: '%' },
  { id: 'CPIAUCSL', title: 'CPI Inflation', value: null as number | null, unit: '%' },
  { id: 'UNRATE', title: 'Unemployment', value: null as number | null, unit: '%' },
  { id: 'DGS10', title: '10Y Treasury', value: null as number | null, unit: '%' },
]

const RBI = [
  { id: 'REPO', title: 'Repo Rate', value: null as number | null, unit: '%' },
  { id: 'INDIA_CPI', title: 'India CPI', value: null as number | null, unit: '%' },
  { id: 'INDIA_GDP', title: 'GDP Growth', value: null as number | null, unit: '%' },
  { id: 'USD_INR', title: 'USD/INR', value: null as number | null, unit: '' },
]

function TimeDisplay() {
  const [time, setTime] = useState<string | null>(null)
  useEffect(() => {
    const fmt = () => {
      const now = new Date()
      return [now.getHours(), now.getMinutes(), now.getSeconds()]
        .map(n => String(n).padStart(2, '0')).join(':')
    }
    // First tick is deferred (not a synchronous setState in the effect); still client-only to avoid a hydration mismatch.
    const first = setTimeout(() => setTime(fmt()), 0)
    const id = setInterval(() => setTime(fmt()), 1000)
    return () => { clearTimeout(first); clearInterval(id) }
  }, [])
  if (!time) return null
  return <span className="text-indigo-400 data-text tabular-nums">{time}</span>
}

function useCountUp(value: number, duration = 700) {
  const [display, setDisplay] = useState(value)
  const prev = useRef(value)
  const raf = useRef<number>()

  useEffect(() => {
    const from = prev.current
    const to = value
    const start = performance.now()
    const animate = (t: number) => {
      const elapsed = t - start
      const p = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - p, 3)
      const next = from + (to - from) * eased
      setDisplay(next)
      if (p < 1) {
        raf.current = requestAnimationFrame(animate)
      } else {
        prev.current = to
      }
    }
    raf.current = requestAnimationFrame(animate)
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current)
    }
  }, [value, duration])

  return display
}

type BackendHolding = {
  symbol: string
  quantity: number
  avg_price: number
  current_price: number | null
  current_value: number | null
  pl: number | null
  pl_pct: number | null
}

type HoldingRow = {
  symbol: string
  qty: number
  avg: number
  ltp: number | null
  value: number | null
  pl: number | null
  pct: number | null
}

const UNAVAILABLE = 'Unavailable'
const quoteValue = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) ? v : null

function IndexCard({ idx, symbol }: { idx: typeof INDICES_US[0]; symbol: string }) {
  const isUp = idx.pct !== null && idx.pct >= 0

  return (
    <div className={CARD_GLOW}>
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="data-text text-[11px] tracking-[0.28em] text-white/30 uppercase mb-0.5">{idx.symbol}</div>
          <div className="data-text text-[13px] tracking-[0.12em] text-white/55 uppercase">{idx.name}</div>
        </div>
        <div className={`data-text text-[11px] font-medium px-2 py-1 rounded border ${isUp ? 'border-indigo-500/25 bg-indigo-500/8 text-indigo-400' : 'border-white/8 bg-white/3 text-white/35'}`}>
          {idx.pct === null ? UNAVAILABLE : `${isUp ? '+' : ''}${idx.pct.toFixed(2)}%`}
        </div>
      </div>

      <div className="metric-text glow-text primary-text text-[32px] tabular-nums tracking-tight mb-5 leading-none">
        {idx.price === null ? UNAVAILABLE : `${symbol}${idx.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
      </div>


    </div>
  )
}

function FredCard({ m }: { m: typeof FRED[0] }) {
  return (
    <div className={CARD_GLOW}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="data-text text-[10px] text-white/25 tracking-[0.28em] uppercase">{m.id}</span>
        <span className="data-text text-[9px] text-indigo-400/60">{m.value === null ? 'UNAVAILABLE' : 'CACHED'}</span>
      </div>
      <div className="data-text text-[13px] text-white/50 mb-2">{m.title}</div>
      <div className="metric-text glow-text primary-text text-[28px] mb-4 tabular-nums tracking-tight leading-none">
        {m.value === null ? UNAVAILABLE : m.value.toFixed(2)}<span className="text-[16px] text-white/35 ml-0.5">{m.unit}</span>
      </div>

    </div>
  )
}

type Market = 'us' | 'india'

export default function DashboardPage() {
  const [market, setMarket] = useState<Market>('us')
  const [refreshing, setRefreshing] = useState(false)
  const [indices, setIndices] = useState(market === 'us' ? INDICES_US : INDICES_IN)
  const [holdings, setHoldings] = useState<HoldingRow[]>([])
  const [portfolioStatus, setPortfolioStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const watchlist: { symbol: string; price: number; change: number; pct: number; vol: string }[] = []
  const [macro, setMacro] = useState(market === 'us' ? FRED : RBI)
  const [error, setError] = useState<string | null>(null)
  // Beta / Sharpe of the current holdings from GET .../portfolio/risk (null = unavailable).
  const [risk, setRisk] = useState<{ status: 'loading' | 'done'; beta: number | null; sharpe: number | null }>({ status: 'loading', beta: null, sharpe: null })

  const isUS = market === 'us'
  const sym = isUS ? '$' : '₹'
  const INDICES = indices
  const HOLDINGS = holdings
  const WATCHLIST = watchlist
  const MACRO = macro

  const loadBackendData = useCallback(async () => {
    setRefreshing(true)
    setPortfolioStatus('loading')
    setError(null)
    try {
      const [overview, portfolio, fredSnapshot]: [any, any, any] = await Promise.all([
        marketAPI.getOverview(),
        investorProfileAPI.getPortfolio(),
        fredAPI.getLatestCached(['FEDFUNDS', 'CPIAUCSL', 'UNRATE', 'DGS10']),
      ])

      if (Array.isArray(portfolio?.holdings) && portfolio.holdings.length) {
        setRisk(r => ({ ...r, status: 'loading' }))
        investorProfileAPI.getRisk()
          .then(res => {
            const metricValue = (m?: { value: number | null; status: string }) =>
              m && m.status === 'ok' && typeof m.value === 'number' && Number.isFinite(m.value) ? m.value : null
            setRisk({ status: 'done', beta: metricValue(res?.metrics?.beta), sharpe: metricValue(res?.metrics?.sharpe_ratio) })
          })
          .catch(() => setRisk({ status: 'done', beta: null, sharpe: null }))
      } else {
        setRisk({ status: 'done', beta: null, sharpe: null })
      }

      setPortfolioStatus('ready')
      const overviewIndices = overview?.indices || {}
      const fredData = fredSnapshot?.data || {}

      if (market === 'us') {
        setIndices([
          { symbol: 'SPY', name: 'S&P 500', price: quoteValue(overviewIndices.SP500?.price), change: quoteValue(overviewIndices.SP500?.change_pct), pct: quoteValue(overviewIndices.SP500?.change_pct) },
          { symbol: 'QQQ', name: 'NASDAQ', price: quoteValue(overviewIndices.NASDAQ100?.price), change: quoteValue(overviewIndices.NASDAQ100?.change_pct), pct: quoteValue(overviewIndices.NASDAQ100?.change_pct) },
          { symbol: 'DJI', name: 'Dow Jones', price: quoteValue(overviewIndices.DJIA?.price), change: quoteValue(overviewIndices.DJIA?.change_pct), pct: quoteValue(overviewIndices.DJIA?.change_pct) },
          { symbol: 'VIX', name: 'Volatility', price: quoteValue(overviewIndices.VIXCLS?.price), change: quoteValue(overviewIndices.VIXCLS?.change_pct), pct: quoteValue(overviewIndices.VIXCLS?.change_pct) },
        ])
        setHoldings(Array.isArray(portfolio?.holdings) && portfolio.holdings.length ? portfolio.holdings.map((h: BackendHolding) => ({
          symbol: h.symbol,
          qty: h.quantity,
          avg: h.avg_price,
          ltp: h.current_price,
          value: h.current_value,
          pl: h.pl,
          pct: h.pl_pct,
        })) : [])
        setMacro([
          { id: 'FEDFUNDS', title: 'Fed Funds Rate', value: quoteValue(fredData.FEDFUNDS?.value), unit: '%' },
          { id: 'CPIAUCSL', title: 'CPI Inflation', value: quoteValue(fredData.CPIAUCSL?.value), unit: '%' },
          { id: 'UNRATE', title: 'Unemployment', value: quoteValue(fredData.UNRATE?.value), unit: '%' },
          { id: 'DGS10', title: '10Y Treasury', value: quoteValue(fredData.DGS10?.value), unit: '%' },
        ])
      } else {
        setIndices([
          { symbol: 'NIFTY', name: 'Nifty 50', price: quoteValue(overviewIndices['^NSEI']?.price), change: quoteValue(overviewIndices['^NSEI']?.change_pct), pct: quoteValue(overviewIndices['^NSEI']?.change_pct) },
          { symbol: 'SENSEX', name: 'Sensex', price: quoteValue(overviewIndices['^BSESN']?.price), change: quoteValue(overviewIndices['^BSESN']?.change_pct), pct: quoteValue(overviewIndices['^BSESN']?.change_pct) },
          { symbol: 'BANK', name: 'Bank Nifty', price: quoteValue(overviewIndices['^NSEBANK']?.price), change: quoteValue(overviewIndices['^NSEBANK']?.change_pct), pct: quoteValue(overviewIndices['^NSEBANK']?.change_pct) },
          { symbol: 'MIDCAP', name: 'Midcap 100', price: quoteValue(overviewIndices['^NIFTYMCAP100']?.price), change: quoteValue(overviewIndices['^NIFTYMCAP100']?.change_pct), pct: quoteValue(overviewIndices['^NIFTYMCAP100']?.change_pct) },
        ])
        setHoldings(Array.isArray(portfolio?.holdings) && portfolio.holdings.length ? portfolio.holdings.map((h: BackendHolding) => ({
          symbol: h.symbol,
          qty: h.quantity,
          avg: h.avg_price,
          ltp: h.current_price,
          value: h.current_value,
          pl: h.pl,
          pct: h.pl_pct,
        })) : [])
        setMacro(RBI)
      }
    } catch (err) {
      setPortfolioStatus('error')
      setHoldings([])
      setIndices(market === 'us' ? INDICES_US : INDICES_IN)
      setMacro(market === 'us' ? FRED : RBI)
      setRisk({ status: 'done', beta: null, sharpe: null })
      setError(extractErrorMessage(err, 'Failed to load dashboard data from backend.'))
    } finally {
      setRefreshing(false)
    }
  }, [market])

  useEffect(() => {
    void loadBackendData()
  }, [loadBackendData])

  // Totals only exist when every holding could be priced; otherwise they are unavailable (never 0).
  const valuationComplete = portfolioStatus === 'ready' && HOLDINGS.every(h => h.value !== null && h.pl !== null)
  const portfolioVal: number | null = valuationComplete ? HOLDINGS.reduce((a, h) => a + (h.value ?? 0), 0) : null
  const portfolioPL: number | null = valuationComplete ? HOLDINGS.reduce((a, h) => a + (h.pl ?? 0), 0) : null
  const portfolioPct = portfolioVal !== null && portfolioPL !== null
    ? (portfolioVal === portfolioPL ? '0.00' : ((portfolioPL / (portfolioVal - portfolioPL)) * 100).toFixed(2))
    : null
  const animatedPortfolioVal = useCountUp(portfolioVal ?? 0, 800)
  const animatedPortfolioPL = useCountUp(portfolioPL ?? 0, 800)
  const animatedExposure = useCountUp(risk.beta ?? 0, 700)
  const animatedRisk = useCountUp(risk.sharpe ?? 0, 700)
  const riskText = (animated: number, value: number | null) =>
    risk.status === 'loading' ? '…' : value === null ? UNAVAILABLE : animated.toFixed(2)

  const doRefresh = async () => {
    await loadBackendData()
  }

  const fmtVal = (n: number) =>
    isUS
      ? `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

  return (
    <div className="dashboard-bg dashboard-scope space-y-8 relative">

      {/* ── Terminal Header ── */}
      <div className="relative z-10 space-y-5">
        {error && (
          <div className="rounded-xl border border-amber-400/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
            {error}
          </div>
        )}
        <div className="flex items-center gap-3">
          <span className="w-1.5 h-6 rounded-full bg-indigo-400/80 shadow-[0_0_16px_rgba(129,140,248,0.6)]" />
          <span className="data-text text-[12px] text-white/65 tracking-[0.32em] uppercase">
            Terminal
          </span>
          <div className="flex-1 h-px bg-white/10" />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-white/15 bg-white/[0.02] backdrop-blur-xl">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="data-text text-[10px] text-white/60 uppercase tracking-[0.24em]">System Status</span>
          </div>
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-white/10 bg-white/[0.015]">
            <span className="data-text text-[10px] text-indigo-200/90 uppercase tracking-[0.22em]">AI STATUS UNAVAILABLE</span>
          </div>
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-white/10 bg-white/[0.015]">
            <span className="data-text text-[10px] text-white/55 uppercase tracking-[0.22em]">CONFIDENCE UNAVAILABLE</span>
          </div>
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-white/10 bg-white/[0.015]">
            <span className="data-text text-[10px] text-white/55 uppercase tracking-[0.22em]">
              STREAM {isUS ? 'FRED' : 'RBI/NSE'}
            </span>
          </div>
        </div>

        <div className="flex items-center justify-between gap-6">
          <div>
            <h1 className="heading-text glow-text text-[30px] text-white tracking-[-0.01em] flex items-center gap-4">
              Analytics Terminal
              <span className="inline-flex items-center gap-2 px-2.5 py-1 text-[10px] border border-indigo-400/40 rounded-full text-indigo-200/90 bg-indigo-500/10">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-300 animate-pulse" />
                LATEST SNAPSHOT
              </span>
            </h1>
            <p className="data-text text-[11px] meta-text mt-2 tracking-[0.18em] uppercase">
              <TimeDisplay /> · STREAM {isUS ? 'FRED' : 'RBI/NSE'}
            </p>
          </div>

          {/* Controls */}
          <div className="flex items-center gap-3">
            {/* Market Toggle */}
            <div className="flex items-center border border-white/15 rounded-lg overflow-hidden data-text text-[11px] tracking-widest">
              <button
                onClick={() => setMarket('us')}
                className={`px-4 py-2 transition-all ${isUS ? 'bg-indigo-500/15 text-white shadow-lg' : 'text-white/40 hover:text-white hover:bg-white/5'}`}
              >
                $ US
              </button>
              <div className="w-px h-5 bg-white/15" />
              <button
                onClick={() => setMarket('india')}
                className={`px-4 py-2 transition-all ${!isUS ? 'bg-indigo-500/15 text-white shadow-lg' : 'text-white/40 hover:text-white hover:bg-white/5'}`}
              >
                ₹ INDIA
              </button>
            </div>

            <button
              onClick={doRefresh}
              className="px-4 py-2 rounded-lg border border-indigo-400/30 bg-indigo-500/10 backdrop-blur-xl text-indigo-200/90 hover:text-white hover:bg-indigo-500/20 transition-all data-text text-[11px] uppercase tracking-widest"
            >
              {refreshing ? 'REFRESHING...' : 'REFRESH'}
            </button>
          </div>
        </div>
      </div>

      {/* ── System Metrics ── */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 relative z-10">
        {[
          { label: 'Portfolio Value', val: portfolioVal === null ? UNAVAILABLE : fmtVal(animatedPortfolioVal), sub: portfolioPct === null ? 'PRICES_UNAVAILABLE' : `${Number(portfolioPct) >= 0 ? '+' : ''}${portfolioPct}% TOTAL`, glow: true },
          { label: 'Unrealized P&L', val: portfolioPL === null ? UNAVAILABLE : `${portfolioPL >= 0 ? '+' : ''}${fmtVal(animatedPortfolioPL)}`, sub: portfolioPL === null ? 'PRICES_UNAVAILABLE' : 'ESTIMATED_VALUE', glow: false },
          { label: 'Exposure Index', val: riskText(animatedExposure, risk.beta), sub: risk.status === 'done' && risk.beta === null ? 'UNAVAILABLE' : 'SYSTEM_CALCULATED', glow: false },
          { label: 'Risk Efficiency', val: riskText(animatedRisk, risk.sharpe), sub: risk.status === 'done' && risk.sharpe === null ? 'UNAVAILABLE' : 'SHARPE_ANNUAL', glow: false },
        ].map(card => (
          <div key={card.label} className={card.glow ? CARD_GLOW : CARD}>
            <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 bg-[radial-gradient(circle_at_top_right,rgba(79,107,255,0.18),transparent_60%)]" />
            <div className="section-title meta-text mb-3">{card.label}</div>
            <div className="metric-text glow-text primary-text text-[28px] mb-1.5 tabular-nums leading-none">{card.val}</div>
            <div className="data-text text-[10px] secondary-text tracking-widest">{card.sub}</div>
          </div>
        ))}
      </div>

      {/* ── Market Field ── */}
      <section className="relative z-10">
        <div className="flex items-center gap-3 mb-5">
          <div className="w-6 h-[1px] bg-indigo-400/40" />
          <span className="section-title meta-text">Market Field · {isUS ? 'US' : 'INDIA'}</span>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          {INDICES.map(idx => <IndexCard key={idx.symbol} idx={idx} symbol={sym} />)}
        </div>
      </section>

      {/* ── Portfolio + Watchlist ── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 relative z-10">
        {/* Holdings */}
        <div className="lg:col-span-2 rounded-2xl border border-white/[0.07] bg-white/[0.03] backdrop-blur-xl overflow-hidden">
          <div className="px-6 py-4 border-b border-white/[0.05] flex items-center justify-between">
          <span className="data-text text-[11px] text-white/35 uppercase tracking-[0.2em] font-medium">Live Holdings</span>
          <span className="metric-text primary-text text-[15px] tabular-nums">{portfolioVal === null ? UNAVAILABLE : fmtVal(portfolioVal)}</span>
        </div>
        <div className="p-4 space-y-1.5">
          {portfolioStatus === 'ready' && !HOLDINGS.length && <p className="p-4 text-sm text-white/50">No positions yet.</p>}
          {HOLDINGS.map(h => (
            <div key={h.symbol} className="flex items-center justify-between px-4 py-3 rounded-xl border border-white/[0.03] hover:border-white/[0.1] hover:bg-white/[0.03] transition-all cursor-default">
              <div>
                <div className="data-text text-[14px] text-white tracking-wide">{h.symbol}</div>
                <div className="data-text text-[11px] text-white/30 mt-0.5">{h.qty} × {sym}{h.avg.toFixed(0)}</div>
              </div>
              <div className="text-right">
                <div className="metric-text primary-text text-[14px] tabular-nums">{h.value === null ? UNAVAILABLE : fmtVal(h.value)}</div>
                <div className={`data-text text-[11px] font-medium mt-0.5 ${h.pct !== null && h.pct >= 0 ? 'text-indigo-400' : 'text-white/30'}`}>
                  {h.pct === null ? UNAVAILABLE : `${h.pct >= 0 ? '+' : ''}${h.pct.toFixed(2)}%`}
                </div>
              </div>
            </div>
          ))}
        </div>
        <div className="px-6 py-3.5 border-t border-white/[0.05] flex justify-between data-text text-[12px]">
          <span className="text-white/25 uppercase tracking-wider">TOTAL P&L</span>
          <span className={`metric-text tabular-nums ${portfolioPL !== null && portfolioPL >= 0 ? 'text-indigo-400' : 'text-white/35'}`}>
            {portfolioPL === null ? UNAVAILABLE : `${portfolioPL >= 0 ? '+' : ''}${fmtVal(portfolioPL)} (${portfolioPct}%)`}
          </span>
        </div>
      </div>

        {/* Watchlist */}
        <div className="lg:col-span-3 rounded-2xl border border-white/[0.07] bg-white/[0.03] backdrop-blur-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-white/[0.05]">
          <span className="data-text text-[11px] text-white/35 uppercase tracking-[0.2em] font-medium">System Watchlist · {isUS ? 'NYSE / NASDAQ' : 'NSE / BSE'}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/[0.03]">
                {['Symbol', 'Price', 'Change', '% Chg', 'Volume'].map(h => (
                  <th key={h} className="px-6 py-3 text-left data-text text-[10px] text-white/18 uppercase tracking-[0.2em] font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {!WATCHLIST.length && <tr><td colSpan={5} className="px-6 py-4 text-white/50">Watchlist data unavailable.</td></tr>}
              {WATCHLIST.map(row => {
                const up = row.pct >= 0
                return (
                  <tr key={row.symbol} className="border-b border-white/[0.025] hover:bg-white/[0.025] transition-colors cursor-default">
                    <td className="px-6 py-3.5">
                      <span className="data-text text-[14px] text-white tracking-wide">{row.symbol}</span>
                    </td>
                    <td className="px-6 py-3.5 metric-text text-[13px] text-white tabular-nums">{sym}{row.price.toFixed(2)}</td>
                    <td className={`px-6 py-3.5 data-text text-[12px] tabular-nums ${up ? 'text-indigo-400' : 'text-white/30'}`}>
                      {up ? '+' : ''}{row.change.toFixed(2)}
                    </td>
                    <td className="px-6 py-3.5">
                      <span className={`data-text text-[12px] font-medium ${up ? 'text-indigo-400' : 'text-white/30'}`}>
                        {up ? '+' : ''}{row.pct.toFixed(2)}%
                      </span>
                    </td>
                    <td className="px-6 py-3.5 data-text text-[11px] text-white/22">{row.vol}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
      </div>

      {/* ── Macro Data ── */}
      <section className="relative z-10">
        <div className="flex items-center gap-3 mb-5">
          <div className="w-6 h-[1px] bg-indigo-500/40" />
          <span className="data-text text-[10px] text-white/25 uppercase tracking-[0.35em]">
            {isUS ? 'FRED Macro Data' : 'RBI / India Macro'}
          </span>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          {MACRO.map(m => <FredCard key={m.id} m={m} />)}
        </div>
      </section>

      {/* ── System Footer ── */}
      <div className="relative z-10 flex flex-wrap items-center gap-10 py-8 border-t border-white/[0.04]">
        {[
          { label: 'Agents', status: UNAVAILABLE },
          { label: 'Market Feed', status: error ? UNAVAILABLE : 'SNAPSHOT' },
          { label: 'Risk Engine', status: risk.status === 'loading' ? 'Loading' : 'Computed where available' },
          { label: 'Latency', status: UNAVAILABLE },
        ].map(s => (
          <div key={s.label} className="flex flex-col gap-1 opacity-25">
            <span className="data-text text-[10px] text-white/50 uppercase tracking-widest font-medium">{s.label}</span>
            <span className="data-text text-[11px] text-white font-medium">{s.status}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
