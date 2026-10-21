"""Trade validation, round trips, optimistic-concurrency (lost update) and valuation."""
import json

import pytest
from sqlalchemy import text

from backend.database.connection import get_db
from backend.portfolio import investor_profile as inv

NAN_BODIES = [
    b'{"symbol":"AAPL","side":"buy","quantity":1,"price":NaN}',
    b'{"symbol":"AAPL","side":"buy","quantity":1,"price":Infinity}',
    b'{"symbol":"AAPL","side":"buy","quantity":NaN}',
    b'{"symbol":"AAPL","side":"buy","amount":Infinity}',
    b'{"symbol":"AAPL","side":"buy","quantity":1e999}',
    b'{"symbol":"AAPL","side":"buy","quantity":-1e999}',
    b'{"symbol":"AAPL","side":"buy","amount":1e999}',
    b'{"symbol":"AAPL","side":"buy","quantity":1,"price":1e999}',
    b'{"symbol":"AAPL","side":"buy","quantity":"5"}',     # numeric strings are not numbers
    b'{"symbol":"AAPL","side":"buy","quantity":true}',
    b'{"symbol":"AAPL","side":"buy","quantity":1,"price":"100"}',
    b'{"symbol":"AAPL","side":"buy","amount":"100"}',
]


async def _trade(client, prefix, hdr, **body):
    body.setdefault("side", "buy")
    return await client.post(prefix + "/trade", json=body, headers=hdr)


async def _portfolio(client, prefix, hdr):
    return (await client.get(prefix + "/portfolio", headers=hdr)).json()


# ---- validation -------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {"symbol": "AAPL", "quantity": 1, "price": -5},
    {"symbol": "AAPL", "quantity": 1, "price": 0},
    {"symbol": "AAPL", "quantity": -1},
    {"symbol": "AAPL", "amount": -100},
    {"symbol": "AAPL", "quantity": 0},                    # neither quantity nor amount
    {"symbol": "AAPL", "quantity": 0, "amount": 0},
    {"symbol": "", "quantity": 1},
    {"symbol": "   ", "quantity": 1},
    {"symbol": "AA PL", "quantity": 1},
    {"symbol": "AAPL;DROP TABLE", "quantity": 1},
    {"symbol": "A" * 21, "quantity": 1},
    {"symbol": "AAPL", "quantity": 1, "side": "hold"},
    {"quantity": 1},                                       # symbol missing
    {"symbol": "AAPL", "quantity": 1e308, "price": 1e308},  # overflows to inf
])
async def test_invalid_trades_are_rejected(client, new_user, prefix, body):
    _, hdr = await new_user()
    resp = await _trade(client, prefix, hdr, **body)
    assert resp.status_code in (400, 422), resp.text
    assert (await _portfolio(client, prefix, hdr))["holdings"] == []


@pytest.mark.parametrize("raw", NAN_BODIES)
async def test_nan_and_inf_are_rejected(client, new_user, prefix, raw):
    _, hdr = await new_user()
    resp = await client.post(
        prefix + "/trade", content=raw, headers={**hdr, "Content-Type": "application/json"}
    )
    assert resp.status_code in (400, 422)


async def test_sell_more_than_held_and_unowned_symbol(client, new_user, prefix):
    _, hdr = await new_user()
    assert (await _trade(client, prefix, hdr, symbol="AAPL", quantity=2)).status_code == 200
    over = await _trade(client, prefix, hdr, symbol="AAPL", side="sell", quantity=2.5)
    assert over.status_code == 400 and "Not enough shares" in over.json()["detail"]
    assert (await _trade(client, prefix, hdr, symbol="MSFT", side="sell", quantity=1)).status_code == 400
    assert (await _portfolio(client, prefix, hdr))["holdings"][0]["quantity"] == 2


async def test_no_live_price_is_400(client, new_user, prefix):
    _, hdr = await new_user()
    resp = await _trade(client, prefix, hdr, symbol="NOPRICE", quantity=1)
    assert resp.status_code == 400 and "Could not fetch price" in resp.json()["detail"]
    # explicit price needs no live quote
    assert (await _trade(client, prefix, hdr, symbol="NOPRICE", quantity=1, price=10)).status_code == 200


async def test_provider_exception_is_400_not_500(client, new_user, prefix, prices):
    _, hdr = await new_user()
    prices["AAPL"] = RuntimeError("provider down")
    assert (await _trade(client, prefix, hdr, symbol="AAPL", quantity=1)).status_code == 400


# ---- round trips ------------------------------------------------------------

async def test_buy_sell_round_trip_persists(client, new_user, prefix):
    _, hdr = await new_user()
    # symbol normalisation: lower case + whitespace
    r1 = await _trade(client, prefix, hdr, symbol=" aapl ", quantity=10, price=100)
    assert r1.status_code == 200, r1.text
    assert r1.json()["portfolio"]["AAPL"]["quantity"] == 10
    r2 = await _trade(client, prefix, hdr, symbol="AAPL", amount=1100, price=110)  # 10 more shares
    assert r2.status_code == 200
    h = r2.json()["portfolio"]["AAPL"]
    assert h["quantity"] == pytest.approx(20)
    assert h["total_invested"] == pytest.approx(2100)
    assert h["avg_price"] == pytest.approx(105)

    r3 = await _trade(client, prefix, hdr, symbol="AAPL", side="sell", quantity=5, price=120)
    assert r3.status_code == 200
    h = r3.json()["portfolio"]["AAPL"]
    assert h["quantity"] == pytest.approx(15)
    assert h["total_invested"] == pytest.approx(2100 * 15 / 20)
    assert h["avg_price"] == pytest.approx(105)  # moving average unchanged by sells

    # persisted: a fresh read reflects it
    pf = await _portfolio(client, prefix, hdr)
    [holding] = pf["holdings"]
    assert holding["quantity"] == pytest.approx(15)
    assert holding["total_invested"] == pytest.approx(1575)

    # selling everything removes the position
    r4 = await _trade(client, prefix, hdr, symbol="AAPL", side="sell", quantity=15, price=120)
    assert r4.status_code == 200 and r4.json()["portfolio"] == {}
    assert (await _portfolio(client, prefix, hdr))["holdings"] == []


async def test_live_price_used_when_no_price_given(client, new_user, prefix):
    _, hdr = await new_user()
    resp = await _trade(client, prefix, hdr, symbol="MSFT", amount=1000)  # live price 200 -> 5 shares
    assert resp.status_code == 200
    assert resp.json()["portfolio"]["MSFT"]["quantity"] == pytest.approx(5)
    assert resp.json()["price"] == 200


async def test_sell_by_amount_can_close_position_despite_float_error(client, new_user, prefix):
    _, hdr = await new_user()
    await _trade(client, prefix, hdr, symbol="AAPL", amount=100, price=3)  # 33.333... shares
    resp = await _trade(client, prefix, hdr, symbol="AAPL", side="sell", amount=100, price=3)
    assert resp.status_code == 200 and resp.json()["portfolio"] == {}


async def test_first_trade_creates_profile_row_once(client, new_user, prefix):
    _, hdr = await new_user()
    assert (await client.get(prefix + "/load", headers=hdr)).json()["status"] == "not_found"
    assert (await _trade(client, prefix, hdr, symbol="AAPL", quantity=1)).status_code == 200
    assert (await _trade(client, prefix, hdr, symbol="MSFT", quantity=1)).status_code == 200
    assert (await client.get(prefix + "/load", headers=hdr)).json()["status"] == "ok"
    assert len((await _portfolio(client, prefix, hdr))["holdings"]) == 2


def test_profile_row_creation_is_idempotent_under_races():
    """A duplicate insert (lost race on UNIQUE user_id) is swallowed, not a 500."""
    db = next(get_db())
    try:
        uid = "guest_race_" + "0" * 20
        inv._ensure_profile_row(db, uid)
        inv._ensure_profile_row(db, uid)  # IntegrityError path
        count = db.execute(text("SELECT COUNT(*) FROM user_profiles WHERE user_id=:u"), {"u": uid}).scalar()
        assert count == 1
    finally:
        db.close()


# ---- lost updates -----------------------------------------------------------

def _competing_writer(uid, symbol, qty):
    """Commit a rival trade through a separate session (as a concurrent request would)."""
    other = next(get_db())
    try:
        blob = other.execute(
            text("SELECT existing_investments FROM user_profiles WHERE user_id=:u"), {"u": uid}
        ).scalar()
        holdings = json.loads(blob) if blob else {}
        holdings[symbol] = {"quantity": qty, "avg_price": 10.0, "total_invested": qty * 10.0}
        other.execute(
            text("UPDATE user_profiles SET existing_investments=:b WHERE user_id=:u"),
            {"b": json.dumps(holdings), "u": uid},
        )
        other.commit()
    finally:
        other.close()


async def test_concurrent_trade_between_read_and_write_is_not_lost(client, new_user, prefix, monkeypatch):
    uid, hdr = await new_user()
    await _trade(client, prefix, hdr, symbol="AAPL", quantity=1, price=100)  # row exists with a blob

    real_read = inv._read_holdings_blob
    calls = {"n": 0}

    def racing_read(db, user_id):
        result = real_read(db, user_id)  # trade #1 has now SELECTed...
        calls["n"] += 1
        if calls["n"] == 1:
            _competing_writer(user_id, "MSFT", 7)  # ...trade #2 commits before trade #1's UPDATE
        return result

    monkeypatch.setattr(inv, "_read_holdings_blob", racing_read)
    resp = await _trade(client, prefix, hdr, symbol="TSLA", quantity=2, price=50)
    assert resp.status_code == 200, resp.text
    assert calls["n"] >= 2  # it detected the conflict and re-read

    monkeypatch.setattr(inv, "_read_holdings_blob", real_read)
    held = {h["symbol"]: h["quantity"] for h in (await _portfolio(client, prefix, hdr))["holdings"]}
    assert held == {"AAPL": 1, "MSFT": 7, "TSLA": 2}


async def test_lost_update_on_null_blob_first_write(client, new_user, prefix, monkeypatch):
    """CAS must also work when the stored value is NULL (profile saved, never traded)."""
    uid, hdr = await new_user()
    await client.post(prefix + "/save", json={"name": "N"}, headers=hdr)

    real_read = inv._read_holdings_blob
    calls = {"n": 0}

    def racing_read(db, user_id):
        result = real_read(db, user_id)
        calls["n"] += 1
        if calls["n"] == 1:
            assert result == (True, None)
            _competing_writer(user_id, "MSFT", 3)
        return result

    monkeypatch.setattr(inv, "_read_holdings_blob", racing_read)
    assert (await _trade(client, prefix, hdr, symbol="AAPL", quantity=1, price=100)).status_code == 200
    monkeypatch.setattr(inv, "_read_holdings_blob", real_read)
    held = {h["symbol"] for h in (await _portfolio(client, prefix, hdr))["holdings"]}
    assert held == {"AAPL", "MSFT"}


async def test_persistent_contention_gives_409(client, new_user, prefix, monkeypatch):
    uid, hdr = await new_user()
    await _trade(client, prefix, hdr, symbol="AAPL", quantity=1, price=100)
    real_read = inv._read_holdings_blob
    calls = {"n": 0}

    def always_racing(db, user_id):
        result = real_read(db, user_id)
        calls["n"] += 1
        _competing_writer(user_id, "X" + str(calls["n"]), calls["n"])
        return result

    monkeypatch.setattr(inv, "_read_holdings_blob", always_racing)
    resp = await _trade(client, prefix, hdr, symbol="TSLA", quantity=1, price=50)
    assert resp.status_code == 409
    assert calls["n"] == inv.MAX_TRADE_ATTEMPTS
    monkeypatch.setattr(inv, "_read_holdings_blob", real_read)
    symbols = {h["symbol"] for h in (await _portfolio(client, prefix, hdr))["holdings"]}
    assert "TSLA" not in symbols  # the failed trade left no partial write


# ---- valuation --------------------------------------------------------------

async def test_valuation_all_priced(client, new_user, prefix):
    _, hdr = await new_user()
    await _trade(client, prefix, hdr, symbol="AAPL", quantity=10, price=80)    # cost 800, now 100 -> 1000
    await _trade(client, prefix, hdr, symbol="MSFT", quantity=5, price=250)    # cost 1250, now 200 -> 1000
    pf = await _portfolio(client, prefix, hdr)
    assert pf["valuation_complete"] is True and pf["unpriced_symbols"] == []
    assert pf["total_invested"] == pytest.approx(2050)
    assert pf["total_value"] == pytest.approx(2000)
    assert pf["total_pl"] == pytest.approx(-50)
    assert pf["total_pl_pct"] == pytest.approx(-50 / 2050 * 100)
    by_symbol = {h["symbol"]: h for h in pf["holdings"]}
    aapl = by_symbol["AAPL"]
    assert aapl["price_status"] == "live" and aapl["current_price"] == 100
    assert aapl["current_value"] == pytest.approx(1000) and aapl["pl"] == pytest.approx(200)
    assert aapl["pl_pct"] == pytest.approx(25) and aapl["avg_price"] == pytest.approx(80)
    assert by_symbol["MSFT"]["pl"] == pytest.approx(-250)


@pytest.mark.parametrize("failure", [0.0, None, RuntimeError("boom"), float("nan")])
async def test_valuation_never_substitutes_cost_basis(client, new_user, prefix, prices, failure):
    _, hdr = await new_user()
    await _trade(client, prefix, hdr, symbol="AAPL", quantity=10, price=80)
    await _trade(client, prefix, hdr, symbol="MSFT", quantity=5, price=250)
    prices["MSFT"] = failure

    pf = await _portfolio(client, prefix, hdr)
    assert pf["valuation_complete"] is False
    assert pf["unpriced_symbols"] == ["MSFT"]
    assert pf["total_invested"] == pytest.approx(2050)
    assert pf["total_value"] is None and pf["total_pl"] is None and pf["total_pl_pct"] is None

    by_symbol = {h["symbol"]: h for h in pf["holdings"]}
    msft = by_symbol["MSFT"]
    assert msft["price_status"] == "unavailable"
    assert msft["current_price"] is None and msft["current_value"] is None
    assert msft["pl"] is None and msft["pl_pct"] is None
    assert msft["quantity"] == 5 and msft["avg_price"] == pytest.approx(250)
    assert by_symbol["AAPL"]["price_status"] == "live"
    assert by_symbol["AAPL"]["current_value"] == pytest.approx(1000)
    assert pf["holdings"][-1]["symbol"] == "MSFT"  # unpriced sorted last


async def test_empty_portfolio_shape(client, new_user, prefix):
    _, hdr = await new_user()
    pf = await _portfolio(client, prefix, hdr)
    assert pf.pop("valued_at")  # additive as-of timestamp, covered in test_valued_at.py
    assert pf == {
        "holdings": [], "total_invested": 0.0, "total_value": 0.0, "total_pl": 0.0,
        "total_pl_pct": 0, "valuation_complete": True, "unpriced_symbols": [],
    }
    assert "pairtfolio" not in pf


async def test_sell_clamp_keeps_amount_consistent_with_quantity(client, new_user, prefix):
    _, hdr = await new_user()
    await _trade(client, prefix, hdr, symbol="AAPL", quantity=1, price=3)
    # amount sized to slightly more than held shares (float error scale) is clamped to the holding
    resp = await _trade(client, prefix, hdr, symbol="AAPL", side="sell", amount=3 * (1 + 5e-10), price=3)
    body = resp.json()
    assert resp.status_code == 200 and body["quantity"] == 1
    assert body["amount"] == pytest.approx(body["quantity"] * body["price"], rel=0, abs=1e-12)


@pytest.mark.parametrize("body", [
    {"symbol": "AAPL", "amount": 1e-320, "price": 100},     # quantity underflows to dust
    {"symbol": "AAPL", "quantity": 1e-9, "price": 100},
])
async def test_dust_quantity_trades_are_rejected(client, new_user, prefix, body):
    _, hdr = await new_user()
    resp = await _trade(client, prefix, hdr, **body)
    assert resp.status_code == 400 and "minimum" in resp.json()["detail"]
    assert (await _portfolio(client, prefix, hdr))["holdings"] == []
