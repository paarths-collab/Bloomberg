"""Guest-token issue/verify, 401 handling, and signing-key configuration."""
import logging
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from backend.auth import security

PROTECTED = "/api/profile/load"  # any require_user route


def _claims(**overrides):
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "guest_" + "a" * 32,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "typ": "guest",
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


async def test_issue_guest_token_and_use_it(client):
    resp = await client.post("/api/auth/guest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user_id"].startswith("guest_") and len(body["user_id"]) == len("guest_") + 32
    assert datetime.fromisoformat(body["expires_at"]) > datetime.now(timezone.utc)

    claims = jwt.decode(body["access_token"], security.get_secret(), algorithms=["HS256"])
    assert claims["sub"] == body["user_id"] and claims["typ"] == "guest"
    assert {"iat", "exp"} <= set(claims)

    ok = await client.get(PROTECTED, headers={"Authorization": f"Bearer {body['access_token']}"})
    assert ok.status_code == 200


async def test_guest_ids_are_unique(client):
    ids = {(await client.post("/api/auth/guest")).json()["user_id"] for _ in range(5)}
    assert len(ids) == 5


async def test_token_ttl_env(client, monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN_TTL_HOURS", "1")
    body = (await client.post("/api/auth/guest")).json()
    delta = datetime.fromisoformat(body["expires_at"]) - datetime.now(timezone.utc)
    assert timedelta(minutes=58) < delta <= timedelta(hours=1)


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": ""},
    {"Authorization": "Bearer"},
    {"Authorization": "Bearer "},
    {"Authorization": "Basic abc123"},
    {"Authorization": "Token abc"},
    {"Authorization": "Bearer not-a-jwt"},
])
async def test_missing_or_malformed_header_is_401(client, headers):
    resp = await client.get(PROTECTED, headers=headers)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_tampered_signature_is_401(client):
    token = (await client.post("/api/auth/guest")).json()["access_token"]
    head, payload, sig = token.split(".")
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    resp = await client.get(PROTECTED, headers={"Authorization": f"Bearer {head}.{payload}.{flipped}"})
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_tampered_payload_is_401(client):
    """Re-using a valid signature with a different subject must fail."""
    victim = jwt.encode(_claims(sub="guest_" + "b" * 32), security.get_secret(), algorithm="HS256")
    other = jwt.encode(_claims(sub="guest_" + "c" * 32), security.get_secret(), algorithm="HS256")
    forged = ".".join([other.split(".")[0], other.split(".")[1], victim.split(".")[2]])
    resp = await client.get(PROTECTED, headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


async def test_wrong_secret_is_401(client):
    token = jwt.encode(_claims(), "x" * 48, algorithm="HS256")
    resp = await client.get(PROTECTED, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_expired_token_is_401(client):
    token, _ = security.create_access_token("guest_" + "d" * 32, ttl=timedelta(seconds=-60))
    resp = await client.get(PROTECTED, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_small_clock_skew_is_tolerated_but_not_more(client):
    just_expired, _ = security.create_access_token("guest_" + "1" * 32, ttl=timedelta(seconds=-10))
    long_expired, _ = security.create_access_token("guest_" + "1" * 32, ttl=timedelta(seconds=-60))
    ok = await client.get(PROTECTED, headers={"Authorization": f"Bearer {just_expired}"})
    assert ok.status_code == 200  # within the 30s leeway
    bad = await client.get(PROTECTED, headers={"Authorization": f"Bearer {long_expired}"})
    assert bad.status_code == 401
    future_iat = jwt.encode(_claims(iat=int((datetime.now(timezone.utc) + timedelta(seconds=10)).timestamp())),
                            security.get_secret(), algorithm="HS256")
    assert (await client.get(PROTECTED, headers={"Authorization": f"Bearer {future_iat}"})).status_code == 200


async def test_alg_none_token_is_rejected(client):
    token = jwt.encode(_claims(), key=None, algorithm="none")
    assert token.endswith(".")
    resp = await client.get(PROTECTED, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_other_hmac_algorithm_is_rejected(client):
    token = jwt.encode(_claims(), security.get_secret(), algorithm="HS512")
    resp = await client.get(PROTECTED, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.parametrize("overrides", [
    {"sub": None},            # missing subject
    {"sub": ""},              # empty subject
    {"exp": None},            # never expires
    {"iat": None},
    {"typ": "admin"},         # wrong token type
    {"typ": None},
])
async def test_incomplete_claims_are_401(client, overrides):
    token = jwt.encode(_claims(**overrides), security.get_secret(), algorithm="HS256")
    resp = await client.get(PROTECTED, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_optional_user_treats_bad_tokens_as_anonymous():
    from fastapi.security import HTTPAuthorizationCredentials

    def creds(value):
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=value)

    good, _ = security.create_access_token("guest_" + "e" * 32)
    assert security.optional_user(None) is None
    assert security.optional_user(creds("garbage")) is None
    assert security.optional_user(creds(jwt.encode(_claims(), key=None, algorithm="none"))) is None
    assert security.optional_user(creds(good)) == "guest_" + "e" * 32


def test_unset_secret_generates_random_secret_and_warns(monkeypatch, caplog):
    monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
    monkeypatch.setattr(security, "_generated_secret", None)
    monkeypatch.setattr(security, "_warned", set())
    with caplog.at_level(logging.WARNING, logger=security.logger.name):
        secret = security.get_secret()
        assert security.get_secret() == secret  # stable within the process
    assert len(secret) >= 48
    warnings = [r for r in caplog.records if "AUTH_SECRET_KEY is not set" in r.getMessage()]
    assert len(warnings) == 1  # warned once, not on every call
    assert "restart" in warnings[0].getMessage()


def test_short_secret_warns(monkeypatch, caplog):
    monkeypatch.setenv("AUTH_SECRET_KEY", "too-short")
    monkeypatch.setattr(security, "_warned", set())
    with caplog.at_level(logging.WARNING, logger=security.logger.name):
        assert security.get_secret() == "too-short"
    assert any("shorter than 32" in r.getMessage() for r in caplog.records)


def test_configured_secret_roundtrip(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET_KEY", "k" * 40)
    token, _ = security.create_access_token("guest_" + "f" * 32)
    assert security.user_from_token(token) == "guest_" + "f" * 32
    monkeypatch.setenv("AUTH_SECRET_KEY", "z" * 40)  # rotated key invalidates old tokens
    assert security.user_from_token(token) is None


def test_anonymous_identity_is_stable_and_not_a_user_id():
    a, b = security.anonymous_identity("s1"), security.anonymous_identity("s2")
    assert a == security.anonymous_identity("s1") and a != b
    assert a.startswith("anon_") and not a.startswith("guest_")
