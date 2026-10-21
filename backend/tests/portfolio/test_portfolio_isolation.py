"""Authentication and per-user isolation for the paper-portfolio routes (both URL prefixes)."""
import pytest

PROFILE = {"name": "Alice", "age": 30, "risk_tolerance": "aggressive", "primary_goal": "growth"}


async def test_all_routes_require_token(client, prefix):
    for method, path, kwargs in [
        ("post", "/save", {"json": PROFILE}),
        ("get", "/load", {}),
        ("post", "/trade", {"json": {"symbol": "AAPL", "side": "buy", "quantity": 1}}),
        ("get", "/portfolio", {}),
    ]:
        resp = await getattr(client, method)(prefix + path, **kwargs)
        assert resp.status_code == 401, path
        assert resp.headers["www-authenticate"] == "Bearer"


async def test_invalid_token_is_401(client, prefix):
    resp = await client.get(prefix + "/portfolio", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


async def test_users_are_isolated(client, new_user, prefix):
    a_id, a_hdr = await new_user()
    b_id, b_hdr = await new_user()

    assert (await client.post(prefix + "/save", json=PROFILE, headers=a_hdr)).status_code == 200
    buy = await client.post(
        prefix + "/trade", json={"symbol": "AAPL", "side": "buy", "quantity": 5}, headers=a_hdr
    )
    assert buy.status_code == 200, buy.text

    # A sees their own data
    loaded = (await client.get(prefix + "/load", headers=a_hdr)).json()
    assert loaded["status"] == "ok" and loaded["profile"]["name"] == "Alice"
    assert loaded["profile"]["user_id"] == a_id
    pf = (await client.get(prefix + "/portfolio", headers=a_hdr)).json()
    assert [h["symbol"] for h in pf["holdings"]] == ["AAPL"]

    # B sees nothing
    assert (await client.get(prefix + "/load", headers=b_hdr)).json() == {"status": "not_found", "profile": None}
    empty = (await client.get(prefix + "/portfolio", headers=b_hdr)).json()
    assert empty["holdings"] == [] and empty["total_value"] == 0.0 and empty["total_invested"] == 0.0

    # B cannot name A's id on any route
    for resp in [
        await client.get(prefix + "/load", params={"user_id": a_id}, headers=b_hdr),
        await client.get(prefix + "/portfolio", params={"user_id": a_id}, headers=b_hdr),
        await client.post(prefix + "/save", json={**PROFILE, "name": "Mallory", "user_id": a_id}, headers=b_hdr),
        await client.post(
            prefix + "/trade",
            json={"user_id": a_id, "symbol": "AAPL", "side": "sell", "quantity": 5},
            headers=b_hdr,
        ),
    ]:
        assert resp.status_code == 403, resp.text

    # ...and A's data is untouched by those attempts
    assert (await client.get(prefix + "/load", headers=a_hdr)).json()["profile"]["name"] == "Alice"
    pf = (await client.get(prefix + "/portfolio", headers=a_hdr)).json()
    assert pf["holdings"][0]["quantity"] == 5


async def test_matching_user_id_is_accepted_and_legacy_default_is_rejected(client, new_user, prefix):
    a_id, a_hdr = await new_user()
    ok = await client.post(prefix + "/save", json={**PROFILE, "user_id": a_id}, headers=a_hdr)
    assert ok.status_code == 200
    assert (await client.get(prefix + "/load", params={"user_id": a_id}, headers=a_hdr)).status_code == 200
    # The old shared "default" identity can no longer be selected by a client.
    assert (await client.get(prefix + "/load", params={"user_id": "default"}, headers=a_hdr)).status_code == 403


async def test_both_prefixes_share_one_store(client, new_user):
    _, hdr = await new_user()
    await client.post("/api/profile/save", json=PROFILE, headers=hdr)
    await client.post(
        "/api/portfolio/api/investor-profile/trade",
        json={"symbol": "msft", "side": "buy", "quantity": 2}, headers=hdr,
    )
    for p in ("/api/profile", "/api/portfolio/api/investor-profile"):
        assert (await client.get(p + "/load", headers=hdr)).json()["profile"]["name"] == "Alice"
        assert (await client.get(p + "/portfolio", headers=hdr)).json()["holdings"][0]["symbol"] == "MSFT"


async def test_save_does_not_wipe_holdings_and_load_returns_string_timestamps(client, new_user, prefix):
    _, hdr = await new_user()
    await client.post(prefix + "/save", json=PROFILE, headers=hdr)
    await client.post(prefix + "/trade", json={"symbol": "AAPL", "side": "buy", "quantity": 3}, headers=hdr)
    await client.post(prefix + "/save", json={**PROFILE, "name": "Alice2"}, headers=hdr)  # re-save, no holdings

    profile = (await client.get(prefix + "/load", headers=hdr)).json()["profile"]
    assert profile["name"] == "Alice2"
    assert isinstance(profile["created_at"], str) and isinstance(profile["updated_at"], str)
    pf = (await client.get(prefix + "/portfolio", headers=hdr)).json()
    assert pf["holdings"][0]["quantity"] == 3


async def test_save_rejects_malformed_holdings(client, new_user, prefix):
    _, hdr = await new_user()
    for bad in ["free text", "[1,2]", '{"AAPL": {"quantity": -1, "avg_price": 1, "total_invested": 1}}',
                '{"AAPL": 5}', '{"bad symbol!": {"quantity": 1, "avg_price": 1, "total_invested": 1}}']:
        resp = await client.post(prefix + "/save", json={**PROFILE, "existing_investments": bad}, headers=hdr)
        assert resp.status_code == 422, bad


async def test_save_accepts_valid_holdings(client, new_user, prefix):
    _, hdr = await new_user()
    blob = '{"AAPL": {"quantity": 2, "avg_price": 90, "total_invested": 180}}'
    assert (await client.post(prefix + "/save", json={**PROFILE, "existing_investments": blob}, headers=hdr)).status_code == 200
    pf = (await client.get(prefix + "/portfolio", headers=hdr)).json()
    assert pf["holdings"][0]["quantity"] == 2 and pf["total_invested"] == 180


async def test_save_rejects_too_many_holdings_and_oversized_text(client, new_user, prefix):
    import json
    _, hdr = await new_user()
    many = {f"S{i}": {"quantity": 1, "avg_price": 1, "total_invested": 1} for i in range(501)}
    resp = await client.post(prefix + "/save", json={**PROFILE, "existing_investments": json.dumps(many)}, headers=hdr)
    assert resp.status_code == 422
    for field, size in [("name", 201), ("primary_goal", 1001), ("risk_tolerance", 51), ("market", 21)]:
        resp = await client.post(prefix + "/save", json={**PROFILE, field: "x" * size}, headers=hdr)
        assert resp.status_code == 422, field
    ok = {f"S{i}": {"quantity": 1, "avg_price": 1, "total_invested": 1} for i in range(500)}
    assert (await client.post(prefix + "/save", json={**PROFILE, "existing_investments": json.dumps(ok)}, headers=hdr)).status_code == 200


@pytest.mark.parametrize("raw", [
    b'{"monthly_income": 1e999}', b'{"monthly_savings": -1e999}', b'{"monthly_income": NaN}',
    b'{"monthly_income": "5000"}', b'{"monthly_income": true}',
])
async def test_save_rejects_non_finite_and_non_numeric_numbers(client, new_user, prefix, raw):
    _, hdr = await new_user()
    resp = await client.post(prefix + "/save", content=raw, headers={**hdr, "Content-Type": "application/json"})
    assert resp.status_code in (400, 422)
    assert (await client.get(prefix + "/load", headers=hdr)).status_code == 200  # nothing bad was stored


async def test_blank_holdings_keep_stored_holdings(client, new_user, prefix):
    _, hdr = await new_user()
    await client.post(prefix + "/trade", json={"symbol": "AAPL", "side": "buy", "quantity": 2}, headers=hdr)
    for blank in ("", "   ", None):
        assert (await client.post(prefix + "/save", json={**PROFILE, "existing_investments": blank}, headers=hdr)).status_code == 200
    assert (await client.get(prefix + "/portfolio", headers=hdr)).json()["holdings"][0]["quantity"] == 2


def test_every_profile_route_requires_auth_dependency():
    """Reflective guard: no route under either prefix may be added without require_user."""
    from backend.auth.security import require_user
    from backend.main import app

    def depends_on(dependant, target):
        return any(d.call is target or depends_on(d, target) for d in dependant.dependencies)

    expected = {"/save", "/load", "/trade", "/portfolio", "/portfolio/risk"}
    for prefix in ("/api/portfolio/api/investor-profile", "/api/profile"):
        routes = [r for r in app.routes if getattr(r, "path", "").startswith(prefix + "/")]
        assert {r.path[len(prefix):] for r in routes} == expected, prefix
        for r in routes:
            assert depends_on(r.dependant, require_user), f"{r.path} is not protected"


@pytest.mark.parametrize("blob", ["[" * 100000, "{" * 100000, "[1]", "null", "12"])
async def test_save_deeply_nested_or_non_object_holdings_is_422_not_500(client, new_user, prefix, blob):
    _, hdr = await new_user()
    resp = await client.post(prefix + "/save", json={**PROFILE, "existing_investments": blob}, headers=hdr)
    assert resp.status_code == 422


async def test_corrupt_stored_holdings_deeply_nested_is_409_not_500(client, new_user, prefix):
    from sqlalchemy import text
    from backend.database.connection import get_db
    uid, hdr = await new_user()
    await client.post(prefix + "/save", json=PROFILE, headers=hdr)
    db = next(get_db())
    try:
        db.execute(text("UPDATE user_profiles SET existing_investments=:b WHERE user_id=:u"), {"b": "[" * 100000, "u": uid})
        db.commit()
    finally:
        db.close()
    assert (await client.get(prefix + "/portfolio", headers=hdr)).status_code == 409


@pytest.mark.parametrize("field,value", [
    ("age", True), ("age", "30"), ("age", 30.0), ("horizon_years", True), ("horizon_years", "5"), ("horizon_years", 5.5),
])
async def test_age_and_horizon_are_strict_ints(client, new_user, prefix, field, value):
    _, hdr = await new_user()
    resp = await client.post(prefix + "/save", json={**PROFILE, field: value}, headers=hdr)
    assert resp.status_code == 422
    assert (await client.post(prefix + "/save", json={**PROFILE, "age": 30, "horizon_years": 7}, headers=hdr)).status_code == 200
