"""Validation errors in investor_profile: deliberate messages reach the client, anything else does not."""
import json

from backend.portfolio import investor_profile as inv

SECRET = "secret-token-XYZ"
PROFILE = {"name": "Alice", "age": 30, "risk_tolerance": "moderate"}


async def test_invalid_benchmark_gets_specific_422(client, new_user, prefix):
    _, hdr = await new_user()
    resp = await client.get(prefix + "/portfolio/risk", params={"benchmark": "bad symbol!"}, headers=hdr)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "symbol must be 1-20 characters of A-Z, 0-9, '.', '-', '^' or '='"


async def test_invalid_holding_gets_specific_422(client, new_user, prefix):
    _, hdr = await new_user()
    bad = json.dumps({"AAPL": {"quantity": -1, "avg_price": 1, "total_invested": 1}})
    resp = await client.post(prefix + "/save", json={**PROFILE, "existing_investments": bad}, headers=hdr)
    assert resp.status_code == 422, resp.text
    assert "holding for AAPL: quantity must be a positive number" in resp.text


async def test_malformed_holdings_json_gets_fixed_422_without_parser_text(client, new_user, prefix):
    _, hdr = await new_user()
    resp = await client.post(prefix + "/save", json={**PROFILE, "existing_investments": "{not json"}, headers=hdr)
    assert resp.status_code == 422, resp.text
    assert "existing_investments must be valid holdings JSON" in resp.text
    assert "Expecting" not in resp.text and "char" not in resp.text


async def test_unexpected_exception_in_benchmark_validation_yields_generic_422(
    client, new_user, prefix, monkeypatch
):
    _, hdr = await new_user()

    def boom(value):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(inv, "_normalize_symbol", boom)
    resp = await client.get(prefix + "/portfolio/risk", params={"benchmark": "SPY"}, headers=hdr)
    assert resp.status_code == 422, resp.text
    assert SECRET not in resp.text
    assert resp.json()["detail"] == "benchmark must be a valid ticker symbol"
