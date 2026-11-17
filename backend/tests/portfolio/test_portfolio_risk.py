"""GET .../portfolio/risk: auth, per-user holdings, parameters (history fetch is monkeypatched)."""
import numpy as np
import pandas as pd
import pytest

from backend.services.market_data import market_service


def _series(seed, n=200, drift=0.0005):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2024-06-14", periods=n)
    return pd.Series(100 * np.cumprod(1 + rng.normal(drift, 0.01, n)), index=idx)


@pytest.fixture
def history(monkeypatch):
    """Offline get_history; records the (symbol, period) requests."""
    table = {"SPY": _series(1), "AAPL": _series(1), "MSFT": _series(2), "^NSEI": _series(3)}
    calls = []

    def fake_get_history(symbol, period="1y", interval="1d", **kw):
        calls.append((symbol, period))
        series = table.get(symbol)
        if series is None:
            return pd.DataFrame()
        return pd.DataFrame({"Close": series})

    monkeypatch.setattr(market_service, "get_history", fake_get_history)
    fake_get_history.table, fake_get_history.calls = table, calls
    return fake_get_history


async def _buy(client, prefix, hdr, symbol, qty):
    r = await client.post(prefix + "/trade", json={"symbol": symbol, "side": "buy", "quantity": qty, "price": 100}, headers=hdr)
    assert r.status_code == 200, r.text


async def test_risk_requires_token(client, prefix):
    resp = await client.get(prefix + "/portfolio/risk")
    assert resp.status_code == 401 and resp.headers["www-authenticate"] == "Bearer"


async def test_holding_equal_to_benchmark_has_beta_one(client, new_user, prefix, history):
    _, hdr = await new_user()
    await _buy(client, prefix, hdr, "AAPL", 10)  # AAPL series == SPY series
    resp = await client.get(prefix + "/portfolio/risk", headers=hdr)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["benchmark"] == "SPY" and body["period"] == "1y" and body["as_of"]
    assert body["metrics"]["beta"]["status"] == "ok"
    assert body["metrics"]["beta"]["value"] == pytest.approx(1.0, abs=1e-6)
    for name in ("sharpe_ratio", "max_drawdown_pct", "volatility_annualized_pct"):
        assert body["metrics"][name]["status"] == "ok"
    assert body["weights"] == {"AAPL": 1.0}
    assert ("SPY", "1y") in history.calls


async def test_risk_uses_only_the_callers_holdings(client, new_user, prefix, history):
    a_id, a_hdr = await new_user()
    _, b_hdr = await new_user()
    await _buy(client, prefix, a_hdr, "AAPL", 10)
    await _buy(client, prefix, b_hdr, "MSFT", 3)

    history.calls.clear()
    body = (await client.get(prefix + "/portfolio/risk", headers=b_hdr)).json()
    assert body["weights"] == {"MSFT": 1.0}
    assert {s for s, _ in history.calls} == {"MSFT", "SPY"}  # never AAPL

    denied = await client.get(prefix + "/portfolio/risk", params={"user_id": a_id}, headers=b_hdr)
    assert denied.status_code == 403


async def test_empty_portfolio_returns_unavailable_metrics(client, new_user, prefix, history):
    _, hdr = await new_user()
    resp = await client.get(prefix + "/portfolio/risk", headers=hdr)
    assert resp.status_code == 200
    metrics = resp.json()["metrics"]
    assert set(metrics) == {"beta", "sharpe_ratio", "max_drawdown_pct", "volatility_annualized_pct"}
    assert all(m["status"] == "unavailable" and m["value"] is None and "no holdings" in m["reason"] for m in metrics.values())
    assert history.calls == []  # nothing to fetch


async def test_missing_history_is_reported_not_faked(client, new_user, prefix, history):
    _, hdr = await new_user()
    await _buy(client, prefix, hdr, "TSLA", 1)  # no history in the table
    metrics = (await client.get(prefix + "/portfolio/risk", headers=hdr)).json()["metrics"]
    assert all(m["status"] == "unavailable" and "TSLA" in m["reason"] for m in metrics.values())


@pytest.mark.parametrize("params", [
    {"period": "10y"}, {"period": "max"}, {"period": ""},
    {"risk_free_rate": "-0.01"}, {"risk_free_rate": "0.5"}, {"risk_free_rate": "nan"}, {"risk_free_rate": "inf"},
    {"benchmark": "bad symbol!"},
])
async def test_invalid_parameters_are_rejected(client, new_user, prefix, history, params):
    _, hdr = await new_user()
    resp = await client.get(prefix + "/portfolio/risk", params=params, headers=hdr)
    assert resp.status_code in (400, 422)


async def test_period_benchmark_and_rate_are_applied(client, new_user, prefix, history):
    _, hdr = await new_user()
    await _buy(client, prefix, hdr, "MSFT", 1)
    body = (await client.get(
        prefix + "/portfolio/risk", params={"period": "2y", "benchmark": "aapl", "risk_free_rate": "0.04"}, headers=hdr
    )).json()
    assert body["period"] == "2y" and body["benchmark"] == "AAPL" and body["risk_free_rate"] == 0.04
    assert {("MSFT", "2y"), ("AAPL", "2y")} <= set(history.calls)


async def test_india_profile_defaults_to_nsei(client, new_user, prefix, history):
    _, hdr = await new_user()
    await client.post(prefix + "/save", json={"name": "Asha", "market": "India"}, headers=hdr)
    await _buy(client, prefix, hdr, "MSFT", 1)
    body = (await client.get(prefix + "/portfolio/risk", headers=hdr)).json()
    assert body["benchmark"] == "^NSEI"


async def test_too_many_holdings_for_risk_is_422_without_fetching(client, new_user, prefix, history):
    import json
    from backend.portfolio import investor_profile as inv
    _, hdr = await new_user()
    n = inv.MAX_RISK_SYMBOLS + 1
    blob = json.dumps({f"S{i}": {"quantity": 1, "avg_price": 1, "total_invested": 1} for i in range(n)})
    assert (await client.post(prefix + "/save", json={"name": "x", "existing_investments": blob}, headers=hdr)).status_code == 200
    resp = await client.get(prefix + "/portfolio/risk", headers=hdr)
    assert resp.status_code == 422 and str(inv.MAX_RISK_SYMBOLS) in resp.json()["detail"]
    assert history.calls == []


async def test_db_session_released_before_price_fetch(client, new_user, prefix, history, monkeypatch):
    from backend.portfolio import investor_profile as inv
    _, hdr = await new_user()
    await _buy(client, prefix, hdr, "AAPL", 1)
    events = []
    real_load = inv.load_price_history
    monkeypatch.setattr(inv, "load_price_history", lambda *a, **k: (events.append("fetch"), real_load(*a, **k))[1])
    from sqlalchemy.orm import Session
    real_close = Session.close
    monkeypatch.setattr(Session, "close", lambda self: (events.append("close"), real_close(self))[1])
    assert (await client.get(prefix + "/portfolio/risk", headers=hdr)).status_code == 200
    assert events.index("close") < events.index("fetch")
