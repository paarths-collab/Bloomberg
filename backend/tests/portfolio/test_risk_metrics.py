"""Offline unit tests for backend.portfolio.core.risk_metrics (all data synthetic)."""
import json
import math

import numpy as np
import pandas as pd
import pytest

from backend.portfolio.core import risk_metrics as rm
from backend.portfolio.core.risk_metrics import compute_portfolio_risk, load_price_history


def series(values, start="2024-01-01", tz=None):
    idx = pd.date_range(start, periods=len(values), freq="D", tz=tz)
    return pd.Series(values, index=idx, dtype=float)


def bench_and_returns(n=120, seed=7):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0005, 0.01, n)
    closes = 100 * np.cumprod(1 + r)
    return series(np.concatenate([[100.0], closes])), r


def metric(res, name):
    return res["metrics"][name]


def assert_all_unavailable(res, reason_part):
    for name in rm.METRIC_NAMES:
        m = metric(res, name)
        assert m["status"] == "unavailable" and m["value"] is None
        assert reason_part in m["reason"]


# ----- beta -----------------------------------------------------------------

def test_beta_one_when_portfolio_equals_benchmark():
    bench, _ = bench_and_returns()
    res = compute_portfolio_risk({"SPY": 3}, {"SPY": bench}, bench)
    assert metric(res, "beta")["status"] == "ok"
    assert metric(res, "beta")["value"] == pytest.approx(1.0, abs=1e-6)


def test_beta_two_for_2x_leveraged_holding():
    bench, r_b = bench_and_returns()
    lev = series(np.concatenate([[50.0], 50.0 * np.cumprod(1 + 2 * r_b)]))
    res = compute_portfolio_risk({"LEV": 10}, {"LEV": lev}, bench)
    assert metric(res, "beta")["value"] == pytest.approx(2.0, abs=1e-4)


def test_beta_unavailable_without_benchmark_or_zero_variance_or_short_overlap():
    bench, r_b = bench_and_returns()
    hold = series(bench.values * 2)
    res = compute_portfolio_risk({"A": 1}, {"A": hold}, None)
    assert metric(res, "beta")["status"] == "unavailable"
    assert "no benchmark history for SPY" in metric(res, "beta")["reason"]
    # the other metrics are unaffected
    assert metric(res, "volatility_annualized_pct")["status"] == "ok"

    flat_bench = series([100.0] * len(bench))
    res = compute_portfolio_risk({"A": 1}, {"A": hold}, flat_bench)
    assert metric(res, "beta")["reason"] == "zero benchmark variance"

    short_bench = bench.iloc[:30]
    res = compute_portfolio_risk({"A": 1}, {"A": hold}, short_bench)
    assert "insufficient history" in metric(res, "beta")["reason"]
    assert metric(res, "sharpe_ratio")["status"] == "ok"


# ----- hand-checked volatility / sharpe / drawdown ----------------------------

def test_hand_computed_vol_sharpe_drawdown():
    closes = [100, 102, 101, 105, 103, 108]
    qty = 2  # scaling the position must not change any return-based metric
    # Explicit arithmetic with plain python (independent of pandas/numpy)
    r = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    n = len(r)
    mean = sum(r) / n
    var = sum((x - mean) ** 2 for x in r) / (n - 1)
    std = math.sqrt(var)
    rf, ppy = 0.02, 252
    exp_vol = std * math.sqrt(ppy) * 100
    exp_sharpe = (mean - rf / ppy) / std * math.sqrt(ppy)
    # peak 105 -> trough 103 is the deepest fall: 103/105 - 1
    exp_dd = (103 / 105 - 1) * 100
    assert exp_dd == pytest.approx(-1.904761, abs=1e-5)

    res = compute_portfolio_risk(
        {"X": qty}, {"X": series(closes)}, None,
        risk_free_rate=rf, periods_per_year=ppy, min_observations=5,
    )
    assert res["observations"] == 5
    assert res["start"] == "2024-01-01" and res["end"] == "2024-01-06"
    assert metric(res, "volatility_annualized_pct")["value"] == pytest.approx(exp_vol, abs=1e-4)
    assert metric(res, "sharpe_ratio")["value"] == pytest.approx(exp_sharpe, abs=1e-4)
    assert metric(res, "max_drawdown_pct")["value"] == pytest.approx(exp_dd, abs=1e-4)
    assert res["weights"] == {"X": 1.0}


def test_two_holdings_value_and_weights():
    a = series([10, 11, 12, 11, 13, 14])
    b = series([20, 20, 22, 24, 23, 25])
    res = compute_portfolio_risk({"A": 3, "B": 1}, {"A": a, "B": b}, None, min_observations=5)
    v = [3 * x + y for x, y in zip(a, b)]
    r = [v[i] / v[i - 1] - 1 for i in range(1, len(v))]
    mean = sum(r) / len(r)
    std = math.sqrt(sum((x - mean) ** 2 for x in r) / (len(r) - 1))
    assert metric(res, "volatility_annualized_pct")["value"] == pytest.approx(std * math.sqrt(252) * 100, abs=1e-4)
    assert res["weights"]["A"] == pytest.approx(3 * 14 / (3 * 14 + 25), abs=1e-4)
    assert sum(res["weights"].values()) == pytest.approx(1.0, abs=1e-3)


def test_constant_prices_zero_vol_sharpe_unavailable_drawdown_zero():
    res = compute_portfolio_risk({"X": 5}, {"X": series([50.0] * 80)}, None)
    assert metric(res, "volatility_annualized_pct") == {"value": 0.0, "status": "ok"}
    assert metric(res, "max_drawdown_pct")["value"] == 0.0
    sharpe = metric(res, "sharpe_ratio")
    assert sharpe["status"] == "unavailable" and sharpe["reason"] == "zero volatility"


# ----- unavailable paths -----------------------------------------------------

def test_insufficient_observations():
    res = compute_portfolio_risk({"X": 1}, {"X": series([100, 101, 102, 103])}, None)
    assert res["observations"] == 3
    assert_all_unavailable(res, "insufficient history: 3 < 60")


def test_empty_holdings():
    res = compute_portfolio_risk({}, {}, None)
    assert_all_unavailable(res, "no holdings")
    assert res["weights"] == {} and res["observations"] == 0 and res["start"] is None


def test_missing_or_empty_history_names_symbol_and_does_not_drop_holding():
    bench, _ = bench_and_returns()
    good = series(bench.values)
    res = compute_portfolio_risk(
        {"GOOD": 1, "BAD": 1, "GONE": 2}, {"GOOD": good, "BAD": pd.Series(dtype=float)}, bench
    )
    assert_all_unavailable(res, "no price history for: BAD, GONE")
    assert res["weights"] == {}


def test_invalid_quantity_is_reported():
    res = compute_portfolio_risk({"X": -1}, {"X": series([1.0, 2.0])}, None)
    assert_all_unavailable(res, "invalid quantity for: X")


# ----- date handling / gaps / non-finite ---------------------------------------

def test_tz_aware_index_works():
    bench, _ = bench_and_returns()
    hold = series(bench.values, tz="America/New_York")
    res = compute_portfolio_risk({"A": 1}, {"A": hold}, bench)
    assert metric(res, "beta")["value"] == pytest.approx(1.0, abs=1e-6)
    assert res["start"] == "2024-01-01"


def test_nan_gap_removed_by_inner_join():
    a = series(np.linspace(100, 120, 70))
    b = series(np.linspace(50, 40, 70))
    a.iloc[30] = np.nan
    b.iloc[40] = np.inf  # non-finite dropped before alignment
    bench = series(np.linspace(100, 130, 70))
    res = compute_portfolio_risk({"A": 1, "B": 1}, {"A": a, "B": b}, bench)
    assert res["observations"] == 70 - 2 - 1  # 68 shared dates -> 67 returns
    for name in ("volatility_annualized_pct", "sharpe_ratio", "max_drawdown_pct", "beta"):
        assert metric(res, name)["status"] == "ok"
    # weights at the last date: A=120, B=40 (qty 1 each)
    assert res["weights"] == {"A": pytest.approx(0.75, abs=1e-4), "B": pytest.approx(0.25, abs=1e-4)}
    assert metric(res, "beta")["value"] is not None


def test_beta_exactly_one_when_benchmark_has_gaps():
    bench, _ = bench_and_returns(n=120)
    gappy = bench.drop(bench.index[[5, 17, 18, 40, 41, 42, 70, 71, 90, 100]])
    res = compute_portfolio_risk({"SPY": 2}, {"SPY": bench}, gappy)
    assert metric(res, "beta")["status"] == "ok"
    assert metric(res, "beta")["value"] == pytest.approx(1.0, abs=1e-6)


def test_beta_exactly_one_when_holding_has_nan_gaps():
    bench, _ = bench_and_returns(n=120)
    hold = bench.copy()
    hold.iloc[[3, 25, 26, 60, 99]] = np.nan
    res = compute_portfolio_risk({"SPY": 1}, {"SPY": hold}, bench)
    assert metric(res, "beta")["status"] == "ok"
    assert metric(res, "beta")["value"] == pytest.approx(1.0, abs=1e-6)


def test_symbols_are_case_and_whitespace_normalised():
    bench, _ = bench_and_returns()
    res = compute_portfolio_risk({" aapl ": 1, "AAPL": 1}, {"Aapl": series(bench.values)}, bench)
    assert metric(res, "beta")["value"] == pytest.approx(1.0, abs=1e-6)
    assert res["weights"] == {"AAPL": 1.0}
    res = compute_portfolio_risk({"msft": 1}, {"AAPL": series(bench.values)}, bench)
    assert_all_unavailable(res, "no price history for: MSFT")


def test_output_is_json_safe_and_finite():
    bench, _ = bench_and_returns()
    res = compute_portfolio_risk({"A": 2}, {"A": series(bench.values)}, bench)
    text = json.dumps(res, allow_nan=False)
    assert "NaN" not in text and "Infinity" not in text
    for name in rm.METRIC_NAMES:
        assert metric(res, name)["status"] == "ok"
        assert math.isfinite(metric(res, name)["value"])
    assert res["benchmark"] == "SPY" and res["periods_per_year"] == 252 and res["risk_free_rate"] == 0.0
    assert "intersect" in res["method"] and "cummax" in res["method"]


# ----- load_price_history ------------------------------------------------------

def test_load_price_history_injected_fetch():
    calls = []

    def fake_fetch(symbol, period=None, interval=None):
        calls.append((symbol, period, interval))
        if symbol == "BOOM":
            raise RuntimeError("network down")
        if symbol == "EMPTY":
            return pd.DataFrame()
        idx = pd.date_range("2024-01-01", periods=3, freq="D")
        return pd.DataFrame({"Close": [1.0, np.nan, 3.0], "Open": [0, 0, 0]}, index=idx)

    out = load_price_history(["AAA", "EMPTY", "BOOM"], period="6mo", interval="1d", fetch=fake_fetch)
    assert list(out) == ["AAA", "EMPTY", "BOOM"]
    assert list(out["AAA"].values) == [1.0, 3.0]
    assert out["EMPTY"].empty and out["BOOM"].empty
    assert calls[0] == ("AAA", "6mo", "1d")

    res = compute_portfolio_risk({"AAA": 1, "BOOM": 1}, out, None)
    assert_all_unavailable(res, "no price history for: BOOM")


def test_load_price_history_defaults_to_market_service(monkeypatch):
    from backend.services.market_data import market_service

    seen = {}

    def fake_get_history(ticker, period="6mo", interval="1d", start=None, end=None):
        seen[ticker] = (period, interval)
        idx = pd.date_range("2024-01-01", periods=2, freq="D")
        return pd.DataFrame({"Close": [10.0, 11.0]}, index=idx)

    monkeypatch.setattr(market_service, "get_history", fake_get_history)
    out = load_price_history(["MSFT"])
    assert seen == {"MSFT": ("1y", "1d")}
    assert list(out["MSFT"].values) == [10.0, 11.0]
