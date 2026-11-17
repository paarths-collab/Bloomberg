"""Fetch errors must never look like empty holdings (both URL prefixes).

A failure to read the user's stored data must produce an error status with a generic body,
never HTTP 200 with an empty holdings list or a "not_found"/no-profile answer. A missing live
price must mark only that holding as ``price_status: "unavailable"``.
"""
import pytest
from sqlalchemy.exc import OperationalError

from backend.database.connection import get_db
from backend.main import app
from backend.services.market_data import market_service

PROFILE = {"name": "Alice", "age": 30, "risk_tolerance": "aggressive", "primary_goal": "growth"}
SECRET = "hunter2-secret-host-db01"


class _FailingUserProfilesSession:
    """Wraps the real session; every SELECT against user_profiles raises OperationalError."""

    def __init__(self, inner):
        self._inner = inner

    def execute(self, statement, *args, **kwargs):
        sql = str(statement)
        if "user_profiles" in sql and sql.lstrip().upper().startswith("SELECT"):
            raise OperationalError(sql, {}, Exception(f"connection refused password={SECRET}"))
        return self._inner.execute(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.fixture
def failing_db():
    def _override():
        gen = get_db()
        session = next(gen)
        try:
            yield _FailingUserProfilesSession(session)
        finally:
            gen.close()

    app.dependency_overrides[get_db] = _override
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


def _assert_generic_error(resp):
    assert resp.status_code >= 500, resp.text
    body = resp.text
    assert SECRET not in body and "connection refused" not in body
    assert "holdings" not in resp.json()
    assert "profile" not in resp.json()


async def test_get_portfolio_db_error_is_5xx_not_empty(client, new_user, prefix, failing_db):
    _, hdr = await new_user()
    resp = await client.get(prefix + "/portfolio", headers=hdr)
    _assert_generic_error(resp)


async def test_get_load_db_error_is_5xx_not_not_found(client, new_user, prefix, failing_db):
    _, hdr = await new_user()
    resp = await client.get(prefix + "/load", headers=hdr)
    _assert_generic_error(resp)


async def test_get_risk_db_error_is_5xx_not_empty(client, new_user, prefix, failing_db):
    _, hdr = await new_user()
    resp = await client.get(prefix + "/portfolio/risk", headers=hdr)
    _assert_generic_error(resp)


async def test_missing_price_marks_only_that_holding_unavailable(client, new_user, prefix, monkeypatch):
    _, hdr = await new_user()
    assert (await client.post(prefix + "/save", json=PROFILE, headers=hdr)).status_code == 200
    for symbol in ("AAPL", "MSFT"):
        buy = await client.post(prefix + "/trade", json={"symbol": symbol, "side": "buy", "quantity": 2}, headers=hdr)
        assert buy.status_code == 200, buy.text

    real_price = market_service.get_current_price

    def flaky_price(ticker):
        if ticker == "MSFT":
            raise RuntimeError("upstream price provider timed out")
        return real_price(ticker)

    monkeypatch.setattr(market_service, "get_current_price", flaky_price)

    resp = await client.get(prefix + "/portfolio", headers=hdr)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_symbol = {h["symbol"]: h for h in body["holdings"]}
    assert set(by_symbol) == {"AAPL", "MSFT"}

    assert by_symbol["AAPL"]["price_status"] == "live"
    assert by_symbol["AAPL"]["current_price"] == 100.0

    msft = by_symbol["MSFT"]
    assert msft["price_status"] == "unavailable"
    assert msft["quantity"] == 2 and msft["total_invested"] == 400.0
    assert msft["current_price"] is None
    assert msft["current_value"] is None
    assert msft["pl"] is None
    assert msft["pl_pct"] is None

    assert body["valuation_complete"] is False
    assert body["unpriced_symbols"] == ["MSFT"]
    assert body["total_value"] is None and body["total_pl"] is None


async def test_brand_new_user_gets_explicit_no_profile_response(client, new_user, prefix):
    _, hdr = await new_user()

    load = await client.get(prefix + "/load", headers=hdr)
    assert load.status_code == 200
    assert load.json() == {"status": "not_found", "profile": None}

    pf = await client.get(prefix + "/portfolio", headers=hdr)
    assert pf.status_code == 200
    body = pf.json()
    assert body["holdings"] == [] and body["valuation_complete"] is True and body["unpriced_symbols"] == []
    assert body["total_value"] == 0.0 and body["total_invested"] == 0.0


async def test_corrupt_stored_holdings_409_has_no_exception_text(client, new_user, prefix, monkeypatch):
    _, hdr = await new_user()
    assert (await client.post(prefix + "/save", json=PROFILE, headers=hdr)).status_code == 200

    from backend.portfolio import investor_profile

    def corrupt_blob(db, user_id):
        return True, '{"AAPL": {"quantity": -1, "avg_price": 1, "total_invested": 1}}'

    monkeypatch.setattr(investor_profile, "_read_holdings_blob", corrupt_blob)

    resp = await client.get(prefix + "/portfolio", headers=hdr)
    assert resp.status_code == 409, resp.text
    assert resp.json() == {"detail": "Stored holdings are not valid. Re-save the profile with valid holdings."}
    assert "quantity" not in resp.text and "AAPL" not in resp.text


async def test_risk_computation_failure_is_generic_500(client, new_user, prefix, monkeypatch):
    _, hdr = await new_user()
    assert (await client.post(prefix + "/save", json=PROFILE, headers=hdr)).status_code == 200

    from backend.portfolio import investor_profile

    def boom(*args, **kwargs):
        raise RuntimeError(f"numpy blew up password={SECRET}")

    monkeypatch.setattr(investor_profile, "compute_portfolio_risk", boom)
    monkeypatch.setattr(investor_profile, "load_price_history", lambda symbols, period: {})

    resp = await client.get(prefix + "/portfolio/risk", headers=hdr)
    assert resp.status_code == 500, resp.text
    assert resp.json() == {"detail": "Risk computation failed"}
    assert SECRET not in resp.text and "numpy" not in resp.text
