"""Offline tests for POST /api/portfolio/api/long-term/analyze and the core strategy.

The only network seam (core._fetch_close) is monkeypatched with fixture series.
"""
import json
import math
import types

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.portfolio import long_term
from backend.portfolio.core import long_term_strategy as core

URL = "/api/portfolio/api/long-term/analyze"


def make_series(values, start="2021-01-04", tz=None):
    idx = pd.bdate_range(start, periods=len(values), tz=tz)
    return pd.Series(values, index=idx, dtype=float)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(long_term.router, prefix="/api/portfolio")
    return TestClient(app)


@pytest.fixture
def patch_fetch(monkeypatch):
    def _patch(mapping):
        calls = []

        def fake(ticker, start_date, end_date=None):
            calls.append((ticker, start_date, end_date))
            return mapping.get(ticker, pd.Series(dtype=float))

        monkeypatch.setattr(core, "_fetch_close", fake)
        return calls

    return _patch


def test_valid_single_ticker_matches_buy_and_hold(client, patch_fetch):
    closes = [100.0, 104.0, 98.0, 110.0, 121.0, 115.5]
    calls = patch_fetch({"AAPL": make_series(closes, tz="America/New_York")})
    r = client.post(URL, json={"ticker": "aapl", "capital": 20000, "start_date": "2021-01-01",
                               "risk_profile": "aggressive"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success"
    assert body["ignored_fields"] == ["risk_profile"]
    d = body["data"]
    assert calls == [("AAPL", "2021-01-01", None)]
    assert d["tickers"] == ["AAPL"] and d["allocation"] == {"AAPL": 1.0}
    assert d["initial_capital"] == 20000
    assert d["total_return"] == pytest.approx((closes[-1] / closes[0] - 1) * 100, abs=0.01)
    assert d["final_value"] == pytest.approx(20000 * closes[-1] / closes[0], abs=0.01)
    assert d["equity_curve"][0] == {"date": "2021-01-04", "value": 20000.0}
    assert len(d["equity_curve"]) == len(closes)
    # drawdown: peak 104 -> trough 98 is the first fall, but 121 -> 115.5 is smaller
    assert d["max_drawdown"] == pytest.approx((98 / 104 - 1) * 100, abs=0.01)
    # 5 return periods is too short to annualise honestly -> null with a note
    assert d["annualized_return"] is None
    assert "unavailable" in d["annualized_return_note"]
    # Sharpe from daily returns, rf = 0
    r_ = np.array(closes[1:]) / np.array(closes[:-1]) - 1
    assert d["sharpe_ratio"] == pytest.approx(r_.mean() / r_.std(ddof=1) * math.sqrt(252), abs=0.01)
    json.dumps(body, allow_nan=False)


def test_drawdown_includes_initial_point(client, patch_fetch):
    # first move is a loss; a curve starting after the first return would miss it
    patch_fetch({"X": make_series([100.0, 80.0, 85.0, 90.0])})
    d = client.post(URL, json={"ticker": "X"}).json()["data"]
    assert d["max_drawdown"] == pytest.approx(-20.0, abs=0.01)


def test_custom_allocation_is_true_buy_and_hold(client, patch_fetch):
    a = [100.0, 200.0, 200.0]
    b = [50.0, 50.0, 25.0]
    patch_fetch({"A": make_series(a), "B": make_series(b)})
    r = client.post(URL, json={"ticker": "A", "capital": 1000, "allocation": {"A": 3, "B": 1}})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["allocation"] == {"A": 0.75, "B": 0.25}
    # 750 in A doubles -> 1500; 250 in B halves -> 125
    assert d["final_value"] == pytest.approx(1625.0, abs=0.01)
    assert d["total_return"] == pytest.approx(62.5, abs=0.01)


def test_end_date_passed_to_fetch(client, patch_fetch):
    calls = patch_fetch({"X": make_series([1.0, 2.0, 3.0])})
    r = client.post(URL, json={"ticker": "X", "start_date": "2021-01-01", "end_date": "2022-01-01"})
    assert r.status_code == 200
    assert calls == [("X", "2021-01-01", "2022-01-01")]
    assert r.json()["ignored_fields"] == []


@pytest.mark.parametrize("capital", [0, -5, "abc", None])
def test_invalid_capital_rejected(client, patch_fetch, capital):
    patch_fetch({"X": make_series([1.0, 2.0, 3.0])})
    r = client.post(URL, json={"ticker": "X", "capital": capital})
    assert 400 <= r.status_code < 500


def test_non_finite_capital_rejected(client, patch_fetch):
    patch_fetch({"X": make_series([1.0, 2.0, 3.0])})
    r = client.post(URL, content='{"ticker": "X", "capital": Infinity}', headers={"content-type": "application/json"})
    assert 400 <= r.status_code < 500
    assert core.run_long_term_strategy(["X"], initial_capital=float("nan"))["error_code"] == "invalid_input"
    assert core.run_long_term_strategy(["X"], initial_capital=float("inf"))["error_code"] == "invalid_input"


def test_bad_dates_and_allocation_rejected(client, patch_fetch):
    patch_fetch({"X": make_series([1.0, 2.0, 3.0])})
    assert client.post(URL, json={"ticker": "X", "start_date": "yesterday"}).status_code == 422
    assert client.post(URL, json={"ticker": "X", "start_date": "2022-01-01", "end_date": "2021-01-01"}).status_code == 422
    assert client.post(URL, json={"ticker": "X", "allocation": {"X": -1}}).status_code == 422
    assert client.post(URL, json={"ticker": "X", "allocation": {"X": 0}}).status_code == 422
    assert client.post(URL, json={"ticker": ""}).status_code == 422


def test_data_unavailable_is_404_not_500(client, patch_fetch):
    patch_fetch({})
    r = client.post(URL, json={"ticker": "NOPE"})
    assert r.status_code == 404
    assert "NOPE" in r.json()["detail"]


def test_fetch_exception_is_404_and_partial_data_is_not_silently_dropped(client, patch_fetch, monkeypatch):
    def boom(ticker, start_date, end_date=None):
        if ticker == "BAD":
            raise RuntimeError("network down")
        return make_series([1.0, 2.0, 3.0])

    monkeypatch.setattr(core, "_fetch_close", boom)
    r = client.post(URL, json={"ticker": "OK", "allocation": {"OK": 1, "BAD": 1}})
    assert r.status_code == 404
    assert "BAD" in r.json()["detail"]


def test_too_little_data_is_404(client, patch_fetch):
    patch_fetch({"X": make_series([5.0])})
    assert client.post(URL, json={"ticker": "X"}).status_code == 404


def test_core_rejects_empty_tickers_and_unknown_allocation_keys():
    assert core.run_long_term_strategy([])["error_code"] == "invalid_input"
    res = core.run_long_term_strategy(["X"], allocation={"Y": 1.0})
    assert res["error_code"] == "invalid_input"


def test_core_nan_and_gap_handling(patch_fetch):
    s = make_series([100.0, np.nan, 110.0, 121.0])
    patch_fetch({"X": s})
    res = core.run_long_term_strategy(["X"], initial_capital=1000)
    assert res["status"] == "success"
    assert res["total_return"] == pytest.approx(21.0, abs=0.01)
    assert len(res["equity_curve"]) == 3


def test_annualized_return_for_long_enough_window(client, patch_fetch):
    closes = list(np.linspace(100.0, 130.0, 41))  # 40 return periods
    patch_fetch({"X": make_series(closes)})
    d = client.post(URL, json={"ticker": "X"}).json()["data"]
    expected = ((130.0 / 100.0) ** (252 / 40) - 1) * 100
    assert d["annualized_return"] == pytest.approx(expected, rel=1e-3)
    assert d["annualized_return_note"] is None


def test_annualized_overflow_returns_null_not_500(client, patch_fetch):
    closes = [1.0] * 20 + [1e30]  # (1e30) ** (252/20) exceeds float range -> OverflowError
    patch_fetch({"X": make_series(closes)})
    r = client.post(URL, json={"ticker": "X"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["annualized_return"] is None and d["annualized_return_note"]
    json.dumps(r.json(), allow_nan=False)


def test_flat_prices_sharpe_is_null_not_zero(client, patch_fetch):
    patch_fetch({"X": make_series([50.0] * 30)})
    d = client.post(URL, json={"ticker": "X"}).json()["data"]
    assert d["sharpe_ratio"] is None
    assert d["total_return"] == 0.0 and d["max_drawdown"] == 0.0


def test_ticker_charset_and_allocation_size_limits(client, patch_fetch):
    patch_fetch({"X": make_series([1.0, 2.0, 3.0])})
    assert client.post(URL, json={"ticker": "AA PL"}).status_code == 422
    assert client.post(URL, json={"ticker": "A" * 16}).status_code == 422
    assert client.post(URL, json={"ticker": "X;DROP"}).status_code == 422
    too_many = {f"S{i}": 1.0 for i in range(26)}
    assert client.post(URL, json={"ticker": "X", "allocation": too_many}).status_code == 422
    assert client.post(URL, json={"ticker": "X", "allocation": {"bad sym": 1.0}}).status_code == 422
    assert client.post(URL, json={"ticker": "BRK-B"}).status_code == 404  # valid symbol, no data


SECRET = "postgresql://u:pw@h/db"


def test_internal_error_in_core_is_generic_and_hides_secret(client, patch_fetch, monkeypatch):
    patch_fetch({"X": make_series([1.0, 2.0, 3.0])})

    def boom(_x):
        raise RuntimeError(f"cannot connect to {SECRET}")

    # np.sqrt is only used in the metric stage, outside the per-ticker fetch guard
    monkeypatch.setattr(core, "np", types.SimpleNamespace(inf=np.inf, nan=np.nan, sqrt=boom))
    res = core.run_long_term_strategy(["X"])
    assert res["status"] == "error" and res["error_code"] == "internal_error"
    assert SECRET not in json.dumps(res)

    r = client.post(URL, json={"ticker": "X"})
    assert r.status_code == 500
    assert SECRET not in r.text and "pw" not in r.text
    assert r.json()["detail"] == "Long-term analysis failed"


def test_route_level_exception_is_generic_and_hides_secret(client, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError(f"cannot connect to {SECRET}")

    monkeypatch.setattr(core, "run_long_term_strategy", boom)
    r = client.post(URL, json={"ticker": "X"})
    assert r.status_code == 500
    assert SECRET not in r.text
    assert r.json()["detail"] == "Long-term analysis failed"
