'use client';

import { useEffect, useState, useCallback } from 'react';
import { marketAPI, fredAPI, extractErrorMessage } from '@/lib/api';

// --- Constants & Styles ---
const CARD_GLOW = "group relative rounded-2xl border border-white/[0.07] bg-white/[0.03] backdrop-blur-xl shadow-[0_0_24px_rgba(79,70,229,0.04)] hover:shadow-[0_0_32px_rgba(79,70,229,0.12)] hover:border-indigo-500/20 hover:bg-white/[0.05] transition-all duration-500 overflow-hidden hover:-translate-y-1";
// v2: v1 snapshots could contain hard-coded placeholder prices, so they are never read back.
const CACHE_KEY = 'bloomberg_market_data_v2';
const CACHE_TTL = 4 * 60 * 60 * 1000; // 4 hours
const UNAVAILABLE = 'Unavailable';

type MarketItem = {
  name: string;
  id: string;
  /** null when the provider returned no value (rendered as "Unavailable"). */
  change_percent: number | null;
  /** null when the provider returned no value (rendered as "Unavailable"). */
  price: number | null;
  sym: string;
};

type MarketsPayload = {
  globalIndices: MarketItem[];
  commodities: MarketItem[];
  fxPairs: MarketItem[];
  macroRates: MarketItem[];
};

type MarketStatus = 'loading' | 'live' | 'cached' | 'unavailable';

type QuotePoint = {
  value?: number;
  price?: number;
  change_pct?: number;
};

const asQuotePoint = (value: unknown): QuotePoint =>
  typeof value === 'object' && value !== null ? (value as QuotePoint) : {};

const finiteNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

// Card labels only; no prices live here. A card without a real value renders "Unavailable".
type CardDef = { name: string; id: string; sym: string };

const INDEX_DEFS: CardDef[] = [
  { name: 'S&P 500', id: 'SPX', sym: '$' },
  { name: 'NASDAQ 100', id: 'NDX', sym: '$' },
  { name: 'NIFTY 50', id: 'NIFTY', sym: '₹' },
  { name: 'DOW JONES', id: 'DJI', sym: '$' },
  { name: 'SENSEX', id: 'BSESN', sym: '₹' },
];

const COMMODITY_DEFS: CardDef[] = [
  { name: 'Gold Spot', id: 'GOLD', sym: '$' },
  { name: 'WTI Crude', id: 'WTI', sym: '$' },
  { name: 'Brent Crude', id: 'BRENT', sym: '$' },
  { name: 'Silver Spot', id: 'SILVER', sym: '$' },
];

const FX_DEFS: CardDef[] = [
  { name: 'EUR / USD', id: 'EURUSD', sym: '' },
  { name: 'USD / JPY', id: 'USDJPY', sym: '' },
  { name: 'GBP / USD', id: 'GBPUSD', sym: '' },
];

const MACRO_DEFS: CardDef[] = [
  { name: 'US 10Y Yield', id: 'US10Y', sym: '%' },
  { name: 'VIX Index', id: 'VIX', sym: '' },
  { name: 'DXY Index', id: 'DXY', sym: '' },
];

const toItem = (def: CardDef, price: unknown, change: unknown, invertChange = false): MarketItem => {
  const p = finiteNumber(price);
  if (p === null || p <= 0) return { ...def, price: null, change_percent: null };
  const c = finiteNumber(change);
  return { ...def, price: p, change_percent: c === null ? null : invertChange && c !== 0 ? -c : c };
};

const emptyPayload = (): MarketsPayload => ({
  globalIndices: INDEX_DEFS.map((d) => toItem(d, null, null)),
  commodities: COMMODITY_DEFS.map((d) => toItem(d, null, null)),
  fxPairs: FX_DEFS.map((d) => toItem(d, null, null)),
  macroRates: MACRO_DEFS.map((d) => toItem(d, null, null)),
});

const payloadItems = (payload: MarketsPayload): MarketItem[] => [
  ...payload.globalIndices, ...payload.commodities, ...payload.fxPairs, ...payload.macroRates,
];

const hasAnyPrice = (payload: MarketsPayload): boolean =>
  payloadItems(payload).some((item) => item.price !== null);

// Maps the FRED (value) and yfinance overview (price) responses onto the cards. Missing -> null.
function buildPayload(fredData: Record<string, unknown>, overview: Record<string, unknown>): MarketsPayload {
  const f = (id: string) => asQuotePoint(fredData[id]);
  const o = (id: string) => asQuotePoint(overview[id]);
  const gcf = o('GC=F');
  const goldFromOverview = (finiteNumber(gcf.price) ?? 0) > 0;
  const goldFred = f('GOLDAMGBD228NLBM');
  return {
    globalIndices: [
      toItem(INDEX_DEFS[0], f('SP500').value, f('SP500').change_pct),
      toItem(INDEX_DEFS[1], f('NASDAQ100').value, f('NASDAQ100').change_pct),
      toItem(INDEX_DEFS[2], o('^NSEI').price, o('^NSEI').change_pct),
      toItem(INDEX_DEFS[3], f('DJIA').value, f('DJIA').change_pct),
      toItem(INDEX_DEFS[4], o('^BSESN').price, o('^BSESN').change_pct),
    ],
    commodities: [
      goldFromOverview
        ? toItem(COMMODITY_DEFS[0], gcf.price, gcf.change_pct)
        : toItem(COMMODITY_DEFS[0], goldFred.value, goldFred.change_pct),
      toItem(COMMODITY_DEFS[1], f('DCOILWTICO').value, f('DCOILWTICO').change_pct),
      toItem(COMMODITY_DEFS[2], f('DCOILBRENTEU').value, f('DCOILBRENTEU').change_pct),
      toItem(COMMODITY_DEFS[3], f('NASDAQQSLVO').value, f('NASDAQQSLVO').change_pct),
    ],
    fxPairs: [
      toItem(FX_DEFS[0], f('DEXUSEU').value, f('DEXUSEU').change_pct),
      toItem(FX_DEFS[1], f('DEXJPUS').value, f('DEXJPUS').change_pct, true),
      toItem(FX_DEFS[2], f('DEXUSUK').value, f('DEXUSUK').change_pct),
    ],
    macroRates: [
      toItem(MACRO_DEFS[0], f('DGS10').value, f('DGS10').change_pct),
      toItem(MACRO_DEFS[1], f('VIXCLS').value, f('VIXCLS').change_pct),
      toItem(MACRO_DEFS[2], f('DTWEXBGS').value, f('DTWEXBGS').change_pct),
    ],
  };
}

// Re-validates a stored snapshot against the card definitions; unknown/invalid values become null.
function normalizePayload(payload: unknown): MarketsPayload | null {
  if (!payload || typeof payload !== 'object') return null;
  const obj = payload as Record<string, unknown>;
  const section = (value: unknown, defs: CardDef[]): MarketItem[] => {
    const stored = Array.isArray(value) ? value.filter((x): x is Record<string, unknown> => typeof x === 'object' && x !== null) : [];
    return defs.map((def) => {
      const hit = stored.find((x) => x.id === def.id);
      return toItem(def, hit?.price, hit?.change_percent);
    });
  };
  const normalized: MarketsPayload = {
    globalIndices: section(obj.globalIndices, INDEX_DEFS),
    commodities: section(obj.commodities, COMMODITY_DEFS),
    fxPairs: section(obj.fxPairs, FX_DEFS),
    macroRates: section(obj.macroRates, MACRO_DEFS),
  };
  return hasAnyPrice(normalized) ? normalized : null;
}

// Header badge. "live" only for a successful fetch that returned data; "cached" only when the
// response says so explicitly or a stored snapshot is being shown; otherwise "unavailable".
function deriveMarketStatus(input: { fetchOk: boolean; hasData: boolean; cachedFlag?: boolean; fromStoredSnapshot?: boolean }): MarketStatus {
  if (input.fromStoredSnapshot) return 'cached';
  if (!input.fetchOk || !input.hasData) return 'unavailable';
  return input.cachedFlag === true ? 'cached' : 'live';
}

const STATUS_LABEL: Record<MarketStatus, string> = {
  loading: 'Loading',
  live: 'Live',
  cached: 'Cached',
  unavailable: 'Unavailable',
};

const formatPrice = (item: MarketItem, symbol: string): string => {
  if (item.price === null) return UNAVAILABLE;
  const digits = item.price < 10 ? 4 : 2;
  return `${symbol}${item.price.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
};

const formatChange = (item: MarketItem): string => {
  if (item.change_percent === null) return UNAVAILABLE;
  return `${item.change_percent >= 0 ? '+' : ''}${item.change_percent.toFixed(2)}%`;
};

// --- Components ---
function MarketCard({ item, symbol, size = 'md' }: { item: MarketItem; symbol: string; size?: 'md' | 'lg' }) {
  const isUp = item.change_percent !== null && item.change_percent >= 0;
  const isLarge = size === 'lg';

  return (
    <div className={`${CARD_GLOW} ${isLarge ? 'p-7' : 'p-6'}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="heading-text text-[14px] text-white/80 truncate">
            {item.name}
          </div>
        </div>
        <div className={`shrink-0 data-text text-[10px] font-semibold px-2.5 py-1 rounded border ${isUp ? 'border-indigo-500/20 bg-indigo-500/5 text-indigo-300' : 'border-white/5 bg-white/2 text-white/25'}`}>
          {formatChange(item)}
        </div>
      </div>

      <div className={`metric-text glow-text text-white tabular-nums tracking-tight leading-none ${isLarge ? 'text-[30px] mt-4' : 'text-[26px] mt-3'}`}>
        {formatPrice(item, symbol)}
      </div>

      <div className="flex items-center justify-between mt-2">
        <span className="data-text text-[10px] text-white/45 uppercase tracking-[0.28em]">{item.id}</span>
      </div>
    </div>
  );
}

function MarketSection({ title, items, symbol }: { title: string; items: MarketItem[]; symbol: string }) {
    if (!items || items.length === 0) return null;
    return (
        <section className="space-y-5">
            <div className="flex items-center gap-3">
                <div className="w-1.5 h-1.5 rounded-full bg-indigo-500 shadow-[0_0_8px_rgba(99,102,241,0.6)]" />
                <span className="data-text text-[10px] text-white/60 uppercase tracking-[0.35em] font-medium">{title}</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5">
                {items.map(item => <MarketCard key={item.id} item={item} symbol={item.sym || symbol} />)}
            </div>
        </section>
    );
}

export default function MarketsPage() {
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<MarketStatus>('loading');
  const [cacheInfo, setCacheInfo] = useState<{ used: boolean; timestamp: number | null }>({ used: false, timestamp: null });
  const [data, setData] = useState<MarketsPayload>(emptyPayload);

  const loadFromCache = useCallback((allowExpired = false) => {
    try {
      const cached = localStorage.getItem(CACHE_KEY);
      if (!cached) return false;

      const parsed = JSON.parse(cached);
      const payload = normalizePayload(parsed?.payload);
      const timestamp = Number(parsed?.timestamp);
      const validTimestamp = Number.isFinite(timestamp) && timestamp > 0;
      if (!payload || !validTimestamp) return false;

      const isFresh = Date.now() - timestamp < CACHE_TTL;
      if (isFresh || allowExpired) {
        setData(payload);
        setCacheInfo({ used: true, timestamp });
        setStatus(deriveMarketStatus({ fetchOk: true, hasData: true, fromStoredSnapshot: true }));
        return true;
      }
    } catch (e) {
      console.error('Failed to load cache:', e);
    }
    return false;
  }, []);

  const saveToCache = (payload: MarketsPayload) => {
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify({
        payload,
        timestamp: Date.now()
      }));
    } catch (e) {
      console.error('Failed to save cache:', e);
      setError('Unable to persist market snapshot in local cache.');
    }
  };

  const fetchAllData = async (force = false) => {
    try {
      setError(null);
      const fredSeries = [
        'SP500', 'DJIA', 'NASDAQ100', 
        'DCOILWTICO', 'DCOILBRENTEU', 'NASDAQQSLVO',
        'DEXUSEU', 'DEXJPUS', 'DEXUSUK',
        'DGS10', 'VIXCLS', 'DTWEXBGS'
      ];

      // 1. Fetch FRED Data
      const fredResponse = force 
        ? await fredAPI.getLatestLive(fredSeries)
        : await fredAPI.getLatestCached(fredSeries);
      
      const fredData = (fredResponse?.data as Record<string, unknown> | undefined) || {};

      // 2. Fetch yfinance Data (Indices + Gold)
      const overviewRes = await marketAPI.getOverview();
      const overviewIndices = (overviewRes?.indices as Record<string, unknown> | undefined) || {};

      // 3. Mapping Logic (missing values stay null and render as "Unavailable")
      const payload = buildPayload(fredData, overviewIndices);
      const hasData = hasAnyPrice(payload);
      const cachedFlag = (fredResponse as { cached?: unknown } | undefined)?.cached === true
        || (overviewRes as { cached?: unknown } | undefined)?.cached === true;

      if (!hasData) {
        // Nothing real came back: show a stored snapshot (labelled as such) or Unavailable.
        if (loadFromCache(true)) {
          setError('Live refresh returned no data. Showing cached market snapshot.');
          return;
        }
        setData(payload);
        setCacheInfo({ used: false, timestamp: null });
        setStatus(deriveMarketStatus({ fetchOk: true, hasData: false }));
        setError('Market data is currently unavailable.');
        return;
      }

      setData(payload);
      saveToCache(payload);
      setCacheInfo({ used: false, timestamp: null });
      setStatus(deriveMarketStatus({ fetchOk: true, hasData: true, cachedFlag }));
      setError(null);
    } catch (err) {
      console.error('Fetch error:', err);
      // Keep UI useful by falling back to stale cache if live fetch fails.
      const usedStaleCache = loadFromCache(true);
      if (usedStaleCache) {
        setError('Live refresh failed. Showing cached market snapshot.');
        return;
      }
      setStatus(deriveMarketStatus({ fetchOk: false, hasData: false }));
      setError(extractErrorMessage(err, 'Failed to fetch market data.'));
    }
  };

  const doRefresh = async () => {
    setRefreshing(true);
    await fetchAllData(true);
    await new Promise(r => setTimeout(r, 600));
    setRefreshing(false);
  };

  useEffect(() => {
    // localStorage only exists in the browser, so the cached snapshot can only be read after mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    const hasCache = loadFromCache();
    // Always try background refresh so cache appears immediately but data stays current.
    void fetchAllData(!hasCache);
  }, [loadFromCache]);

  const displayData = data;

  return (
    <div className="space-y-12 pb-20 relative">
      <div
        className="pointer-events-none absolute inset-0"
        style={{ background: 'radial-gradient(circle at 70% 20%, rgba(79,107,255,0.08), transparent 55%)' }}
      />
      
      {/* Universal Header */}
      <header className="flex items-center justify-between sticky top-0 z-20 bg-black/70 backdrop-blur-xl py-5 border-b border-white/5">
        <div className="flex items-center gap-4">
          <div className="flex flex-col">
            <span className="data-text text-[10px] text-white/40 uppercase tracking-[0.32em]">Global Markets</span>
            <span className="heading-text text-[26px] text-white/90 tracking-[-0.01em]">Unified Terminal</span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className={`w-1.5 h-1.5 rounded-full ${status === 'live' ? 'bg-indigo-500' : 'bg-white/30'} ${refreshing ? 'animate-pulse' : ''}`} />
            <span className={`data-text text-[10px] uppercase tracking-widest ${status === 'live' ? 'text-indigo-400' : 'text-white/45'}`}>{STATUS_LABEL[status]}</span>
          </div>
          <button 
            onClick={doRefresh}
            disabled={refreshing}
            className="px-6 py-2 rounded-xl bg-indigo-500/10 backdrop-blur-xl border border-indigo-500/30 text-indigo-300 hover:bg-indigo-500/20 hover:border-indigo-500/50 hover:text-white disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-300 data-text text-[10px] uppercase tracking-[0.28em] shadow-[0_0_15px_rgba(99,102,241,0.06)] hover:shadow-[0_0_22px_rgba(99,102,241,0.18)]"
          >
            {refreshing ? 'SYNCHRONIZING...' : 'REFRESH_TERMINAL'}
          </button>
        </div>
      </header>

      {/* Single Page Sections */}
      <div className="space-y-16 relative z-10">
        {error && (
          <div className="rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        )}

        {cacheInfo.used && cacheInfo.timestamp && (
          <div className="rounded-xl border border-indigo-400/20 bg-indigo-500/10 px-4 py-3 text-xs text-indigo-200">
            Showing cached market snapshot from {new Date(cacheInfo.timestamp).toLocaleString()}.
          </div>
        )}

        <section className="space-y-5">
          <div className="flex items-center gap-3">
            <div className="w-1.5 h-1.5 rounded-full bg-indigo-500 shadow-[0_0_8px_rgba(99,102,241,0.6)]" />
            <span className="data-text text-[10px] text-white/60 uppercase tracking-[0.35em] font-medium">World Indices</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {displayData.globalIndices.slice(0, 2).map(item => (
              <MarketCard key={item.id} item={item} symbol={item.sym} size="lg" />
            ))}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5">
            {displayData.globalIndices.slice(2).map(item => (
              <MarketCard key={item.id} item={item} symbol={item.sym} />
            ))}
          </div>
        </section>

        <MarketSection title="Resource Desk" items={displayData.commodities} symbol="$" />
        <MarketSection title="FX Oracle" items={displayData.fxPairs} symbol="" />
        <MarketSection title="Macro Stability" items={displayData.macroRates} symbol="" />
      </div>

      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar { width: 3px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(99, 102, 241, 0.1); border-radius: 10px; }
      `}</style>
    </div>
  );
}
