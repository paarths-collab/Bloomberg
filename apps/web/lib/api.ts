export type MarketPoint = {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
};

export type MarketOverview = {
  indices: MarketPoint[];
  updatedAt: string;
  source: "live" | "fallback";
};

export const API_BASE = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

const FALLBACK_MARKETS: MarketPoint[] = [
  { symbol: "SPX", name: "S&P 500", price: 6481.32, change: 24.18, changePercent: 0.37 },
  { symbol: "NDX", name: "Nasdaq 100", price: 23849.61, change: 112.24, changePercent: 0.47 },
  { symbol: "DJI", name: "Dow Jones", price: 45307.12, change: -56.48, changePercent: -0.12 },
  { symbol: "VIX", name: "Volatility", price: 15.84, change: -0.61, changePercent: -3.71 },
  { symbol: "GC", name: "Gold", price: 3471.7, change: 18.4, changePercent: 0.53 },
  { symbol: "BTC", name: "Bitcoin", price: 112420.0, change: 1260.0, changePercent: 1.13 },
];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { Accept: "application/json", "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Backend request failed (${response.status})`);
  return response.json() as Promise<T>;
}

function numberValue(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function normalizeOverview(payload: any): MarketPoint[] {
  const raw = payload?.indices ?? payload?.data?.indices ?? payload ?? {};
  const entries: Array<[string, any]> = Array.isArray(raw)
    ? raw.map((value, index) => [String(index), value] as [string, any])
    : Object.entries(raw as Record<string, any>);

  return entries.map(([key, value]) => {
    const price = numberValue(value?.price ?? value?.value ?? value?.close);
    const change = numberValue(value?.change ?? value?.change_value ?? value?.delta);
    const changePercent = numberValue(value?.change_percent ?? value?.changePercent ?? value?.pct_change ?? value?.percent_change);
    return {
      symbol: String(value?.symbol ?? key).replace(/^\^/, ""),
      name: String(value?.name ?? value?.label ?? key),
      price,
      change,
      changePercent,
    };
  }).filter((point) => point.price !== 0);
}

export async function getMarketOverview(): Promise<MarketOverview> {
  try {
    const payload = await request<any>("/api/markets/overview");
    const indices = normalizeOverview(payload);
    if (!indices.length) throw new Error("No market points returned");
    return { indices, updatedAt: new Date().toISOString(), source: "live" };
  } catch {
    return { indices: FALLBACK_MARKETS, updatedAt: new Date().toISOString(), source: "fallback" };
  }
}

export async function getHealth() {
  return request<{ status: string; version?: string; database_connected?: boolean }>("/health");
}
