"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Bell, Bot, BrainCircuit, ChevronRight, Command, Gauge, Globe2, LayoutDashboard, LineChart, MessageSquareText, Search, Settings, Sparkles, Star, Zap } from "lucide-react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { getMarketOverview } from "@/lib/api";
import { MarketChart } from "@/components/market-chart";

const nav = [
  { label: "Overview", icon: LayoutDashboard, active: true },
  { label: "Markets", icon: LineChart },
  { label: "Research", icon: BrainCircuit },
  { label: "Agents", icon: Bot },
  { label: "Signals", icon: Activity },
  { label: "Global", icon: Globe2 },
];

const news = [
  ["00:02", "Macro", "Rates volatility eases as traders reprice the next policy window."],
  ["23:54", "Equities", "Semiconductor breadth improves into the close; defensives lag."],
  ["23:41", "FX", "Dollar basket holds range while yen volatility stays elevated."],
  ["23:22", "Energy", "Crude curve firms as prompt spreads tighten."],
];

const agentEvents = [
  ["Research agent", "Completed cross-asset morning scan", "2m"],
  ["Risk agent", "Portfolio beta moved inside target band", "8m"],
  ["Macro agent", "Flagged change in rate-sensitive factors", "14m"],
  ["News agent", "Compressed 43 stories into 6 market drivers", "21m"],
];

function formatPrice(value: number) {
  if (value >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

export default function HomePage() {
  const overview = useQuery({ queryKey: ["market-overview"], queryFn: getMarketOverview });
  const markets = overview.data?.indices ?? [];
  const source = overview.data?.source ?? "fallback";

  return (
    <main className="terminal">
      <aside className="rail">
        <div className="brand-mark">B</div>
        <nav className="rail-nav" aria-label="Primary navigation">
          {nav.map(({ label, icon: Icon, active }) => (
            <button className={active ? "rail-button active" : "rail-button"} key={label} aria-label={label}>
              <Icon size={18} strokeWidth={1.7} /><span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="rail-spacer" />
        <button className="rail-button" aria-label="Settings"><Settings size={18} strokeWidth={1.7} /><span>Settings</span></button>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="workspace-title"><span className="status-dot" /><span>Market OS</span><span className="slash">/</span><strong>Overview</strong></div>
          <button className="command-bar"><Search size={15} /><span>Search symbols, research, commands...</span><kbd><Command size={12} /> K</kbd></button>
          <div className="top-actions"><span className={source === "live" ? "source live" : "source"}>{source === "live" ? "LIVE" : "DEMO"}</span><button className="icon-button" aria-label="Notifications"><Bell size={16} /></button><div className="avatar">PC</div></div>
        </header>

        <div className="ticker-strip">
          {(markets.length ? markets : [
            { symbol: "SPX", name: "S&P 500", price: 6481.32, change: 24.18, changePercent: 0.37 },
            { symbol: "NDX", name: "Nasdaq 100", price: 23849.61, change: 112.24, changePercent: 0.47 },
            { symbol: "VIX", name: "Volatility", price: 15.84, change: -0.61, changePercent: -3.71 },
          ]).slice(0, 6).map((item) => (
            <div className="ticker" key={item.symbol}><span>{item.symbol}</span><strong>{formatPrice(item.price)}</strong><em className={item.changePercent >= 0 ? "up" : "down"}>{item.changePercent >= 0 ? "+" : ""}{item.changePercent.toFixed(2)}%</em></div>
          ))}
        </div>

        <div className="resizable">
          <Group orientation="horizontal">
            <Panel id="watchlist" defaultSize="22%" minSize="240px" className="pane">
              <section className="panel-section">
                <div className="panel-heading"><div><span className="eyebrow">Workspace</span><h2>Watchlist</h2></div><button className="icon-button"><Star size={15} /></button></div>
                <div className="watchlist">
                  {markets.slice(0, 8).map((item) => (
                    <button className="watch-row" key={item.symbol}><div><strong>{item.symbol}</strong><span>{item.name}</span></div><div className="watch-price"><strong>{formatPrice(item.price)}</strong><span className={item.changePercent >= 0 ? "up" : "down"}>{item.changePercent >= 0 ? "+" : ""}{item.changePercent.toFixed(2)}%</span></div></button>
                  ))}
                  {!markets.length && <div className="loading-card">Connecting to market service…</div>}
                </div>
              </section>
              <section className="panel-section compact-section"><div className="mini-card"><div className="mini-icon"><Gauge size={16} /></div><div><span>Risk regime</span><strong>Balanced</strong></div><ChevronRight size={14} /></div><div className="mini-card"><div className="mini-icon"><Zap size={16} /></div><div><span>Signals today</span><strong>14 active</strong></div><ChevronRight size={14} /></div></section>
            </Panel>

            <Separator className="separator" />

            <Panel id="market" defaultSize="56%" minSize="460px" className="pane center-pane">
              <section className="market-hero">
                <div className="hero-top"><div><span className="eyebrow">US Equities · Realtime workspace</span><div className="market-title-row"><h1>S&P 500</h1><span className="symbol-pill">SPX</span></div><div className="market-number">6,481.32 <span className="up">+24.18 · +0.37%</span></div></div><div className="range-tabs" role="tablist">{["1D", "5D", "1M", "3M", "1Y"].map((range, index) => <button className={index === 0 ? "active" : ""} key={range}>{range}</button>)}</div></div>
                <MarketChart />
              </section>

              <section className="metric-grid">{[["Breadth", "68.4%", "+4.2%"],["Volatility", "15.84", "-3.71%"],["10Y yield", "4.18%", "+2.1 bp"],["USD index", "98.42", "-0.16%"]].map(([label, value, delta]) => <div className="metric" key={label}><span>{label}</span><strong>{value}</strong><em>{delta}</em></div>)}</section>

              <section className="stream"><div className="section-title"><div><span className="eyebrow">Context</span><h2>Market stream</h2></div><button>View all <ChevronRight size={13} /></button></div>{news.map(([time, desk, headline]) => <article className="news-row" key={`${time}-${headline}`}><time>{time}</time><span className="desk">{desk}</span><p>{headline}</p></article>)}</section>
            </Panel>

            <Separator className="separator" />

            <Panel id="agents" defaultSize="22%" minSize="260px" className="pane">
              <section className="agent-panel">
                <div className="panel-heading"><div><span className="eyebrow">Agent layer</span><h2>Intelligence</h2></div><span className="agent-state"><span /> 4 online</span></div>
                <div className="agent-card featured"><div className="agent-card-top"><div className="agent-orb"><Sparkles size={17} /></div><span>Market copilot</span></div><p>Cross-asset context is ready. Ask for a thesis, risk check, or ticker breakdown.</p><div className="prompt-chips"><button>Explain today</button><button>Find anomalies</button></div></div>
                <div className="section-title small"><h3>Recent activity</h3><button><MessageSquareText size={14} /></button></div>
                <div className="agent-feed">{agentEvents.map(([name, event, age]) => <div className="agent-event" key={event}><div className="event-line"><span className="event-dot" /></div><div><div className="event-meta"><strong>{name}</strong><time>{age}</time></div><p>{event}</p></div></div>)}</div>
                <div className="ask-box"><textarea aria-label="Ask the market copilot" placeholder="Ask the market copilot…" rows={3} /><div><span>⌘ Enter</span><button><Sparkles size={14} /> Run</button></div></div>
              </section>
            </Panel>
          </Group>
        </div>
      </section>
    </main>
  );
}
