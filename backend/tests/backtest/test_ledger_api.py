"""HTTP/WS tests for the ledger-era run options: sizing, fee_per_fill, fill_timing, ledger in responses."""
import sys
from types import SimpleNamespace

import pytest

from test_backtest_api import STRAT_PARAMS, _ws_result, multi_payload, single_payload

FIXED = {"mode": "fixed_quantity", "value": 50}


@pytest.fixture
def served(api, long_candles, patch_candles):
    patch_candles(long_candles)
    return api


def test_single_run_reports_ledger_and_new_assumptions(served):
    r = served.post("/api/backtest/run", json=single_payload(sizing=FIXED, fee_per_fill=2, fill_timing="next_close"))
    assert r.status_code == 200, r.text
    body = r.json()
    a = body["assumptions"]
    assert a["sizingSpec"] == FIXED and a["fee_per_fill"] == 2 and a["fill_timing"] == "next_close"
    assert a["engineVersion"] == "2.2.0" and "next bar close" in a["execution"] and "50" in a["sizing"]
    ledger = body["ledger"]
    assert ledger and ledger[0]["kind"] == "fill" and ledger[-1]["kind"] in {"close_at_end", "fill", "liquidation"}
    closes = {p["date"]: p["close"] for p in body["chartData"]}
    first = ledger[0]
    assert first["price"] == pytest.approx(closes[first["date"]]) and abs(first["quantity"]) == 50
    assert first["fee"] == 2 and first["instrument"] == "TEST"
    # backward-compatible keys are all still present
    for key in ("symbol", "strategy", "initialCapital", "metrics", "chartData", "trades", "equity_curve", "monteCarlo"):
        assert key in body


def test_defaults_are_the_legacy_behaviour(served):
    explicit = served.post("/api/backtest/run", json=single_payload(
        sizing={"mode": "percent_equity", "value": 1.0}, fee_per_fill=0, fill_timing="next_open")).json()
    default = served.post("/api/backtest/run", json=single_payload()).json()
    assert explicit["ledger"] == default["ledger"] and explicit["metrics"] == default["metrics"]
    assert default["assumptions"]["sizing"] == "100% of equity, fractional shares"
    assert default["assumptions"]["execution"] == "signal on bar close, filled at next bar open"


@pytest.mark.parametrize("where", ["top", "flat_params"])
def test_options_accepted_at_top_level_or_in_params(served, where):
    extras = {"sizing": FIXED, "fee_per_fill": 3, "fill_timing": "next_close", "commission_bps": 4}
    if where == "top":
        payload = single_payload(**extras)
    else:
        payload = single_payload(params={**STRAT_PARAMS, **extras})
    r = served.post("/api/backtest/run", json=payload)
    assert r.status_code == 200, r.text
    a = r.json()["assumptions"]
    assert a["sizingSpec"] == FIXED and a["fee_per_fill"] == 3 and a["fill_timing"] == "next_close"
    assert a["commission_bps"] == 4


def test_options_in_per_strategy_params_and_multi(served):
    payload = multi_payload()
    payload["params"]["sma_crossover"].update({"sizing": FIXED, "fee_per_fill": 1})
    r = served.post("/api/backtest/run", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assumptions"]["sizingSpec"] == FIXED and body["assumptions"]["fee_per_fill"] == 1
    assert all("error" not in s for s in body["strategies"].values())
    for s in body["strategies"].values():
        assert s["ledger"] and abs(s["ledger"][0]["quantity"]) == 50


def test_multi_entries_carry_the_same_ledger_as_a_single_run(served):
    extras = dict(sizing=FIXED, fee_per_fill=1.5, commission_bps=5, slippage_bps=2, fill_timing="next_close")
    single = served.post("/api/backtest/run", json=single_payload(**extras)).json()
    multi = served.post("/api/backtest/run", json=multi_payload(**extras)).json()
    assert single["ledger"] == multi["strategies"]["sma_crossover"]["ledger"]
    assert single["trades"] == multi["strategies"]["sma_crossover"]["trades"]
    assert single["metrics"] == multi["strategies"]["sma_crossover"]["metrics"]
    assert multi["assumptions"]["fill_timing"] == "next_close"


@pytest.mark.parametrize("bad", [
    {"fill_timing": "same_close"}, {"fill_timing": 1}, {"fee_per_fill": -1}, {"fee_per_fill": "x"},
    {"sizing": {"mode": "fixed_quantity", "value": 0}}, {"sizing": {"mode": "fixed_quantity"}},
    {"sizing": {"mode": "nope", "value": 1}}, {"sizing": 5}, {"sizing": {"mode": "percent_equity", "value": 2}},
])
@pytest.mark.parametrize("builder", [single_payload, multi_payload])
def test_invalid_new_options_are_400(served, builder, bad):
    r = served.post("/api/backtest/run", json=builder(**bad))
    assert r.status_code == 400, r.text
    assert any(k in r.json()["detail"] for k in ("fill_timing", "fee_per_fill", "sizing"))


def test_rejected_orders_surface_through_the_api(served):
    # fibonacci_pullback is long/flat, so every entry is a buy that 10M shares cannot be afforded for
    r = served.post("/api/backtest/run", json=single_payload(
        strategy="fibonacci_pullback", params={"lookback": 20}, sizing={"mode": "fixed_quantity", "value": 10_000_000}))
    assert r.status_code == 200, r.text
    body = r.json()
    kinds = {e["kind"] for e in body["ledger"]}
    assert kinds == {"rejected"} and body["metrics"]["rejectedOrders"] == len(body["ledger"]) >= 1
    assert body["trades"] == [] and body["metrics"]["totalReturn"] == 0
    assert all(e["quantity"] == 0 for e in body["ledger"])


def test_websocket_accepts_the_new_options_and_matches_http(served):
    extras = dict(sizing=FIXED, fee_per_fill=2, fill_timing="next_close", initial_capital=50000)
    _, final = _ws_result(served, {"symbol": "TEST", "strategy": "sma_crossover", "params": dict(STRAT_PARAMS), **extras})
    assert final["status"] == "complete", final
    http = served.post("/api/backtest/run", json=single_payload(**extras)).json()
    assert final["data"]["ledger"] == http["ledger"] and final["data"]["metrics"] == http["metrics"]
    assert final["data"]["assumptions"]["fill_timing"] == "next_close"
    _, bad = _ws_result(served, {"symbol": "TEST", "strategy": "sma_crossover", "fill_timing": "same_close"})
    assert "fill_timing" in bad["error"]


def test_options_never_reach_the_strategy_constructor(served):
    # these keys used to be "Unknown parameter(s)" for the strategy; now they are run options
    r = served.post("/api/backtest/run", json=single_payload(params={**STRAT_PARAMS, "sizing": FIXED, "fill_timing": "next_open"}))
    assert r.status_code == 200, r.text
    r = served.post("/api/backtest/run", json=single_payload(params={**STRAT_PARAMS, "bogus": 1}))
    assert r.status_code == 400 and "Unknown parameter" in r.json()["detail"]


def test_heatmap_and_quantstats_forward_the_new_options(served, long_candles, monkeypatch):
    from backend.backtest import main as backtest_main

    calls = []
    real = backtest_main.run_backtest_on_df

    def spy(df, strategy_name, *args, **kwargs):
        calls.append(kwargs)
        return real(df, strategy_name, *args, **kwargs)

    monkeypatch.setattr(backtest_main, "fetch_candles", lambda *a, **k: [dict(c) for c in long_candles])
    monkeypatch.setattr(backtest_main, "run_backtest_on_df", spy)
    opts = {"sizing": FIXED, "fee_per_fill": 1.5, "fill_timing": "next_close"}
    r = served.post("/api/backtest/heatmap", json={
        "symbol": "TEST", "strategy": "sma_crossover", "x_values": [5, 10], "y_values": [20, 30], **opts})
    assert r.status_code == 200, r.text
    assert len(calls) == 4 and all(
        c["sizing"] == FIXED and c["fee_per_fill"] == 1.5 and c["fill_timing"] == "next_close" for c in calls)
    # the heatmap cell is the same total return a /run with the same assumptions reports
    run = served.post("/api/backtest/run", json=single_payload(
        params={"fast": 5, "slow": 20}, **opts)).json()
    assert r.json()["values"][0][0] == pytest.approx(run["metrics"]["totalReturn"])

    bad = served.post("/api/backtest/heatmap", json={"symbol": "TEST", "strategy": "sma_crossover", "fill_timing": "x"})
    assert bad.status_code == 400

    calls.clear()
    fake_qs = SimpleNamespace(reports=SimpleNamespace(html=lambda returns, **kw: None))
    monkeypatch.setitem(sys.modules, "quantstats", fake_qs)
    r = served.post("/api/backtest/quantstats-report", json={
        "symbol": "TEST", "strategy": "sma_crossover", "params": dict(STRAT_PARAMS), **opts})
    assert r.status_code == 200, r.text
    assert len(calls) == 1
    kw = calls[0]
    assert kw["sizing"] == FIXED and kw["fee_per_fill"] == 1.5 and kw["fill_timing"] == "next_close"
    assert kw["fast_period"] == 5 and "seed" not in kw
    bad = served.post("/api/backtest/quantstats-report", json={"symbol": "TEST", "strategy": "sma_crossover", "fee_per_fill": -1})
    assert bad.status_code == 400


def test_every_route_goes_through_run_spec(served, long_candles, monkeypatch):
    """/run (single, multi), WS, heatmap and QuantStats all reach the engine via service.run_spec."""
    from backend.backtest import main as backtest_main
    from backend.backtest import service

    seen = []
    real = service.run_spec

    def spy(df, spec, **kw):
        seen.append(spec["strategy"])
        return real(df, spec, **kw)

    monkeypatch.setattr(service, "run_spec", spy)
    monkeypatch.setattr(backtest_main, "fetch_candles", lambda *a, **k: [dict(c) for c in long_candles])
    monkeypatch.setitem(sys.modules, "quantstats", SimpleNamespace(reports=SimpleNamespace(html=lambda r, **kw: None)))
    assert served.post("/api/backtest/run", json=single_payload()).status_code == 200
    assert len(seen) == 1
    assert served.post("/api/backtest/run", json=multi_payload()).status_code == 200
    assert len(seen) == 3
    _ws_result(served, {"symbol": "TEST", "strategy": "sma_crossover", "params": dict(STRAT_PARAMS)})
    assert len(seen) == 4
    served.post("/api/backtest/heatmap", json={"symbol": "TEST", "strategy": "sma_crossover", "x_values": [5], "y_values": [20]})
    assert len(seen) == 5
    served.post("/api/backtest/quantstats-report", json={"symbol": "TEST", "strategy": "sma_crossover", "params": dict(STRAT_PARAMS)})
    assert len(seen) == 6
