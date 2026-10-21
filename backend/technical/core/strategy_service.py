
import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .strategy_adapter import (
    SMACrossoverStrategy,
    RSIMomentumStrategy,
    BreakoutStrategy,
)

# 
# 

STRATEGY_REGISTRY = {
    "sma_crossover": SMACrossoverStrategy,
    "rsi_momentum": RSIMomentumStrategy,
    "breakout": BreakoutStrategy,
}

def get_strategy(name: str, **params):
    """
    Factory function to get a strategy instance.
    """
    if name not in STRATEGY_REGISTRY:
        # Fallback or error? For now, raise error.
        # Check if we have a loose match?
        available = ", ".join(STRATEGY_REGISTRY.keys())
        raise ValueError(f"Strategy '{name}' not found. Available: {available}")
    
    strategy_class = STRATEGY_REGISTRY[name]
    # Filter params to only those accepted by the init? 
    # For now, assume dynamic kwargs are passed safely or we let Python raise TypeError if invalid args
    return strategy_class(**params)

def get_available_strategies():
    """
    Return a list of available strategies with default parameters.
    This helps the frontend build the dropdowns dynamically.
    """
    strategies = []
    for name, cls in STRATEGY_REGISTRY.items():
        # Instantiate with defaults to get parameters
        # valid assumption? Most inits have defaults.
        try:
            instance = cls()
            strategies.append({
                "id": name,
                "name": cls.name,
                "parameters": instance.parameters 
            })
        except Exception:
            # If init fails without args, we might need a workaround.
            # For now, skip or manually define.
            strategies.append({
                "id": name,
                "name": cls.name,
                "parameters": {} # Placeholder
            })
            
    return strategies


# --- Analysis (used by GET/POST /api/technical/analyze) ---

# Canonical period -> accepted aliases. "1m" etc. mean months here (not minutes).
PERIOD_ALIASES = {
    "1m": "1mo",
    "3m": "3mo",
    "6m": "6mo",
    "all": "max",
}
SUPPORTED_PERIODS = ["1mo", "3mo", "6mo", "1y", "2y", "5y", "max"]
SUPPORTED_PERIODS_TEXT = "1mo/1m, 3mo/3m, 6mo/6m, 1y, 2y, 5y, max/all"

# Longer history is fetched than requested so indicators are warmed up.
FETCH_PERIOD = {
    "1mo": "1y",
    "3mo": "1y",
    "6mo": "2y",
    "1y": "2y",
    "2y": "5y",
    "5y": "10y",
    "max": "max",
}

# Output window length, measured back from the last bar (None = whole history).
WINDOW_OFFSET = {
    "1mo": pd.DateOffset(months=1),
    "3mo": pd.DateOffset(months=3),
    "6mo": pd.DateOffset(months=6),
    "1y": pd.DateOffset(years=1),
    "2y": pd.DateOffset(years=2),
    "5y": pd.DateOffset(years=5),
    "max": None,
}

DAILY_OR_LONGER_INTERVALS = {"1d", "5d", "1wk", "1mo", "3mo"}

ASSUMPTIONS = (
    "Signals are computed on bar close from historical data and are research "
    "signals, not trade recommendations."
)

SIGNAL_LABELS = {1: "buy", 0: "neutral", -1: "sell"}


# yfinance history limits for intraday intervals, in days.
INTRADAY_FETCH_LIMITS = {
    "1m": 7,
    "2m": 60,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "90m": 60,
    "60m": 730,
    "1h": 730,
}

# Approximate calendar days in each output window (None = unbounded).
WINDOW_DAYS = {
    "1mo": 31,
    "3mo": 92,
    "6mo": 184,
    "1y": 366,
    "2y": 731,
    "5y": 1827,
    "max": None,
}

# Parameters that are thresholds (finite numbers); all others are positive-integer windows.
THRESHOLD_PARAMS = {"oversold", "overbought"}
MAX_WINDOW = 100_000


class NoDataError(Exception):
    """Raised when the provider data has no usable bars."""


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_params(strategy_instance: Any, raw_params: Dict[str, Any]) -> None:
    """
    Reject semantically bad params that the strategy constructors accept
    (they coerce with int()). Raises ValueError with a client-safe message.
    Call after construction, so unknown keys have already been rejected.
    """
    for key, value in raw_params.items():
        if key in THRESHOLD_PARAMS:
            if not _is_number(value) or not math.isfinite(value):
                raise ValueError(f"'{key}' must be a finite number")
            continue
        if not _is_number(value) or not math.isfinite(value) or float(value) != int(value):
            raise ValueError(f"'{key}' must be a positive integer")
        if not 1 <= int(value) <= MAX_WINDOW:
            raise ValueError(f"'{key}' must be an integer between 1 and {MAX_WINDOW}")

    effective = dict(getattr(strategy_instance, "parameters", {}) or {})
    for key, value in effective.items():
        if key not in THRESHOLD_PARAMS and _is_number(value) and value < 1:
            raise ValueError(f"'{key}' must be a positive integer")
    if "oversold" in effective and "overbought" in effective:
        oversold = raw_params.get("oversold", effective["oversold"])
        overbought = raw_params.get("overbought", effective["overbought"])
        if oversold >= overbought:
            raise ValueError("'oversold' must be less than 'overbought'")


def resolve_fetch_period(period: str, interval: str) -> str:
    """
    Provider period to request for a canonical `period` at `interval`.
    Daily and longer intervals fetch extra history for warm-up. Intraday
    intervals are capped at yfinance's per-interval history limit; a window
    longer than that limit raises ValueError.
    """
    limit = INTRADAY_FETCH_LIMITS.get(interval)
    if limit is None:
        return FETCH_PERIOD[period]
    days = WINDOW_DAYS[period]
    if days is None or days > limit:
        raise ValueError(
            f"Period '{period}' is longer than the {limit}-day history limit for "
            f"interval '{interval}'. Use a shorter period or a longer interval."
        )
    return f"{limit}d"


def normalize_period(period: Optional[str]) -> str:
    """Return the canonical period, or raise ValueError listing supported values."""
    value = (period or "1y").strip().lower()
    value = PERIOD_ALIASES.get(value, value)
    if value not in SUPPORTED_PERIODS:
        raise ValueError(
            f"Unsupported period '{period}'. Supported periods: {SUPPORTED_PERIODS_TEXT}"
        )
    return value


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def analyze_dataframe(
    df: pd.DataFrame,
    symbol: str,
    strategy_name: str,
    params: Dict[str, Any],
    period: str,
    interval: str,
) -> Dict[str, Any]:
    """
    Run a strategy's generate_signals over `df` and build the analysis payload.

    `period` must already be canonical (see normalize_period). Signals are
    computed over the whole history (indicator warm-up) and only the output
    window ending at the last bar is returned.
    """
    strategy_instance = get_strategy(strategy_name, **params)

    data = df.copy()
    data.index = pd.to_datetime(data.index)
    data = data[~data.index.duplicated(keep="last")].sort_index()
    data = data[pd.to_numeric(data["Close"], errors="coerce").notna()]
    if data.empty:
        raise NoDataError("No usable bars")
    input_columns = list(data.columns)

    result = strategy_instance.generate_signals(data)
    signal = pd.to_numeric(result["signal"], errors="coerce").fillna(0).astype(int)
    previous = signal.shift(1).fillna(0).astype(int)
    changed = (signal != previous) & signal.isin([1, -1])

    last_ts = result.index[-1]
    offset = WINDOW_OFFSET[period]
    if offset is None:
        in_window = np.ones(len(result), dtype=bool)
    else:
        in_window = np.asarray(result.index >= (last_ts - offset))

    intraday = interval not in DAILY_OR_LONGER_INTERVALS

    def fmt(ts: pd.Timestamp) -> str:
        return ts.isoformat() if intraday else ts.strftime("%Y-%m-%d")

    window = result[in_window]
    truncated_history = bool(offset is not None and result.index[0] > last_ts - offset)
    signals: List[Dict[str, Any]] = []
    for ts in window.index[changed.to_numpy()[in_window]]:
        price = _finite(result.at[ts, "Close"])
        if price is None:
            continue
        signals.append({
            "date": fmt(ts),
            "type": SIGNAL_LABELS[int(signal.at[ts])],
            "price": price,
        })

    indicators: Dict[str, List[Dict[str, Any]]] = {}
    for column in result.columns:
        if column in input_columns or column == "signal":
            continue
        points = []
        for ts, value in window[column].items():
            number = _finite(value)
            if number is not None:
                points.append({"time": fmt(ts), "value": number})
        indicators[str(column)] = points

    latest = int(signal.iloc[-1])
    return {
        "symbol": symbol,
        "strategy": strategy_name,
        "parameters": dict(strategy_instance.parameters),
        "period": period,
        "interval": interval,
        "start": fmt(window.index[0]),
        "end": fmt(window.index[-1]),
        "bars": int(len(window)),
        "truncated_history": truncated_history,
        "signals": signals,
        "latest_signal": {
            "date": fmt(window.index[-1]),
            "signal": latest,
            "label": SIGNAL_LABELS[latest],
        },
        "indicators": indicators,
        "assumptions": ASSUMPTIONS,
    }
