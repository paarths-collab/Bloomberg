"""HTTP-level tests for /api/backtest (monkeypatched data, minimal app with only the backtest router)."""
import pytest

STRAT_PARAMS = {"fast": 5, "slow": 20}  # frontend-style names, normalised to fast_period/slow_period


def single_payload(**extra):
    return {"symbol": "TEST", "strategy": "sma_crossover", "range": "1y", "params": dict(STRAT_PARAMS), **extra}


def multi_payload(**extra):
    return {
        "symbol": "TEST",
        "strategies": ["sma_crossover", "ema_crossover"],
        "range": "1y",
        "params": {"sma_crossover": dict(STRAT_PARAMS), "ema_crossover": {"fast": 8, "slow": 21}},
        **extra,
    }


@pytest.fixture
def served(api, long_candles, patch_candles):
    patch_candles(long_candles)
    return api


# ---------------------------------------------------------------------------
# 5. Capital forwarding
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["initial_capital", "initialCapital"])
def test_single_run_uses_requested_capital(served, key):
    r = served.post("/api/backtest/run", json=single_payload(**{key: 50000}))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["metrics"]["initialCapital"] == 50000
    assert body["equity_curve"][0]["value"] == pytest.approx(50000)
    assert body["equity_curve"][0]["benchmark"] == pytest.approx(50000)
    assert body["chartData"][0]["equity"] == pytest.approx(50000)
    assert body["metrics"]["finalEquity"] == pytest.approx(50000 * (1 + body["metrics"]["totalReturn"] / 100), rel=1e-3)
    assert body["assumptions"]["execution"] == "signal on bar close, filled at next bar open"


def test_multi_run_uses_requested_capital(served):
    r = served.post("/api/backtest/run", json=multi_payload(initial_capital=50000))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["initialCapital"] == 50000
    assert body["benchmarkCurve"][0]["value"] == pytest.approx(50000)
    assert set(body["strategies"]) == {"sma_crossover", "ema_crossover"}
    for result in body["strategies"].values():
        assert "error" not in result, result
        assert result["metrics"]["initialCapital"] == 50000
        assert result["equityCurve"][0]["value"] == pytest.approx(50000)
    assert body["combinedChartData"][0]["sma_crossover"] == pytest.approx(50000)
    assert body["assumptions"]["sizing"] == "100% of equity, fractional shares"


def test_capital_in_params_is_a_backward_compatible_fallback_and_never_hits_the_strategy(served):
    # single, flat params
    r = served.post("/api/backtest/run", json=single_payload(params={**STRAT_PARAMS, "initial_capital": 25000}))
    assert r.status_code == 200, r.text
    assert r.json()["metrics"]["initialCapital"] == 25000
    # multi, per-strategy params (used to raise TypeError inside get_strategy)
    payload = multi_payload()
    payload["params"]["sma_crossover"]["initial_capital"] = 25000
    r = served.post("/api/backtest/run", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["initialCapital"] == 25000
    assert all("error" not in s for s in body["strategies"].values())
    # top level wins over params
    r = served.post("/api/backtest/run", json=single_payload(initial_capital=70000, params={**STRAT_PARAMS, "initial_capital": 1}))
    assert r.json()["metrics"]["initialCapital"] == 70000


def test_default_capital_is_100000(served):
    r = served.post("/api/backtest/run", json=single_payload())
    assert r.json()["metrics"]["initialCapital"] == 100000
    assert r.json()["equity_curve"][0]["value"] == pytest.approx(100000)


@pytest.mark.parametrize("bad", [0, -1, "abc", -0.5, True])
@pytest.mark.parametrize("builder", [single_payload, multi_payload])
def test_invalid_capital_is_400(served, builder, bad):
    r = served.post("/api/backtest/run", json=builder(initial_capital=bad))
    assert r.status_code == 400, r.text
    assert "initial_capital" in r.json()["detail"]


def test_invalid_costs_and_seed_are_400(served):
    for extra in ({"commission_bps": -1}, {"slippage_bps": "x"}, {"seed": 1.5}, {"seed": -3}):
        r = served.post("/api/backtest/run", json=single_payload(**extra))
        assert r.status_code == 400, (extra, r.text)


def test_single_and_multi_give_identical_results_for_same_strategy(served):
    single = served.post("/api/backtest/run", json=single_payload(initial_capital=50000)).json()
    multi = served.post("/api/backtest/run", json=multi_payload(initial_capital=50000)).json()
    in_multi = multi["strategies"]["sma_crossover"]
    assert single["metrics"] == in_multi["metrics"]
    assert single["trades"] == in_multi["trades"]
    assert single["monteCarlo"] == in_multi["monteCarlo"]
    assert [p["value"] for p in single["equity_curve"]] == [p["value"] for p in in_multi["equityCurve"]]
    assert [p["benchmark"] for p in single["equity_curve"]] == [p["value"] for p in multi["benchmarkCurve"]]


def test_costs_and_seed_are_forwarded(served):
    r = served.post("/api/backtest/run", json=single_payload(commission_bps=10, slippage_bps=5, seed=7))
    assert r.status_code == 200, r.text
    a = r.json()["assumptions"]
    assert (a["commission_bps"], a["slippage_bps"], a["monteCarloSeed"]) == (10, 5, 7)
    gross = served.post("/api/backtest/run", json=single_payload()).json()
    assert r.json()["metrics"]["finalEquity"] != gross["metrics"]["finalEquity"]


def test_same_seed_same_monte_carlo_over_http(served):
    a = served.post("/api/backtest/run", json=single_payload(seed=5)).json()["monteCarlo"]
    b = served.post("/api/backtest/run", json=single_payload(seed=5)).json()["monteCarlo"]
    c = served.post("/api/backtest/run", json=single_payload(seed=6)).json()["monteCarlo"]
    assert a == b and a != c


# ---------------------------------------------------------------------------
# 9. Validation + /strategies
# ---------------------------------------------------------------------------

def test_unknown_range_is_400(served):
    r = served.post("/api/backtest/run", json=single_payload(range="7y"))
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "7y" in detail and "1mo" in detail and "5y" in detail


def test_explicit_start_end_still_supported(served):
    r = served.post("/api/backtest/run", json=single_payload(range="7y", start="2020-01-01", end="2021-12-31"))
    assert r.status_code == 200, r.text


def test_unsupported_interval_is_400(served):
    r = served.post("/api/backtest/run", json=single_payload(interval="2h"))
    assert r.status_code == 400
    assert "interval" in r.json()["detail"].lower()
    r = served.post("/api/backtest/run", json=multi_payload(interval="3m"))
    assert r.status_code == 400


def test_weekly_interval_is_annualized_with_52(served):
    r = served.post("/api/backtest/run", json=single_payload(interval="1wk"))
    assert r.status_code == 200
    assert r.json()["assumptions"]["periodsPerYear"] == 52


def test_strategies_endpoint_has_params(api):
    r = api.get("/api/backtest/strategies")
    assert r.status_code == 200
    by_id = {s["id"]: s for s in r.json()["strategies"]}
    assert by_id["sma_crossover"]["params"] == {"fast_period": 20, "slow_period": 50}
    assert by_id["fibonacci_pullback"]["params"] == {"lookback": 50}
    assert all(s["params"] for s in by_id.values())


def test_heatmap_and_quantstats_share_capital_and_range_validation(served, long_candles, monkeypatch):
    from backend.backtest import main as backtest_main
    from backend.backtest import service

    def fake_fetch(symbol, interval="1d", period="1mo", start=None, end=None, market="us"):
        if not (start and end):
            service.validate_range(period)  # keep the real range validation
        return [dict(c) for c in long_candles]

    monkeypatch.setattr(backtest_main, "fetch_candles", fake_fetch)
    r = served.post("/api/backtest/heatmap", json={"symbol": "TEST", "strategy": "sma_crossover", "range": "7y"})
    assert r.status_code == 400
    r = served.post("/api/backtest/heatmap", json={"symbol": "TEST", "strategy": "sma_crossover", "initial_capital": 0})
    assert r.status_code == 400
    r = served.post("/api/backtest/heatmap", json={
        "symbol": "TEST", "strategy": "sma_crossover", "x_values": [5, 10], "y_values": [20, 30],
    })
    assert r.status_code == 200, r.text
    assert all(v is not None for row in r.json()["values"] for v in row)
    # the heatmap's total return must not depend on the capital, since returns are scale-free
    r2 = served.post("/api/backtest/heatmap", json={
        "symbol": "TEST", "strategy": "sma_crossover", "x_values": [5, 10], "y_values": [20, 30], "initial_capital": 5000,
    })
    assert r2.json()["values"] == r.json()["values"]
    r = served.post("/api/backtest/quantstats-report", json={"symbol": "TEST", "strategy": "sma_crossover", "initial_capital": -5})
    assert r.status_code == 400
