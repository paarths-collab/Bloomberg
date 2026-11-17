"""
Isolated long_term_strategy for portfolio/core.
Self-contained buy-and-hold / asset allocation strategy runner.
Modifying this does NOT affect any other module.

Model: capital is split across tickers by ``allocation`` on the first common
trading day and then held (true buy-and-hold: no rebalancing, no contributions,
no fees).  ``_fetch_close`` is the only network seam.

Sharpe ratio uses a 0% risk-free rate and 252 periods per year. Metrics that cannot be
computed are None (never a fabricated 0); annualized_return needs >= 20 return periods.
"""
import logging
import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TRADING_DAYS = 252
MIN_PERIODS_FOR_ANNUALIZING = 20

ERR_INVALID_INPUT = "invalid_input"
ERR_DATA_UNAVAILABLE = "data_unavailable"
ERR_INTERNAL = "internal_error"


def _error(code: str, message: str) -> Dict[str, Any]:
    return {"status": "error", "error_code": code, "error": message}


def _fetch_close(ticker: str, start_date: str, end_date: Optional[str] = None) -> pd.Series:
    """Network seam: daily Close prices for ``ticker`` (empty Series if unavailable)."""
    from backend.services.market_data import market_service

    hist = market_service.get_history(ticker, start=start_date, end=end_date)
    if hist is None or hist.empty or "Close" not in hist.columns:
        return pd.Series(dtype=float)
    return hist["Close"]


def _normalise_prices(s: pd.Series) -> pd.Series:
    """Finite, positive closes on a tz-naive daily index (sorted, de-duplicated)."""
    s = pd.to_numeric(s, errors="coerce").astype(float)
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    s = s[s > 0]
    return s[~s.index.duplicated(keep="last")].sort_index()


def _finite(x: float, ndigits: int = 2) -> Optional[float]:
    """Rounded float, or None when not finite (never a fabricated zero)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, ndigits) if math.isfinite(x) else None


def run_long_term_strategy(
    tickers: List[str],
    allocation: Optional[Dict[str, float]] = None,
    start_date: str = "2020-01-01",
    initial_capital: float = 100000,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run a long-term buy-and-hold portfolio with equal or custom allocation.

    Args:
        tickers: List of ticker symbols
        allocation: Dict of {ticker: weight} (non-negative, normalised to sum 1). Equal if None.
        start_date: Strategy start date in YYYY-MM-DD format
        initial_capital: Starting portfolio value (finite, > 0)
        end_date: Optional last date (YYYY-MM-DD) for the price history

    Returns:
        Portfolio performance metrics and equity curve. On failure returns
        {"status": "error", "error_code": ..., "error": ...}.
    """
    if not tickers:
        return _error(ERR_INVALID_INPUT, "No tickers provided")

    try:
        capital = float(initial_capital)
    except (TypeError, ValueError):
        return _error(ERR_INVALID_INPUT, "initial_capital must be a number")
    if not math.isfinite(capital) or capital <= 0:
        return _error(ERR_INVALID_INPUT, "initial_capital must be a finite number > 0")

    tickers = [str(t).strip().upper() for t in tickers]
    tickers = list(dict.fromkeys(t for t in tickers if t))
    if not tickers:
        return _error(ERR_INVALID_INPUT, "No tickers provided")

    if not allocation:
        weights = {t: 1.0 / len(tickers) for t in tickers}
    else:
        weights = {}
        for k, v in allocation.items():
            try:
                w = float(v)
            except (TypeError, ValueError):
                return _error(ERR_INVALID_INPUT, f"Invalid allocation weight for {k}")
            if not math.isfinite(w) or w < 0:
                return _error(ERR_INVALID_INPUT, f"Invalid allocation weight for {k}")
            weights[str(k).strip().upper()] = weights.get(str(k).strip().upper(), 0.0) + w
        unknown = sorted(set(weights) - set(tickers))
        if unknown:
            return _error(ERR_INVALID_INPUT, f"Allocation has tickers not in tickers list: {', '.join(unknown)}")
        total = sum(weights.values())
        if total <= 0:
            return _error(ERR_INVALID_INPUT, "Allocation weights must sum to more than 0")
        weights = {k: v / total for k, v in weights.items() if v > 0}

    try:
        # Only tickers that actually receive capital need data.
        needed = [t for t in tickers if weights.get(t, 0) > 0]
        data: Dict[str, pd.Series] = {}
        missing: List[str] = []
        for ticker in needed:
            try:
                s = _normalise_prices(_fetch_close(ticker, start_date, end_date))
            except Exception as e:
                logger.warning("[long_term_strategy] Failed to fetch %s: %s", ticker, e)
                s = pd.Series(dtype=float)
            if s.empty:
                missing.append(ticker)
            else:
                data[ticker] = s

        if missing:
            return _error(ERR_DATA_UNAVAILABLE, f"Could not fetch price data for: {', '.join(missing)}")

        prices = pd.DataFrame(data).dropna()
        if len(prices) < 2:
            return _error(ERR_DATA_UNAVAILABLE, "Not enough overlapping price data (need at least 2 common dates)")

        # True buy-and-hold: shares are bought once at the first common close.
        shares = pd.Series({t: capital * weights[t] / prices[t].iloc[0] for t in data})
        equity = prices.mul(shares, axis=1).sum(axis=1)  # starts at exactly `capital`
        daily_returns = equity.pct_change().dropna()

        n_periods = len(daily_returns)
        final = float(equity.iloc[-1])
        total_return = (final / capital - 1) * 100
        max_drawdown = ((equity / equity.cummax()) - 1).min() * 100
        annualized_return: Optional[float] = None
        annualized_note: Optional[str] = None
        if n_periods < MIN_PERIODS_FOR_ANNUALIZING:
            annualized_note = (
                f"unavailable: window has {n_periods} return periods (< {MIN_PERIODS_FOR_ANNUALIZING}); "
                "annualising a short window is not meaningful"
            )
        else:
            try:
                annualized_return = ((final / capital) ** (TRADING_DAYS / n_periods) - 1) * 100
            except OverflowError:
                annualized_return = None
            if annualized_return is None or not math.isfinite(annualized_return):
                annualized_return = None
                annualized_note = "unavailable: annualised return is not finite"
        std = daily_returns.std()
        if std is not None and math.isfinite(std) and std > 0:
            sharpe: Optional[float] = (daily_returns.mean() / std) * np.sqrt(TRADING_DAYS)
        else:
            sharpe = None  # zero/undefined volatility: Sharpe is undefined

        curve = [
            {"date": idx.strftime("%Y-%m-%d"), "value": round(float(val), 2)}
            for idx, val in equity.items()
        ]

        return {
            "tickers": list(data),
            "allocation": {t: weights[t] for t in data},
            "initial_capital": capital,
            "start": curve[0]["date"],
            "end": curve[-1]["date"],
            "final_value": _finite(final),
            "total_return": _finite(total_return),
            "annualized_return": _finite(annualized_return) if annualized_return is not None else None,
            "annualized_return_note": annualized_note,
            "max_drawdown": _finite(max_drawdown),
            "sharpe_ratio": _finite(sharpe) if sharpe is not None else None,
            "equity_curve": curve,
            "status": "success",
        }

    except Exception as e:
        logger.error("[long_term_strategy] Error: %s", e, exc_info=True)
        return _error(ERR_INTERNAL, "Long-term analysis failed")
