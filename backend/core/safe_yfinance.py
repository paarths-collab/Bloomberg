"""
safe_yfinance.py — Centralized, fail-safe Yahoo Finance wrapper.

All backend modules should import from here instead of calling
yf.Ticker(...) directly. This prevents crashes from:
  - Empty DataFrames (delisted / no data)
  - Rate limit exceptions
  - yfinance internal errors

Usage:
    from backend.core.safe_yfinance import safe_fetch_history, safe_fetch_info

    res = safe_fetch_history("AAPL")
    if res["status"] != "ok":
        return None  # or whatever fallback you need
    df = res["data"]
    price = float(df["Close"].iloc[-1])
"""
import copy
import math
from datetime import datetime, timezone
import time
import logging
import pandas as pd
import numpy as np
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List, Callable

from backend.common.ttl_cache import TTLCache

# ─── Suppress YFinance Warnings ──────────────────────────────────────────────
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)

# ─── In-memory cache ────────────────────────────────────────────────────────
# Keys embed user-controlled values (symbol, range, start/end), so the cache is bounded (LRU + TTL).
_CACHE_TTL_SECONDS = 300  # 5 minutes
_CACHE_MAX_ENTRIES = 512
_cache = TTLCache(maxsize=_CACHE_MAX_ENTRIES, ttl=_CACHE_TTL_SECONDS)

# Values yfinance accepts; routes use these to reject bad input with 400 before it reaches the provider.
VALID_PERIODS = frozenset({"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"})
VALID_INTERVALS = frozenset(
    {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"}
)

# ─── Rate-limit delay between batch requests ─────────────────────────────────
_RATE_LIMIT_DELAY = 0.15  # seconds


def _cache_key(symbol: str, period: str, interval: str = "") -> str:
    return f"{symbol.upper()}:{period}:{interval}"


def _copy_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Result dict safe to hand out: the cached DataFrame / info dict is never shared by reference."""
    out = dict(entry)
    data = out.get("data")
    if isinstance(data, pd.DataFrame):
        out["data"] = data.copy()
    elif isinstance(data, dict):
        out["data"] = copy.deepcopy(data)
    if isinstance(out.get("quote_data"), dict):
        out["quote_data"] = dict(out["quote_data"])
    return out


def safe_fetch_history(
    symbol: str,
    period: str = "7d",
    interval: str = "1d",
    start: Optional[str] = None,
    end: Optional[str] = None,
    rate_limit: bool = False,
) -> Dict[str, Any]:
    """
    Safely fetch ticker history with caching.
    Supports fixed periods OR specific date ranges.
    """
    # Use a specific cache key for date ranges
    if start or end:
        key = f"RANGE:{symbol.upper()}:{start}:{end}:{interval}"
    else:
        key = _cache_key(symbol, period, interval)
        
    cached = _cache.get(key)
    if cached is not None:
        return _copy_entry(cached)

    if rate_limit:
        time.sleep(_RATE_LIMIT_DELAY)

    try:
        ticker = yf.Ticker(symbol)
        
        if start or end:
            df = ticker.history(start=start, end=end, interval=interval)
        else:
            df = ticker.history(period=period, interval=interval)

        if df is None or df.empty:
            result = {"status": "no_data", "data": None}
        else:
            result = {"status": "ok", "data": df, "cached_at": time.time()}
            _cache.set(key, result)
            result = _copy_entry(result)  # the caller must not share the cached frame

        return result

    except Exception:
        logger.exception("[safe_yfinance] fetch_history(%s) failed", symbol)
        return {"status": "error", "error": "Market data request failed", "data": None}


def safe_fetch_info(symbol: str) -> Dict[str, Any]:
    """
    Safely fetch ticker info metadata with caching.
    """
    symbol = symbol.upper().strip()
    key = f"INFO:{symbol}"
    
    cached = _cache.get(key)
    if cached is not None:
        return _copy_entry(cached)

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        if not info:
            return {"status": "no_data", "data": {}}

        result = {"status": "ok", "data": info, "cached_at": time.time()}
        _cache.set(key, result)
        return _copy_entry(result)

    except Exception:
        logger.exception("[safe_yfinance] fetch_info(%s) failed", symbol)
        return {"status": "error", "error": "Market data request failed", "data": {}}


def _positive_finite(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _epoch_to_iso(value: Any) -> Optional[str]:
    """ISO-8601 UTC for an epoch-seconds value (e.g. yfinance regularMarketTime), else None."""
    try:
        seconds = float(value)
        if not math.isfinite(seconds) or seconds <= 0:
            return None
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def safe_get_price_quote(symbol: str) -> Dict[str, Any]:
    """
    Current price together with where it came from.

    Returns ``{"price": float | None, "source": str | None, "as_of": str | None}``:
      * ``source == "live"``           currentPrice / regularMarketPrice from the provider's quote
                                       (``as_of`` = regularMarketTime when the provider gives it)
      * ``source == "previous_close"`` the provider's previousClose (no quote time; ``as_of`` None)
      * ``source == "last_close_5d"``  last close of the 5-day history (``as_of`` = that bar's date)
      * ``price is None`` (source None) when nothing usable was found.
    """
    info_res = safe_fetch_info(symbol)
    if info_res["status"] == "ok":
        info = info_res["data"] or {}
        for field, source in (
            ("currentPrice", "live"),
            ("regularMarketPrice", "live"),
            ("previousClose", "previous_close"),
        ):
            price = _positive_finite(info.get(field))
            if price is not None:
                as_of = _epoch_to_iso(info.get("regularMarketTime")) if source == "live" else None
                return {"price": price, "source": source, "as_of": as_of}

    hist_res = safe_fetch_history(symbol, period="5d")
    if hist_res["status"] == "ok":
        df = hist_res["data"]
        if df is not None and not df.empty:
            price = _positive_finite(df["Close"].iloc[-1])
            if price is not None:
                last = df.index[-1]
                as_of = last.isoformat() if hasattr(last, "isoformat") else str(last)
                return {"price": price, "source": "last_close_5d", "as_of": as_of}

    return {"price": None, "source": None, "as_of": None}


def safe_get_price(symbol: str) -> Optional[float]:
    """
    Safely get the current price for a symbol (bare number; see safe_get_price_quote for the source).
    """
    return safe_get_price_quote(symbol)["price"]


def candles_from_frame(df: pd.DataFrame, ndigits: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    OHLCV DataFrame -> candle dicts, JSON-safe and without invented values.

    A row whose open/high/low/close is missing or non-finite is dropped. Volume that is missing or
    non-finite is reported as None (JSON null), never as 0. ``ndigits`` rounds prices when given.
    """
    def num(row, name):
        try:
            raw = row.get(name)
            return float(raw) if raw is not None else float("nan")
        except (TypeError, ValueError):
            return float("nan")

    candles: List[Dict[str, Any]] = []
    for idx, row in df.iterrows():
        o, h, l, c = (num(row, n) for n in ("Open", "High", "Low", "Close"))
        if not all(math.isfinite(v) for v in (o, h, l, c)):
            continue
        vol = num(row, "Volume")
        if ndigits is not None:
            o, h, l, c = (round(v, ndigits) for v in (o, h, l, c))
        candles.append({
            "date": idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": int(vol) if math.isfinite(vol) else None,
        })
    return candles


def safe_fetch_candles(
    symbol: str,
    interval: str = "1d",
    period: str = "1mo",
    market: str = "us"
) -> List[Dict[str, Any]]:
    """
    Consolidated, safe candle fetching for all modules.
    Ensures market suffixes are handled and errors are caught.
    """
    # 1. Normalize and validate
    symbol = symbol.upper().strip()
    market = market.lower().strip()
    
    if market == "india" and not (symbol.endswith(".NS") or symbol.endswith(".BO")):
        symbol = f"{symbol}.NS"

    # 2. Fetch using history wrapper
    res = safe_fetch_history(symbol, period=period, interval=interval)
    if res["status"] != "ok" or res["data"] is None:
        return []

    try:
        return candles_from_frame(res["data"], ndigits=2)
    except Exception as e:
        logger.error(f"[safe_yfinance] Candle processing failed for {symbol}: {e}")
        return []


def calculate_indicators(symbol: str, range_period: str = "6mo", interval: str = "1d", market: str = "us") -> Dict[str, Any]:
    """
    Centralized technical indicator calculation.
    """
    symbol = symbol.upper().strip()
    if market.lower() == "india" and not (symbol.endswith(".NS") or symbol.endswith(".BO")):
        symbol = f"{symbol}.NS"

    # Fetch enough data for indicators (warmup)
    res = safe_fetch_history(symbol, period="1y", interval=interval)
    if res["status"] != "ok" or res["data"] is None:
        return {}

    df = res["data"]
    if len(df) < 20:
        return {}

    try:
        # RSI (14)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # EMAs
        df['ema_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['ema_50'] = df['Close'].ewm(span=50, adjust=False).mean()
        df['ema_200'] = df['Close'].ewm(span=200, adjust=False).mean()
        
        # MACD
        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['macd_line'] = ema12 - ema26
        df['macd_signal'] = df['macd_line'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd_line'] - df['macd_signal']

        # Replace NaNs for JSON
        df = df.replace({np.nan: None})
        
        # Trim to requested period if needed (simple slice for now)
        # In a real app we'd filter by index date
        
        return {
            "dates": df.index.strftime('%Y-%m-%d').tolist(),
            "rsi": df['rsi'].tolist(),
            "macd": {
                "line": df['macd_line'].tolist(),
                "signal": df['macd_signal'].tolist(),
                "histogram": df['macd_hist'].tolist()
            },
            "ema": {
                "20": df['ema_20'].tolist(),
                "50": df['ema_50'].tolist(),
                "200": df['ema_200'].tolist()
            }
        }
    except Exception as e:
        logger.error(f"[safe_yfinance] Indicators failed for {symbol}: {e}")
        return {}


def safe_fetch_multiple_quotes(
    symbols: List[str], 
    max_workers: int = 15,
    validator: Optional[Callable[[str], bool]] = None
) -> Dict[str, Dict[str, Any]]:
    """
    [OPTIMIZED] Fetch quotes for multiple symbols in parallel batches.
    """
    results = {}
    if not symbols:
        return results
        
    # Validation Layer
    if validator:
        valid_symbols = [s for s in symbols if validator(s)]
        if not valid_symbols:
            return {s: {"symbol": s, "error": "Filtered by validator"} for s in symbols}
        symbols = valid_symbols

    now = time.time()
    symbols_to_fetch = []
    
    for symbol in symbols:
        key = _cache_key(symbol, "7d")
        cached = _cache.get(key)
        if cached is not None and "quote_data" in cached:
            results[symbol] = dict(cached.get("quote_data", {}))
        else:
            symbols_to_fetch.append(symbol)
            
    if not symbols_to_fetch:
        return results

    # Smaller batches reduce the chance that a single slow ticker stalls the whole snapshot.
    batch_size = 5
    batches = [symbols_to_fetch[i:i + batch_size] for i in range(0, len(symbols_to_fetch), batch_size)]
    
    def fetch_batch(batch_symbols):
        try:
            data = yf.download(
                tickers=batch_symbols, 
                period="5d", 
                interval="1d", 
                group_by='ticker', 
                auto_adjust=True, 
                progress=False,
                timeout=6
            )
            
            batch_results = {}
            for symbol in batch_symbols:
                ticker_key = symbol.upper()
                try:
                    df = data
                    if isinstance(df.columns, pd.MultiIndex):
                        # yfinance can retain a ticker level even for a one-symbol batch.
                        level = next((i for i in range(df.columns.nlevels) if symbol in df.columns.get_level_values(i)), None)
                        if level is None:
                            raise ValueError("Ticker missing from quote batch")
                        df = df.xs(symbol, axis=1, level=level)
                    df = df.dropna(subset=['Close'])
                    if df.empty:
                        res = {"symbol": ticker_key, "price": None, "change": None, "change_percent": None}
                    else:
                        closes = df['Close'].tolist()
                        price = closes[-1]
                        prev_close = closes[-2] if len(closes) >= 2 else None
                        change = price - prev_close if prev_close is not None else None
                        change_percent = (change / prev_close) * 100 if prev_close else None
                        
                        res = {
                            "symbol": ticker_key,
                            "price": round(float(price), 2),
                            "change": round(float(change), 2) if change is not None else None,
                            "change_percent": round(float(change_percent), 2) if change_percent is not None else None,
                            "timestamp": now
                        }
                    batch_results[symbol] = res
                except Exception:
                    batch_results[symbol] = {"symbol": ticker_key, "price": None, "change": None, "change_percent": None}
            return batch_results
        except Exception:
            logger.exception("[safe_yfinance] batch quote fetch failed")
            return {s: {"symbol": s.upper(), "error": "Market data request failed"} for s in batch_symbols}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_batch = {executor.submit(fetch_batch, b): b for b in batches}
        for future in as_completed(future_to_batch):
            try:
                batch_res = future.result()
                for s, r in batch_res.items():
                    results[s] = r
                    if r.get("price") is not None:
                        cache_key = _cache_key(s, "7d")
                        _cache.set(cache_key, {"status": "ok", "quote_data": dict(r), "cached_at": now})
            except Exception as exc:
                logger.debug("Quote batch future failed: %s", exc)

    return results


def clear_cache():
    _cache.clear()
