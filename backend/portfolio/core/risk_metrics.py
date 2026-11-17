"""
Computed portfolio risk metrics (pure, no network in ``compute_portfolio_risk``).

Method
------
Historical risk of the CURRENT holdings held statically over the lookback
window.  This is *not* the portfolio's realised track record (no trades or
cash flows are modelled); it answers "how risky would today's positions have
been over the lookback?".

1. Portfolio value ``V(t) = sum_i qty_i * close_i(t)`` on the dates where ALL
   holdings have a finite close (inner join; NaN/inf rows dropped).
2. ``r_p = V.pct_change().dropna()``.
3. ``volatility_annualized_pct = std(r_p, ddof=1) * sqrt(periods_per_year) * 100``.
4. ``sharpe_ratio = (mean(r_p) - rf/ppy) / std(r_p, ddof=1) * sqrt(ppy)``
   (unavailable when the standard deviation is ~0).
5. ``max_drawdown_pct = min(V / V.cummax() - 1) * 100`` (always <= 0).
6. ``beta = cov(r_p, r_b) / var(r_b)`` (both ddof=1).  The portfolio value
   series and the benchmark price series are first intersected on dates, then
   both are converted to returns, so paired returns always span the same
   interval even if either series has gaps.

Honesty rules: a metric that cannot be computed is returned as
``{"value": None, "status": "unavailable", "reason": "..."}``.  Holdings are
never silently dropped - if any held symbol has no history, every metric is
unavailable and the reason names the missing symbols.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, Iterable, Optional

import numpy as np
import pandas as pd

METRIC_NAMES = ("beta", "sharpe_ratio", "max_drawdown_pct", "volatility_annualized_pct")
_ZERO_STD_EPS = 1e-12
_ROUND = 4

METHOD = (
    "Historical risk of the current holdings held statically over the lookback: "
    "V(t)=sum(qty*close) on dates where all holdings have a close; "
    "r_p=V.pct_change(); volatility=std(r_p,ddof=1)*sqrt(periods_per_year); "
    "sharpe=(mean(r_p)-rf/periods_per_year)/std(r_p,ddof=1)*sqrt(periods_per_year); "
    "max_drawdown=min(V/cummax(V)-1); beta=cov(r_p,r_b)/var(r_b) on returns of the value and benchmark series after intersecting their dates."
)


def _ok(value: float) -> Dict[str, Any]:
    return {"value": round(float(value), _ROUND), "status": "ok"}


def _unavailable(reason: str) -> Dict[str, Any]:
    return {"value": None, "status": "unavailable", "reason": reason}


def _clean_series(s: Any) -> pd.Series:
    """Numeric, finite, date-indexed (tz-naive, normalised to midnight), de-duplicated, sorted."""
    if s is None:
        return pd.Series(dtype=float)
    if isinstance(s, pd.DataFrame):
        if "Close" in s.columns:
            s = s["Close"]
        elif s.shape[1] == 1:
            s = s.iloc[:, 0]
        else:
            return pd.Series(dtype=float)
    if not isinstance(s, pd.Series) or s.empty:
        return pd.Series(dtype=float)
    s = pd.to_numeric(s, errors="coerce").astype(float)
    try:
        idx = pd.to_datetime(s.index, utc=False)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)  # keep the local calendar date
        s.index = idx.normalize()
    except Exception:
        return pd.Series(dtype=float)
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


def _norm_symbol(sym: Any) -> str:
    return str(sym).strip().upper()


def _all_unavailable(reason: str, base: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    out["metrics"] = {name: _unavailable(reason) for name in METRIC_NAMES}
    return out


def compute_portfolio_risk(
    holdings: Dict[str, float],
    price_history: Dict[str, pd.Series],
    benchmark_history: Optional[pd.Series],
    *,
    benchmark_symbol: str = "SPY",
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
    min_observations: int = 60,
) -> Dict[str, Any]:
    """Compute beta, Sharpe, max drawdown and volatility for the given holdings.

    ``holdings`` maps symbol -> quantity (>0); ``price_history`` maps symbol ->
    close prices indexed by date; ``benchmark_history`` is the benchmark's close
    series (or None).  See the module docstring for the method.
    """
    base: Dict[str, Any] = {
        "method": METHOD,
        "benchmark": benchmark_symbol,
        "risk_free_rate": risk_free_rate,
        "periods_per_year": periods_per_year,
        "observations": 0,
        "start": None,
        "end": None,
        "weights": {},
    }

    # Keep only finite, positive quantities; anything else is reported, not dropped.
    quantities: Dict[str, float] = {}
    bad_qty = []
    for raw_sym, qty in (holdings or {}).items():
        sym = _norm_symbol(raw_sym)
        try:
            q = float(qty)
        except (TypeError, ValueError):
            bad_qty.append(sym)
            continue
        if not math.isfinite(q) or q <= 0:
            bad_qty.append(sym)
        else:
            quantities[sym] = quantities.get(sym, 0.0) + q

    if not holdings:
        return _all_unavailable("no holdings", base)
    if bad_qty:
        return _all_unavailable(f"invalid quantity for: {', '.join(sorted(bad_qty))}", base)

    history = {_norm_symbol(k): v for k, v in (price_history or {}).items()}
    cleaned = {sym: _clean_series(history.get(sym)) for sym in quantities}
    missing = sorted(sym for sym, s in cleaned.items() if s.empty)
    if missing:
        return _all_unavailable(f"no price history for: {', '.join(missing)}", base)

    prices = pd.concat(cleaned, axis=1, join="inner").dropna()
    if prices.empty:
        return _all_unavailable("holdings have no overlapping price dates", base)

    qty_vec = pd.Series(quantities)[prices.columns]
    components = prices.mul(qty_vec, axis=1)
    value = components.sum(axis=1)
    value = value[value > 0]
    if len(value) < 2:
        return _all_unavailable("insufficient history: fewer than 2 price points", base)

    returns = value.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    n_obs = int(len(returns))

    last = components.loc[value.index[-1]]
    total = float(last.sum())
    result = dict(base)
    result.update(
        observations=n_obs,
        start=value.index[0].strftime("%Y-%m-%d"),
        end=value.index[-1].strftime("%Y-%m-%d"),
        weights={sym: round(float(last[sym] / total), _ROUND) for sym in prices.columns},
    )

    metrics: Dict[str, Dict[str, Any]] = {}
    if n_obs < min_observations:
        reason = f"insufficient history: {n_obs} < {min_observations}"
        result["metrics"] = {name: _unavailable(reason) for name in METRIC_NAMES}
        return result

    std = float(returns.std(ddof=1))
    ann = math.sqrt(periods_per_year)

    if not math.isfinite(std):
        metrics["volatility_annualized_pct"] = _unavailable("undefined volatility")
        metrics["sharpe_ratio"] = _unavailable("undefined volatility")
    else:
        metrics["volatility_annualized_pct"] = _ok(std * ann * 100.0)
        if std < _ZERO_STD_EPS:
            metrics["sharpe_ratio"] = _unavailable("zero volatility")
        else:
            sharpe = (float(returns.mean()) - risk_free_rate / periods_per_year) / std * ann
            metrics["sharpe_ratio"] = _ok(sharpe) if math.isfinite(sharpe) else _unavailable("non-finite result")

    drawdown = float((value / value.cummax() - 1.0).min()) * 100.0
    metrics["max_drawdown_pct"] = _ok(min(drawdown, 0.0) + 0.0)

    metrics["beta"] = _compute_beta(value, benchmark_history, benchmark_symbol, min_observations)

    result["metrics"] = {name: metrics[name] for name in METRIC_NAMES}
    return result


def _compute_beta(
    value: pd.Series,
    benchmark_history: Optional[pd.Series],
    benchmark_symbol: str,
    min_observations: int,
) -> Dict[str, Any]:
    """Beta on a common date grid.

    The portfolio VALUE series and the benchmark PRICE series are first
    intersected on dates; only then are both turned into returns, so each pair
    of returns covers exactly the same interval even when either side has gaps.
    """
    bench = _clean_series(benchmark_history)
    if bench.empty:
        return _unavailable(f"no benchmark history for {benchmark_symbol}")
    common = value.index.intersection(bench.index)
    pv = value.loc[common]
    bp = bench.loc[common]
    r_p = pv.pct_change().replace([np.inf, -np.inf], np.nan)
    r_b = bp.pct_change().replace([np.inf, -np.inf], np.nan)
    aligned = pd.concat([r_p.rename("p"), r_b.rename("b")], axis=1).dropna()
    n = len(aligned)
    if n < min_observations:
        return _unavailable(f"insufficient history: {n} < {min_observations} overlapping benchmark observations")
    var_b = float(aligned["b"].var(ddof=1))
    if not math.isfinite(var_b) or var_b < _ZERO_STD_EPS ** 2:
        return _unavailable("zero benchmark variance")
    cov = float(aligned["p"].cov(aligned["b"]))  # ddof=1, consistent with var
    beta = cov / var_b
    if not math.isfinite(beta):
        return _unavailable("non-finite result")
    return _ok(beta)


def load_price_history(
    symbols: Iterable[str],
    *,
    period: str = "1y",
    interval: str = "1d",
    fetch: Optional[Callable[..., Any]] = None,
) -> Dict[str, pd.Series]:
    """Fetch Close series for each symbol.

    By default uses ``market_service.get_history(symbol, period=, interval=)``
    (returns an OHLCV DataFrame, empty on failure).  ``fetch(symbol, period=,
    interval=)`` may be injected (e.g. in tests); it may return a DataFrame with
    a ``Close`` column or a Series.  Failures and empty results map to an empty
    Series so ``compute_portfolio_risk`` can report them.
    """
    if fetch is None:
        from backend.services.market_data import market_service

        fetch = market_service.get_history

    out: Dict[str, pd.Series] = {}
    for symbol in symbols:
        try:
            data = fetch(symbol, period=period, interval=interval)
            if isinstance(data, pd.DataFrame):
                series = data["Close"] if "Close" in data.columns else pd.Series(dtype=float)
            elif isinstance(data, pd.Series):
                series = data
            else:
                series = pd.Series(dtype=float)
            series = series.dropna()
        except Exception:
            series = pd.Series(dtype=float)
        out[symbol] = series
    return out
