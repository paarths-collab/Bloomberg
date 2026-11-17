"""
Dataset versions for experiment trials.

A dataset version is an immutable snapshot of OHLCV bars identified by the sha256 of its canonical
rows and interpretation/provenance metadata. Two sources exist: deterministic synthetic fixtures generated in code (no data files) and
provider snapshots fetched through the backtest service's own fetch helpers.

Everything here is pure except `fetch_provider_dataset`, which calls the provider through
`backend.backtest.service._fetch_candles_with_fallback` (looked up at call time so tests can patch it).

Known provenance gap: that helper silently retries the alternate market (us <-> india) when the first lookup
returns no data, and does not say which market produced the bars. The snapshot therefore records the market
that was *requested* (in the trial's dataset_request), not necessarily the one that answered.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backend.backtest import service as bt

logger = logging.getLogger(__name__)

MAX_BARS = 5000
COLUMNS = ["date", "open", "high", "low", "close", "volume"]
IDENTITY_FIELDS = ("source", "symbol", "interval", "timezone", "adjustment", "rights_note")
SYMBOL_RE = re.compile(r"^[A-Za-z0-9.\-^=]{1,20}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

SYNTHETIC_RIGHTS = "synthetic data, free to redistribute"
PROVIDER_RIGHTS = "provider data; redistribution rights not established"


class DatasetError(Exception):
    """Dataset resolution failed. `code` becomes the failed trial's error_code, `message` is client-safe."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Canonical JSON / hashing / JSON safety
# ---------------------------------------------------------------------------

def json_safe(obj: Any) -> Any:
    """Recursively convert numpy scalars to Python, NaN/inf to None, and unknown objects to str."""
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, np.generic):
        return json_safe(obj.item())
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return json_safe(obj.tolist())
    return str(obj)


def canonical_json(obj: Any) -> str:
    """Deterministic JSON text: sorted keys, no whitespace, floats via repr, NaN/inf rejected."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number + 0.0  # turns -0.0 into 0.0 so the serialised form is unique


def canonicalize_rows(candles: List[Dict[str, Any]]) -> List[List[Any]]:
    """Candle dicts -> [[date, open, high, low, close, volume], ...] in input order."""
    rows: List[List[Any]] = []
    for c in candles:
        volume = _num(c.get("volume"))
        rows.append([
            str(c.get("date")),
            _num(c.get("open")), _num(c.get("high")), _num(c.get("low")), _num(c.get("close")),
            None if volume is None else int(volume),
        ])
    return rows


def rows_hash(rows: List[List[Any]]) -> str:
    return sha256_hex(canonical_json({"schema": COLUMNS, "rows": rows}))


def snapshot_hash(rows, **metadata):
    """Version 2 identity includes provenance and interpretation, not just bars."""
    return sha256_hex(canonical_json({"version": 2, "schema": COLUMNS, "rows": rows,
                                     "metadata": metadata}))


def rows_to_df(rows: List[List[Any]]) -> pd.DataFrame:
    """Stored rows -> the frame the engine runs on (same path for first run and reproduction)."""
    candles = [dict(zip(COLUMNS, r)) for r in rows]
    return bt.prepare_candles_df(candles)


# ---------------------------------------------------------------------------
# Dataset value object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Dataset:
    content_hash: str
    rows: List[List[Any]]
    source: str
    symbol: Optional[str]
    interval: str
    timezone: str
    adjustment: str
    rights_note: str

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def missing_rows(self) -> int:
        return sum(1 for r in self.rows if any(v is None for v in r[1:5]))

    @property
    def start(self) -> Optional[str]:
        return self.rows[0][0] if self.rows else None

    @property
    def end(self) -> Optional[str]:
        return self.rows[-1][0] if self.rows else None

    def meta(self) -> Dict[str, Any]:
        return {
            "content_hash": self.content_hash, "source": self.source, "symbol": self.symbol,
            "interval": self.interval, "timezone": self.timezone, "start": self.start, "end": self.end,
            "row_count": self.row_count, "missing_rows": self.missing_rows,
            "adjustment": self.adjustment, "rights_note": self.rights_note,
        }


def build_dataset(
    candles: List[Dict[str, Any]], *, source: str, symbol: Optional[str], interval: str,
    timezone: str, adjustment: str, rights_note: str,
) -> Dataset:
    rows = canonicalize_rows(candles)
    interval = "1h" if interval == "60m" else interval
    metadata = dict(source=source, symbol=symbol, interval=interval, timezone=timezone,
                    adjustment=adjustment, rights_note=rights_note)
    return Dataset(snapshot_hash(rows, **metadata), rows, **metadata)


# ---------------------------------------------------------------------------
# Synthetic fixtures (deterministic, generated in code)
# ---------------------------------------------------------------------------

def _candle(date: str, o: float, h: float, l: float, c: float, v: int) -> Dict[str, Any]:
    return {"date": date, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _gen_gbm_504() -> List[Dict[str, Any]]:
    """Seeded geometric Brownian motion with overnight gap opens. Uses random.Random (Mersenne Twister,
    a documented stable stream); prices are rounded to 4 decimals at every step."""
    rng = random.Random(20220103)
    start_price, mu, sigma, gap_sigma, wick_sigma = 100.0, 0.08, 0.25, 0.006, 0.004
    dt = 1.0 / 252.0
    dates = pd.bdate_range("2022-01-03", periods=504)
    prev_close = start_price
    candles = []
    for i, d in enumerate(dates):
        # every price is rounded to 4 decimals as it is produced (including the carried close), so tiny
        # libm differences between platforms cannot accumulate into a different hash
        open_ = start_price if i == 0 else round(prev_close * (1.0 + rng.gauss(0.0, gap_sigma)), 4)
        close = round(prev_close * math.exp((mu - 0.5 * sigma ** 2) * dt + sigma * math.sqrt(dt) * rng.gauss(0.0, 1.0)), 4)
        high = round(max(open_, close) * (1.0 + abs(rng.gauss(0.0, wick_sigma))), 4)
        low = round(min(open_, close) * (1.0 - abs(rng.gauss(0.0, wick_sigma))), 4)
        volume = int(1_000_000 * (0.7 + 0.6 * rng.random()))
        candles.append(_candle(d.strftime("%Y-%m-%d"), open_, high, low, close, volume))
        prev_close = close
    return candles


def _gen_flat_60() -> List[Dict[str, Any]]:
    dates = pd.bdate_range("2022-01-03", periods=60)
    return [_candle(d.strftime("%Y-%m-%d"), 100.0, 100.0, 100.0, 100.0, 1_000_000) for d in dates]


FIXTURES: Dict[str, Dict[str, Any]] = {
    "synthetic-gbm-504": {
        "description": "504 business days from 2022-01-03: seeded GBM (mu 8%, sigma 25%, seed 20220103) "
                       "with overnight gap opens.",
        "symbol": "SYN-GBM",
        "version": 1,  # bump deliberately if a generator or its parameters ever change (hash changes too)
        "generator": _gen_gbm_504,
    },
    "synthetic-flat-60": {
        "description": "60 business days of constant price 100: a strategy completes with a zero-return run.",
        "symbol": "SYN-FLAT",
        "version": 1,
        "generator": _gen_flat_60,
    },
}


@lru_cache(maxsize=None)
def get_fixture(name: str) -> Dataset:
    """Build (once per process) the named fixture. Raises KeyError for an unknown name."""
    spec = FIXTURES[name]
    return build_dataset(
        spec["generator"](), source=f"synthetic:{name}", symbol=spec["symbol"], interval="1d",
        timezone="UTC", adjustment="synthetic", rights_note=SYNTHETIC_RIGHTS,
    )


def fixture_by_hash(content_hash: str) -> Optional[Dataset]:
    for name in FIXTURES:
        ds = get_fixture(name)
        if content_hash in (ds.content_hash, rows_hash(ds.rows)):
            return ds
    return None


def list_fixtures() -> List[Dict[str, Any]]:
    return [
        {"name": name, "description": FIXTURES[name]["description"], "version": FIXTURES[name]["version"],
         "rows": get_fixture(name).row_count, "content_hash": get_fixture(name).content_hash}
        for name in FIXTURES
    ]


# ---------------------------------------------------------------------------
# Provider snapshots
# ---------------------------------------------------------------------------

def validate_provider_request(
    symbol: str, interval: Optional[str], range_: Optional[str], start: Optional[str],
    end: Optional[str], market: Optional[str],
) -> Dict[str, Any]:
    """Request-level validation (-> 422). Returns the normalised provider request. Raises ValueError."""
    if not isinstance(symbol, str) or not SYMBOL_RE.match(symbol.strip()):
        raise ValueError("dataset.symbol must be 1-20 characters of A-Z, 0-9, '.', '-', '^' or '='")
    interval = str(interval or "1d").strip().lower()
    bt.get_periods_per_year(interval)  # ValueError for unsupported intervals
    market = str(market or "us").strip().lower()
    if market not in ("us", "india"):
        raise ValueError("dataset.market must be 'us' or 'india'")
    if (start is None) != (end is None):
        raise ValueError("dataset.start and dataset.end must be given together")
    out = {"symbol": symbol.strip().upper(), "interval": interval, "market": market,
           "range": None, "start": None, "end": None}
    if start is not None:
        try:
            s, e = pd.Timestamp(start), pd.Timestamp(end)
        except (ValueError, TypeError):
            raise ValueError("dataset.start and dataset.end must be valid dates")
        if not s < e:
            raise ValueError("dataset.start must be before dataset.end")
        out["start"], out["end"] = str(start), str(end)
    else:
        out["range"] = bt.validate_range(range_ if range_ is not None else "1y")
    return out


def fetch_provider_dataset(req: Dict[str, Any]) -> Dataset:
    """Fetch + snapshot provider bars. Raises DatasetError(data_unavailable | no_data | invalid_dataset)."""
    try:
        candles = bt._fetch_candles_with_fallback(
            symbol=req["symbol"], interval=req["interval"], range_period=req["range"] or "1y",
            start_date=req["start"], end_date=req["end"], market=req["market"],
        )
    except Exception:  # MarketDataError and anything unexpected: details are logged, never returned
        logger.exception("Provider fetch failed for %s", req.get("symbol"))
        raise DatasetError("data_unavailable", "The market data provider could not be reached or failed.")
    if not candles:
        raise DatasetError("no_data", "The provider returned no data for the requested symbol and period.")
    if len(candles) > MAX_BARS:
        raise DatasetError("invalid_dataset", f"The dataset has more than {MAX_BARS} bars.")
    dates = [str(c.get("date")) for c in candles]
    # the bar timestamp formats ("%Y-%m-%d" / "%Y-%m-%d %H:%M") sort lexicographically
    if any(a >= b for a, b in zip(dates, dates[1:])):
        raise DatasetError("invalid_dataset", "The provider bars are not sorted by date with unique timestamps.")
    ds = build_dataset(
        candles, source="provider:yfinance", symbol=req["symbol"], interval=req["interval"],
        timezone="provider default (not recorded)", adjustment="provider default", rights_note=PROVIDER_RIGHTS,
    )
    if rows_to_df(ds.rows).empty:
        raise DatasetError("invalid_dataset", "The dataset has no bars with a usable close price.")
    return ds
