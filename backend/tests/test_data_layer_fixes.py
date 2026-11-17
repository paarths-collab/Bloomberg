"""
Bounded caches, news outage fallback, candle NaN handling, cache copy semantics, and
/api/news/latest limit bounds. All offline: the yfinance Ticker and the news HTTP layer are stubbed.
"""
import types

import numpy as np
import pandas as pd
import pytest

from backend.common.ttl_cache import TTLCache
from backend.core import safe_yfinance
from backend.news import live_service as ls
from backend.news.live_service import LiveNewsService, LiveNewsSource
from backend.services.technical_analysis import technical_service


# --------------------------------------------------------------------------- helpers

def _frame(rows=300, nan_rows=(), nan_volume_rows=()):
    index = pd.date_range("2023-01-02", periods=rows, freq="D")
    base = 100 + np.sin(np.arange(rows) / 7.0) * 5 + np.arange(rows) * 0.05
    df = pd.DataFrame({
        "Open": base, "High": base + 1.0, "Low": base - 1.0, "Close": base + 0.3,
        "Volume": np.full(rows, 1_000_000.0),
    }, index=index)
    for i in nan_rows:
        df.iloc[i, df.columns.get_loc("Open")] = np.nan
        df.iloc[i, df.columns.get_loc("Close")] = np.nan
    for i in nan_volume_rows:
        df.iloc[i, df.columns.get_loc("Volume")] = np.nan
    return df


@pytest.fixture
def fake_yf(monkeypatch):
    """Replace yfinance.Ticker with a stub serving `fake_yf.frame`; start each test with a clean cache."""
    state = types.SimpleNamespace(frame=_frame(), calls=0)

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            state.calls += 1
            return state.frame.copy()

        @property
        def info(self):
            return {"shortName": "X", "nested": {"a": [1, 2]}}

    monkeypatch.setattr(safe_yfinance.yf, "Ticker", FakeTicker)
    safe_yfinance.clear_cache()
    technical_service._indicator_cache.clear()
    yield state
    safe_yfinance.clear_cache()
    technical_service._indicator_cache.clear()


# --------------------------------------------------------------------------- TTLCache

def test_ttlcache_is_bounded_and_evicts_least_recently_used():
    cache = TTLCache(maxsize=3, ttl=100, clock=lambda: 0.0)
    for key in "abc":
        cache.set(key, key.upper())
    assert cache.get("a") == "A"  # touch a: b is now least recently used
    cache.set("d", "D")
    assert len(cache) == 3
    assert cache.get("b") is None and cache.get("a") == "A" and cache.get("d") == "D"


def test_ttlcache_expires_but_keeps_stale_until_evicted():
    clock = {"t": 0.0}
    cache = TTLCache(maxsize=2, ttl=10, clock=lambda: clock["t"])
    cache.set("k", "v")
    assert cache.get("k") == "v"
    clock["t"] = 10.0
    assert cache.get("k") is None
    assert cache.get_stale("k") == "v"
    cache.set("fresh1", 1)
    cache.set("fresh2", 2)  # over capacity: the expired entry goes before live ones
    assert cache.get_stale("k") is None
    assert cache.get("fresh1") == 1 and cache.get("fresh2") == 2


# --------------------------------------------------------------------------- (4) bounded caches

def test_safe_yfinance_cache_is_bounded_for_user_supplied_ranges(fake_yf):
    limit = safe_yfinance._cache.maxsize
    for i in range(limit + 150):
        res = safe_yfinance.safe_fetch_history("AAPL", start=f"2020-01-{i % 28 + 1:02d}", end=f"x{i}")
        assert res["status"] == "ok"
    assert len(safe_yfinance._cache) <= limit
    assert limit <= 1000


def test_technical_indicator_cache_is_bounded_and_market_is_normalised(fake_yf, monkeypatch):
    from backend.services.market_data import market_service

    monkeypatch.setattr(market_service, "get_history", lambda *a, **k: _frame())
    cache = technical_service._indicator_cache
    for i in range(cache.maxsize + 100):
        technical_service.calculate_indicators(f"T{i}", "6mo", "1d", "us")
    assert len(cache) <= cache.maxsize

    cache.clear()
    technical_service.calculate_indicators("AAPL", "6mo", "1d", "US")
    technical_service.calculate_indicators("AAPL", "6mo", "1d", "weird-market-1")
    technical_service.calculate_indicators("AAPL", "6mo", "1d", "weird-market-2")
    assert len(cache) == 1  # every non-India market value is the same US key
    technical_service.calculate_indicators("AAPL", "6mo", "1d", "India")
    assert len(cache) == 2


def _service(sources=1):
    svc = LiveNewsService()
    svc._sources = [
        LiveNewsSource(source_id=f"s{i}", name=f"Source {i}", mode="rss", url=f"https://example.com/{i}.xml",
                       seed_urls=[], max_pages=1, shard=0, is_live=True, trust_tier=1)
        for i in range(sources)
    ]
    return svc


def _rss(*titles):
    items = "".join(f"<item><title>{t}</title><link>https://example.com/{abs(hash(t))}</link></item>"
                    for t in titles)
    return f"<rss><channel>{items}</channel></rss>"


def test_live_news_query_and_summary_caches_are_bounded(monkeypatch):
    svc = _service()
    svc._cached_set(svc._BASE_CACHE_KEY, [{"title": "Alpha market news headline", "url": "https://e/1", "source_id": "s0"}])
    for i in range(svc._CACHE_MAX_ENTRIES + 300):
        svc.get_news(query=f"query number {i}", limit=5)
    assert len(svc._cache) <= svc._CACHE_MAX_ENTRIES
    # a hostile, huge query text does not become a huge key
    svc.get_news(query="q" * 100_000, limit=5)
    assert all(len(k) < 400 for k in svc._cache._data)

    monkeypatch.setattr(ls, "validate_article_url", lambda u: types.SimpleNamespace(netloc="e.com"))
    monkeypatch.setattr(ls, "fetch_public_html", lambda u: "<html><title>t</title><p>" + "word " * 30 + ".</p></html>")
    for i in range(svc._SUMMARY_CACHE_MAX_ENTRIES + 100):
        svc.summarize_article(f"https://e.com/a{i}")
    assert len(svc._summary_cache) <= svc._SUMMARY_CACHE_MAX_ENTRIES


# --------------------------------------------------------------------------- (5) news outage

def test_news_outage_after_expiry_serves_stale_and_recovery_is_fresh(monkeypatch):
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(ls, "time", types.SimpleNamespace(time=lambda: clock["t"]))
    svc = _service()
    svc._cache = TTLCache(maxsize=256, ttl=svc._CACHE_TTL_SECONDS, clock=lambda: clock["t"])
    feed = {"xml": _rss("First story about stocks rallying today", "Second story about oil prices moving")}
    svc._http_get = lambda client, url: feed["xml"]

    fresh = svc.get_news(query="stock market news", limit=10)
    assert [a["title"] for a in fresh["articles"]] == [
        "First story about stocks rallying today", "Second story about oil prices moving"]
    assert fresh["cached"] is False and fresh["stale"] is False

    clock["t"] += svc._CACHE_TTL_SECONDS + 1  # everything expired
    feed["xml"] = None  # upstream outage
    stale = svc.get_news(query="stock market news", limit=10)
    assert len(stale["articles"]) == 2
    assert stale["cached"] is True and stale["stale"] is True
    # the good snapshot was NOT replaced by an empty one, and the outage result was not cached
    assert len(svc._cached_get(svc._BASE_CACHE_KEY, allow_stale=True)) == 2
    assert svc._cached_get("stock market news|10") is None

    # a query never seen before is served from the stale base snapshot
    other = svc.get_news(query="oil prices", limit=10)
    assert other["stale"] is True and other["articles"][0]["title"].startswith("Second story")

    # still down on the next call: still stale, not empty
    assert len(svc.get_news(query="stock market news", limit=10)["articles"]) == 2

    clock["t"] += 5
    feed["xml"] = _rss("Brand new recovery headline for the markets")
    recovered = svc.get_news(query="stock market news", limit=10)
    assert [a["title"] for a in recovered["articles"]] == ["Brand new recovery headline for the markets"]
    assert recovered["stale"] is False and recovered["cached"] is False
    # and the recovery is what is now cached
    again = svc.get_news(query="stock market news", limit=10)
    assert again["cached"] is True and again["articles"][0]["title"].startswith("Brand new")


def test_news_outage_with_nothing_cached_is_empty_but_not_cached(monkeypatch):
    svc = _service()
    feed = {"xml": None}
    svc._http_get = lambda client, url: feed["xml"]
    down = svc.get_news(query="stock market news", limit=5)
    assert down["articles"] == [] and down["stale"] is False
    assert svc._cached_get("stock market news|5", allow_stale=True) is None
    assert svc._cached_get(svc._BASE_CACHE_KEY, allow_stale=True) is None
    feed["xml"] = _rss("Service is back with a fresh headline today")
    assert len(svc.get_news(query="stock market news", limit=5)["articles"]) == 1  # not poisoned


def test_cached_only_news_serves_stale_after_expiry(monkeypatch):
    clock = {"t": 5_000.0}
    monkeypatch.setattr(ls, "time", types.SimpleNamespace(time=lambda: clock["t"]))
    svc = _service()
    svc._cache = TTLCache(maxsize=256, ttl=svc._CACHE_TTL_SECONDS, clock=lambda: clock["t"])
    svc._http_get = lambda client, url: _rss("Only story available right now for markets")
    svc.get_news(query="stock market news", limit=5)
    clock["t"] += 10_000
    out = svc.get_cached_news(query="stock market news", limit=5)
    assert out["stale"] is True and len(out["articles"]) == 1


# --------------------------------------------------------------------------- (6) candles

async def test_candles_with_nan_ohlc_are_dropped_not_500(client, fake_yf):
    fake_yf.frame = _frame(rows=40, nan_rows=(5, 6), nan_volume_rows=(10,))
    r = await client.get("/api/markets/candles/NANCANDLES?range=1mo&interval=1d")
    assert r.status_code == 200
    assert "NaN" not in r.text and "Infinity" not in r.text
    data = r.json()["data"]
    assert len(data) == 38  # the two rows without a real price are gone
    assert all(isinstance(c["open"], float) and isinstance(c["close"], float) for c in data)
    # NaN volume is reported as null (never invented as 0) and the candle with real OHLC is kept
    assert data[10 - 2]["volume"] is None
    assert sum(c["volume"] is None for c in data) == 1
    assert all(c["volume"] == 1_000_000 for c in data if c["volume"] is not None)
    assert '"volume":null' in r.text.replace(" ", "")


async def test_candles_all_nan_is_404_no_data(client, fake_yf):
    fake_yf.frame = _frame(rows=5, nan_rows=range(5))
    r = await client.get("/api/markets/candles/ALLNAN?range=1mo&interval=1d")
    assert r.status_code == 404


def test_safe_fetch_candles_neutralises_nan(fake_yf):
    fake_yf.frame = _frame(rows=12, nan_rows=(0,), nan_volume_rows=(3,))
    candles = safe_yfinance.safe_fetch_candles("NANUNIT", interval="1d", period="1mo")
    assert len(candles) == 11
    assert all(np.isfinite([c["open"], c["high"], c["low"], c["close"]]).all() for c in candles)
    assert [c["volume"] for c in candles].count(None) == 1
    assert candles[2]["volume"] is None  # original row 3, after row 0 was dropped


def test_safe_fetch_candles_missing_volume_column_is_null(fake_yf):
    fake_yf.frame = _frame(rows=12).drop(columns=["Volume"])
    candles = safe_yfinance.safe_fetch_candles("NOVOLCOL", interval="1d", period="1mo")
    assert len(candles) == 12 and all(c["volume"] is None for c in candles)


@pytest.mark.parametrize("query", [
    "range=bogus&interval=1d", "range=1y&interval=2h", "range=1mo;drop&interval=1d",
    "range=99y&interval=99m", "range=&interval=1d",
])
async def test_invalid_range_or_interval_is_400_not_404(client, fake_yf, query):
    for path in ("candles", "indicators"):
        r = await client.get(f"/api/markets/{path}/AAPL?{query}")
        assert r.status_code == 400, (path, query, r.status_code)
    assert fake_yf.calls == 0  # rejected before any provider call


async def test_valid_range_and_interval_still_work(client, fake_yf):
    r = await client.get("/api/markets/candles/AAPL?range=6mo&interval=1d")
    assert r.status_code == 200 and r.json()["data"]


# --------------------------------------------------------------------------- (7) copy semantics

async def test_indicators_do_not_mutate_the_cached_history(client, fake_yf):
    safe_yfinance.safe_fetch_history("CPTEST", period="1y", interval="1d")  # warm the shared cache
    key = safe_yfinance._cache_key("CPTEST", "1y", "1d")
    columns_before = list(safe_yfinance._cache.get(key)["data"].columns)
    values_before = safe_yfinance._cache.get(key)["data"].copy()

    r = await client.get("/api/markets/indicators/CPTEST?range=6mo&interval=1d")
    assert r.status_code == 200
    assert r.json()["indicators"]["rsi"]

    cached_df = safe_yfinance._cache.get(key)["data"]
    assert list(cached_df.columns) == columns_before
    pd.testing.assert_frame_equal(cached_df, values_before)


def test_safe_fetch_history_returns_independent_copies(fake_yf):
    first = safe_yfinance.safe_fetch_history("COPYTEST", period="1y")
    first["data"]["injected"] = 1
    first["data"].iloc[0, 0] = -999.0
    second = safe_yfinance.safe_fetch_history("COPYTEST", period="1y")  # cache hit
    assert fake_yf.calls == 1
    assert "injected" not in second["data"].columns
    assert second["data"].iloc[0, 0] != -999.0
    second["data"]["x"] = 2
    third = safe_yfinance.safe_fetch_history("COPYTEST", period="1y")
    assert "x" not in third["data"].columns


def test_safe_fetch_info_returns_independent_copies(fake_yf):
    a = safe_yfinance.safe_fetch_info("INFOCOPY")
    a["data"]["nested"]["a"].append(99)
    a["data"]["shortName"] = "mutated"
    b = safe_yfinance.safe_fetch_info("INFOCOPY")
    assert b["data"] == {"shortName": "X", "nested": {"a": [1, 2]}}


def test_calculate_indicators_in_safe_yfinance_does_not_touch_cache(fake_yf):
    safe_yfinance.calculate_indicators("CALCCOPY")
    cached = safe_yfinance._cache.get(safe_yfinance._cache_key("CALCCOPY", "1y", "1d"))["data"]
    assert "rsi" not in cached.columns


def test_technical_service_copies_even_a_shared_frame(monkeypatch):
    from backend.services.market_data import market_service

    shared = _frame()
    columns = list(shared.columns)
    monkeypatch.setattr(market_service, "get_history", lambda *a, **k: shared)
    technical_service._indicator_cache.clear()
    assert technical_service.calculate_indicators("SHARED", "6mo", "1d", "us")["rsi"]
    assert list(shared.columns) == columns
    # callers cannot corrupt the cached indicator payload either
    first = technical_service.calculate_indicators("SHARED", "6mo", "1d", "us")
    first["rsi"].clear()
    assert technical_service.calculate_indicators("SHARED", "6mo", "1d", "us")["rsi"]
    technical_service._indicator_cache.clear()


# --------------------------------------------------------------------------- (8) /api/news/latest

@pytest.mark.parametrize("limit", ["0", "-1", "-5", "51", "100000", "abc"])
async def test_news_latest_rejects_out_of_range_limit(client, limit):
    r = await client.get(f"/api/news/latest?limit={limit}")
    assert r.status_code == 422


@pytest.mark.parametrize("limit", [1, 10, 50])
async def test_news_latest_accepts_bounded_limit_and_slices(client, monkeypatch, limit):
    from backend.news import main as news_main

    monkeypatch.setattr(news_main._NEWS_SERVICE, "search_news",
                        lambda query: [{"title": f"n{i}"} for i in range(80)])
    r = await client.get(f"/api/news/latest?limit={limit}")
    assert r.status_code == 200
    assert len(r.json()) == limit
    assert r.json()[0] == {"title": "n0"}
