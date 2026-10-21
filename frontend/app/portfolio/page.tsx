'use client'

import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, Briefcase, ArrowUpRight, ArrowDownRight, PieChart } from 'lucide-react'
import { PieChart as RechartsPie, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import { investorProfileAPI, extractErrorMessage, type PortfolioRiskResponse } from '@/lib/api'

const COLORS = ['#f59e0b', '#3b82f6', '#22c55e', '#8b5cf6', '#ef4444', '#06b6d4']

// Prices, values and P&L are null when no live price is available (never coerced to 0).
type Holding = {
  symbol: string
  quantity: number
  avg_price: number
  current_price: number | null
  current_value: number | null
  pl: number | null
  pl_pct: number | null
}

type PortfolioData = {
  total_value: number | null
  total_invested: number
  total_pl: number | null
  total_pl_pct: number | null
  holdings: Holding[]
  valuation_complete: boolean
  unpriced_symbols: string[]
}

const UNAVAILABLE = 'Unavailable'

// null / undefined / non-finite -> null (rendered as unavailable); anything numeric -> number.
const numOrNull = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

const RISK_PERIOD_NOTE: Record<string, string> = { '6mo': 'Last 6m', '1y': 'Last 12m', '2y': 'Last 24m', '5y': 'Last 5y' }

type PieDatum = {
  name: string
  value: number
  pct: string
}

export default function PortfolioPage() {
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [risk, setRisk] = useState<PortfolioRiskResponse | null>(null)
  const [riskLoading, setRiskLoading] = useState(false)
  const [riskError, setRiskError] = useState<string | null>(null)

  const normalizePortfolio = (data: unknown): PortfolioData => {
    const obj = (typeof data === 'object' && data !== null) ? (data as Partial<PortfolioData>) : {}
    const holdings = Array.isArray(obj.holdings) ? obj.holdings : []
    const unpriced = Array.isArray(obj.unpriced_symbols) ? obj.unpriced_symbols.map(String) : []
    const normalizedHoldings = holdings.map((h) => ({
      symbol: String((h as Partial<Holding>).symbol ?? ''),
      quantity: Number((h as Partial<Holding>).quantity ?? 0),
      avg_price: Number((h as Partial<Holding>).avg_price ?? 0),
      current_price: numOrNull((h as Partial<Holding>).current_price),
      current_value: numOrNull((h as Partial<Holding>).current_value),
      pl: numOrNull((h as Partial<Holding>).pl),
      pl_pct: numOrNull((h as Partial<Holding>).pl_pct),
    }))
    return {
      total_value: numOrNull(obj.total_value),
      total_invested: Number(obj.total_invested ?? 0),
      total_pl: numOrNull(obj.total_pl),
      total_pl_pct: numOrNull(obj.total_pl_pct),
      holdings: normalizedHoldings,
      valuation_complete: typeof obj.valuation_complete === 'boolean'
        ? obj.valuation_complete
        : obj.total_value !== null && obj.total_value !== undefined,
      unpriced_symbols: unpriced.length
        ? unpriced
        : normalizedHoldings.filter((h) => h.current_value === null).map((h) => h.symbol),
    }
  }

  const fetchRisk = useCallback(async () => {
    setRiskLoading(true)
    setRiskError(null)
    try {
      setRisk(await investorProfileAPI.getRisk())
    } catch (err) {
      setRisk(null)
      setRiskError(extractErrorMessage(err, 'Risk metrics unavailable'))
    } finally {
      setRiskLoading(false)
    }
  }, [])

  const fetchPortfolio = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await investorProfileAPI.getPortfolio()
      const normalized = normalizePortfolio(data)
      setPortfolio(normalized)
      if (normalized.holdings.length) void fetchRisk()
      else { setRisk(null); setRiskError(null) }
    } catch (err) {
      // A failed fetch is an error state, not an empty portfolio.
      setPortfolio(null)
      setRisk(null)
      setError(extractErrorMessage(err, 'Portfolio service unavailable'))
    } finally {
      setLoading(false)
    }
  }, [fetchRisk])

  useEffect(() => { void fetchPortfolio() }, [fetchPortfolio])

  const holdings = portfolio?.holdings ?? []
  const totalValue = portfolio?.total_value ?? null
  const totalPl = portfolio?.total_pl ?? null
  const totalPlPct = portfolio?.total_pl_pct ?? null
  const unpricedSymbols = portfolio?.unpriced_symbols ?? []

  // Pie chart data: only holdings that could be priced can be allocated.
  const pricedHoldings = holdings.filter((h): h is Holding & { current_value: number } => h.current_value !== null)
  const pricedTotal = pricedHoldings.reduce((sum, h) => sum + h.current_value, 0)
  const pieData: PieDatum[] = pricedHoldings.map((h) => ({
    name: h.symbol,
    value: h.current_value,
    pct: (pricedTotal > 0 ? (h.current_value / pricedTotal) * 100 : 0).toFixed(1),
  }))

  if (loading) return (
    <div className="flex items-center justify-center h-[400px]">
      <div className="flex flex-col items-center gap-3">
        <RefreshCw className="animate-spin text-orange-400" size={28} />
        <span className="text-[12px] font-mono text-white/30">Loading portfolio…</span>
      </div>
    </div>
  )

  // Risk cards: computed by the backend; unavailable metrics show why instead of a number.
  const riskCard = (
    label: string,
    metric: { value: number | null; status: string; reason?: string } | undefined,
    format: (v: number) => string,
    okNote: string,
    okColor?: string,
  ) => {
    if (riskLoading) return { label, value: '…', note: 'Computing', color: 'text-white/40' }
    if (riskError) return { label, value: UNAVAILABLE, note: riskError, color: 'text-white/40' }
    if (!metric || metric.status !== 'ok' || metric.value === null || !Number.isFinite(metric.value)) {
      return { label, value: UNAVAILABLE, note: metric?.reason ?? 'Not computed', color: 'text-white/40' }
    }
    return { label, value: format(metric.value), note: okNote, color: okColor }
  }
  const riskMetrics = risk?.metrics
  const riskCards = [
    riskCard('Portfolio Beta', riskMetrics?.beta, (v) => v.toFixed(2), `vs ${risk?.benchmark ?? 'benchmark'}`),
    riskCard('Sharpe Ratio', riskMetrics?.sharpe_ratio, (v) => v.toFixed(2), 'Annualized'),
    riskCard('Max Drawdown', riskMetrics?.max_drawdown_pct, (v) => `${v.toFixed(1)}%`, RISK_PERIOD_NOTE[risk?.period ?? ''] ?? `Last ${risk?.period ?? ''}`.trim(), 'text-red-400'),
    riskCard('Volatility', riskMetrics?.volatility_annualized_pct, (v) => `${v.toFixed(1)}%`, 'Annualized'),
  ]

  const plAvailable = totalPl !== null
  const isUp = (totalPl ?? 0) >= 0

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-mono font-bold text-white">Portfolio</h1>
          <p className="text-[12px] font-mono text-white/30 mt-0.5">Holdings · Performance Attribution · Risk Exposure</p>
        </div>
        <button onClick={fetchPortfolio}
          className="flex items-center gap-2 px-4 py-2 bg-white/[0.03] border border-white/[0.08] rounded-xl text-white/40 hover:text-white hover:bg-white/[0.06] transition-all text-[12px] font-mono">
          <RefreshCw size={13} />
          Refresh
        </button>
      </div>

      {error ? (
        <div role="alert" className="flex flex-col items-center justify-center py-24 border border-red-400/30 bg-red-400/5 rounded-2xl text-red-200/80">
          <Briefcase size={48} strokeWidth={1} className="mb-4 opacity-40" />
          <h3 className="text-lg font-mono font-semibold text-red-200/90">Portfolio Unavailable</h3>
          <p className="text-[12px] font-mono mt-1">{error}</p>
        </div>
      ) : !holdings.length ? (
        <div className="flex flex-col items-center justify-center py-24 border border-white/[0.07] rounded-2xl text-white/25">
          <Briefcase size={48} strokeWidth={1} className="mb-4 opacity-40" />
          <h3 className="text-lg font-mono font-semibold text-white/30">No Positions Yet</h3>
          <p className="text-[12px] font-mono mt-1">Use the AI Command or Backtest pages to initiate positions.</p>
        </div>
      ) : (
        <>
          {!portfolio?.valuation_complete && (
            <div className="rounded-xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-200">
              Live prices are unavailable for {unpricedSymbols.length ? unpricedSymbols.join(', ') : 'some holdings'}; totals and P&L are unavailable until every holding can be priced.
            </div>
          )}

          {/* Summary Cards */}
          <div className="grid grid-cols-3 gap-4">
            <div className="p-5 rounded-xl border border-white/[0.07] bg-white/[0.02]">
              <div className="text-[10px] font-mono text-white/25 uppercase tracking-widest mb-2">Total Value</div>
              {totalValue === null ? (
                <div className="text-3xl font-mono font-bold text-white/40">{UNAVAILABLE}</div>
              ) : (
                <div className="text-3xl font-mono font-bold text-white">${totalValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
              )}
            </div>
            <div className="p-5 rounded-xl border border-white/[0.07] bg-white/[0.02]">
              <div className="text-[10px] font-mono text-white/25 uppercase tracking-widest mb-2">Total Invested</div>
              <div className="text-3xl font-mono font-bold text-white">${(portfolio?.total_invested ?? 0).toLocaleString()}</div>
            </div>
            <div className={`p-5 rounded-xl border ${!plAvailable ? 'border-white/[0.07] bg-white/[0.02]' : isUp ? 'border-emerald-400/20 bg-emerald-400/5' : 'border-red-400/20 bg-red-400/5'}`}>
              <div className="text-[10px] font-mono text-white/25 uppercase tracking-widest mb-2">Total P&L</div>
              {!plAvailable ? (
                <div className="text-3xl font-mono font-bold text-white/40">{UNAVAILABLE}</div>
              ) : (
                <div className={`text-3xl font-mono font-bold ${isUp ? 'text-emerald-400' : 'text-red-400'}`}>
                  {isUp ? '+' : ''}${totalPl.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  <span className="text-lg ml-2">({totalPlPct === null ? UNAVAILABLE : `${totalPlPct.toFixed(2)}%`})</span>
                </div>
              )}
            </div>
          </div>

          {/* Holdings Table + Allocation Pie */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            {/* Table */}
            <div className="lg:col-span-2 rounded-xl border border-white/[0.07] bg-white/[0.02] overflow-hidden">
              <div className="px-5 py-4 border-b border-white/[0.06]">
                <div className="text-[11px] font-mono text-white/30 uppercase tracking-widest">Holdings</div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-white/[0.05]">
                      {['Symbol', 'Qty', 'Avg Price', 'LTP', 'Value', 'P&L'].map(h => (
                        <th key={h} className="px-4 py-3 text-left text-[10px] font-mono text-white/25 uppercase tracking-widest font-normal">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {holdings.map((h) => {
                      const hUp = (h.pl ?? 0) >= 0
                      return (
                        <tr key={h.symbol} className="border-b border-white/[0.04] hover:bg-white/[0.03] transition-colors">
                          <td className="px-4 py-3.5">
                            <div className="flex items-center gap-2">
                              <div className="w-7 h-7 rounded-lg bg-white/[0.06] flex items-center justify-center text-[10px] font-mono font-bold text-white/50">
                                {h.symbol.slice(0, 2)}
                              </div>
                              <span className="font-mono text-[13px] font-semibold text-white">{h.symbol}</span>
                            </div>
                          </td>
                          <td className="px-4 py-3.5 font-mono text-[12px] text-white/60">{h.quantity}</td>
                          <td className="px-4 py-3.5 font-mono text-[12px] text-white/60">${h.avg_price.toFixed(2)}</td>
                          <td className="px-4 py-3.5 font-mono text-[13px] font-semibold text-white">
                            {h.current_price === null ? <span className="text-white/40">{UNAVAILABLE}</span> : `$${h.current_price.toFixed(2)}`}
                          </td>
                          <td className="px-4 py-3.5 font-mono text-[13px] text-white">
                            {h.current_value === null ? <span className="text-white/40">{UNAVAILABLE}</span> : `$${h.current_value.toLocaleString()}`}
                          </td>
                          <td className="px-4 py-3.5">
                            {h.pl === null ? (
                              <span className="font-mono text-[13px] text-white/40">{UNAVAILABLE}</span>
                            ) : (
                              <div className={`inline-flex flex-col items-end`}>
                                <div className={`font-mono text-[13px] font-bold flex items-center gap-1 ${hUp ? 'text-emerald-400' : 'text-red-400'}`}>
                                  {hUp ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                                  {hUp ? '+' : ''}${Math.abs(h.pl).toLocaleString()}
                                </div>
                                <span className={`text-[10px] font-mono ${hUp ? 'text-emerald-400/70' : 'text-red-400/70'}`}>
                                  ({hUp ? '+' : ''}{h.pl_pct === null ? UNAVAILABLE : `${h.pl_pct.toFixed(2)}%`})
                                </span>
                              </div>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Allocation Pie */}
            <div className="p-5 rounded-xl border border-white/[0.07] bg-white/[0.02]">
              <div className="text-[11px] font-mono text-white/30 uppercase tracking-widest mb-4 flex items-center gap-2">
                <PieChart size={13} className="text-orange-400" />
                Allocation
              </div>
              <ResponsiveContainer width="100%" height={200}>
                <RechartsPie>
                  <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={85} dataKey="value" paddingAngle={2}>
                    {pieData.map((_, i: number) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: '#0a0a0a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, fontSize: 11, fontFamily: 'monospace' }}
                    formatter={(value: any, _name: any, props: any) => [`$${Number(value).toLocaleString()} (${props.payload?.pct ?? '0.0'}%)`, props.payload?.name ?? '-']}
                  />
                </RechartsPie>
              </ResponsiveContainer>
              <div className="mt-4 space-y-2">
                {pieData.map((d, i: number) => (
                  <div key={d.name} className="flex items-center justify-between text-[11px] font-mono">
                    <div className="flex items-center gap-2">
                      <div className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                      <span className="text-white/60">{d.name}</span>
                    </div>
                    <span className="text-white/40">{d.pct}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Risk & Attribution */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {riskCards.map(card => (
              <div key={card.label} className="p-4 rounded-xl border border-white/[0.07] bg-white/[0.02]">
                <div className="text-[10px] font-mono text-white/25 uppercase tracking-widest mb-2">{card.label}</div>
                <div className={`text-xl font-mono font-bold ${card.color ?? 'text-white'}`}>{card.value}</div>
                <div className="text-[10px] font-mono text-white/25 mt-0.5">{card.note}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
