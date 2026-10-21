"""`valued_at` as-of timestamp on GET portfolio and portfolio/risk (additive field)."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from backend.services.market_data import market_service


def _parse_utc(value):
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)
    return parsed


def _assert_recent(value):
    parsed = _parse_utc(value)
    assert abs(datetime.now(timezone.utc) - parsed) < timedelta(seconds=10)


async def _buy(client, prefix, hdr, symbol, qty):
    r = await client.post(
        prefix + "/trade", json={"symbol": symbol, "side": "buy", "quantity": qty, "price": 100}, headers=hdr
    )
    assert r.status_code == 200, r.text


async def test_portfolio_has_valued_at(client, new_user, prefix):
    _, hdr = await new_user()
    await _buy(client, prefix, hdr, "AAPL", 2)
    body = (await client.get(prefix + "/portfolio", headers=hdr)).json()
    _assert_recent(body["valued_at"])
    assert body["valuation_complete"] is True
    assert "valued_at" not in body["holdings"][0]  # no invented per-price timestamps


async def test_valued_at_present_for_empty_portfolio(client, new_user, prefix):
    _, hdr = await new_user()
    _assert_recent((await client.get(prefix + "/portfolio", headers=hdr)).json()["valued_at"])


async def test_valued_at_present_when_prices_unavailable(client, new_user, prefix, prices):
    _, hdr = await new_user()
    await _buy(client, prefix, hdr, "AAPL", 2)
    prices["AAPL"] = 0.0  # provider failure value
    resp = await client.get(prefix + "/portfolio", headers=hdr)
    body = resp.json()
    assert resp.status_code == 200 and body["valuation_complete"] is False
    assert body["total_value"] is None and body["holdings"][0]["price_status"] == "unavailable"
    _assert_recent(body["valued_at"])


async def test_valued_at_present_when_price_provider_raises(client, new_user, prefix, prices):
    _, hdr = await new_user()
    await _buy(client, prefix, hdr, "AAPL", 2)
    prices["AAPL"] = RuntimeError("provider down")
    body = (await client.get(prefix + "/portfolio", headers=hdr)).json()
    assert body["valuation_complete"] is False
    _assert_recent(body["valued_at"])


async def test_valued_at_is_taken_after_prices_are_fetched(client, new_user, prefix, monkeypatch):
    _, hdr = await new_user()
    await _buy(client, prefix, hdr, "AAPL", 1)
    before = datetime.now(timezone.utc)
    seen = {}

    def slow_price(symbol):
        seen["fetched_at"] = datetime.now(timezone.utc)
        return 100.0

    monkeypatch.setattr(market_service, "get_current_price", slow_price)
    body = (await client.get(prefix + "/portfolio", headers=hdr)).json()
    valued = _parse_utc(body["valued_at"])
    assert before <= seen["fetched_at"] <= valued


@pytest.fixture
def history(monkeypatch):
    idx = pd.bdate_range(end="2024-06-14", periods=200)
    series = pd.Series(100 * np.cumprod(1 + np.random.default_rng(1).normal(0.0005, 0.01, 200)), index=idx)

    def fake_get_history(symbol, period="1y", interval="1d", **kw):
        return pd.DataFrame({"Close": series}) if symbol in ("SPY", "AAPL") else pd.DataFrame()

    monkeypatch.setattr(market_service, "get_history", fake_get_history)


async def test_risk_has_valued_at_matching_as_of(client, new_user, prefix, history):
    _, hdr = await new_user()
    await _buy(client, prefix, hdr, "AAPL", 5)
    resp = await client.get(prefix + "/portfolio/risk", headers=hdr)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    _assert_recent(body["valued_at"])
    assert body["as_of"] == body["valued_at"]


async def test_risk_valued_at_present_for_empty_portfolio_and_failed_history(client, new_user, prefix, history):
    _, hdr = await new_user()
    empty = (await client.get(prefix + "/portfolio/risk", headers=hdr)).json()
    _assert_recent(empty["valued_at"])
    await _buy(client, prefix, hdr, "MSFT", 1)  # fake history has no MSFT data
    body = (await client.get(prefix + "/portfolio/risk", headers=hdr)).json()
    _assert_recent(body["valued_at"])
    assert body["as_of"] == body["valued_at"]
