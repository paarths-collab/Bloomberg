"""Regression tests for DB-URL exposure, error leakage, CORS parsing and fallback policy."""
import importlib.util
import logging

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.exc import SQLAlchemyError

from backend.database import connection
from backend.main import app, default_origins, parse_cors_origins

SECRET_URL = "postgresql://alice:s3cr3t-pw@db.internal:5432/prod"
LEAKY_TOKENS = ("s3cr3t-pw", "alice", "db.internal")


def _assert_no_leak(text: str):
    """Strict: no credentials and no host (used for client-facing responses)."""
    for token in LEAKY_TOKENS:
        assert token not in text, f"{token!r} leaked"


def _assert_no_credentials(text: str):
    """Logs may show the masked URL (host only), but never username or password."""
    for token in ("s3cr3t-pw", "alice"):
        assert token not in text, f"{token!r} leaked"


# --- /health ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_never_exposes_database_url(client, monkeypatch):
    monkeypatch.setattr(connection, "_active_database_url", SECRET_URL)
    monkeypatch.setattr(connection, "check_db_connection", lambda: False)

    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "version", "database_connected", "database_fallback_active"}
    assert "database_url" not in body
    assert body["status"] == "degraded"
    assert body["database_connected"] is False
    _assert_no_leak(response.text)
    assert "postgresql" not in response.text


# --- check_db_connection logging --------------------------------------------

def test_check_db_connection_failure_does_not_leak_secrets(monkeypatch, capsys, caplog):
    monkeypatch.setattr(connection, "_active_database_url", SECRET_URL)

    def _failing_engine():
        # Simulates a driver error that embeds the raw URL and credentials.
        raise SQLAlchemyError(f"could not connect to {SECRET_URL} as alice with s3cr3t-pw")

    monkeypatch.setattr(connection, "get_engine", _failing_engine)

    with caplog.at_level(logging.DEBUG):
        assert connection.check_db_connection() is False

    captured = capsys.readouterr()
    _assert_no_credentials(captured.out)
    _assert_no_credentials(captured.err)
    _assert_no_credentials(caplog.text)
    assert "Database connection failed" in caplog.text


def test_fallback_log_redacts_reason(monkeypatch, caplog):
    monkeypatch.setattr(connection, "_active_database_url", SECRET_URL)
    monkeypatch.setattr(connection, "_engine", None)
    monkeypatch.setattr(connection, "_fallback_active", False)
    monkeypatch.setattr(connection, "SQLITE_FALLBACK_URL", "sqlite://")

    with caplog.at_level(logging.DEBUG):
        connection.switch_to_sqlite_fallback(reason=f"failed for {SECRET_URL}")

    _assert_no_credentials(caplog.text)
    assert connection.get_database_status()["database_fallback_active"] is True


# --- _safe_db_url -----------------------------------------------------------

def test_safe_db_url_masks_user_and_password():
    masked = connection._safe_db_url(SECRET_URL)
    _assert_no_credentials(masked)
    assert masked == "postgresql://***:***@db.internal:5432/prod"


def test_safe_db_url_masks_password_containing_at_sign():
    masked = connection._safe_db_url("postgresql://bob:p@ss@host.example/db")
    assert "bob" not in masked and "p@ss" not in masked and "ss@" not in masked
    assert masked.endswith("@host.example/db")


def test_safe_db_url_leaves_credentialless_urls_readable():
    assert connection._safe_db_url("postgresql://db.example:5432/prod") == "postgresql://db.example:5432/prod"
    assert connection._safe_db_url("sqlite:///./boomerang.db") == "sqlite:///./boomerang.db"


def test_redact_db_secrets_scrubs_configured_urls(monkeypatch):
    monkeypatch.setattr(connection, "DATABASE_URL", SECRET_URL)
    monkeypatch.setattr(connection, "_active_database_url", SECRET_URL)
    redacted = connection.redact_db_secrets(f"boom {SECRET_URL} user alice pw s3cr3t-pw")
    assert "s3cr3t-pw" not in redacted and "alice" not in redacted


# --- Global exception handler -----------------------------------------------

@pytest.mark.asyncio
async def test_global_handler_returns_generic_message(caplog):
    async def _boom():
        raise RuntimeError(SECRET_URL)

    app.router.add_api_route("/__test_boom", _boom, methods=["GET"])
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with caplog.at_level(logging.ERROR):
                response = await ac.get("/__test_boom")
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/__test_boom"]

    assert response.status_code == 500
    body = response.json()
    assert set(body) == {"status", "message"}
    assert body["status"] == "error"
    _assert_no_leak(response.text)
    # Full exception is still logged server-side.
    assert "Global error at /__test_boom" in caplog.text


@pytest.mark.asyncio
async def test_http_exception_detail_unaffected():
    async def _teapot():
        from fastapi import HTTPException
        raise HTTPException(status_code=418, detail="short and stout")

    app.router.add_api_route("/__test_teapot", _teapot, methods=["GET"])
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/__test_teapot")
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/__test_teapot"]

    assert response.status_code == 418
    assert response.json() == {"detail": "short and stout"}


# --- CORS parsing -----------------------------------------------------------

def test_cors_defaults_kept_when_unset():
    assert parse_cors_origins(None) == default_origins
    assert parse_cors_origins("") == default_origins
    assert parse_cors_origins(" , ,") == default_origins


def test_cors_env_values_merged_and_trimmed():
    origins = parse_cors_origins(" https://app.example.com , ,https://b.example.com/ ,http://localhost:3000")
    assert origins[: len(default_origins)] == default_origins
    assert origins[len(default_origins):] == ["https://app.example.com", "https://b.example.com"]


def test_cors_wildcard_ignored_with_warning(caplog):
    with caplog.at_level(logging.WARNING):
        origins = parse_cors_origins("*, https://app.example.com")
    assert "*" not in origins
    assert "https://app.example.com" in origins
    assert "wildcard" in caplog.text.lower()


def test_cors_parse_does_not_mutate_defaults():
    snapshot = list(default_origins)
    parse_cors_origins("https://x.example.com")
    assert default_origins == snapshot


# --- Fallback default -------------------------------------------------------

def test_env_flag_defaults_off_and_parses_true(monkeypatch):
    monkeypatch.delenv("DB_FALLBACK_TO_SQLITE", raising=False)
    assert connection._env_flag("DB_FALLBACK_TO_SQLITE") is False
    monkeypatch.setenv("DB_FALLBACK_TO_SQLITE", "TRUE")
    assert connection._env_flag("DB_FALLBACK_TO_SQLITE") is True
    monkeypatch.setenv("DB_FALLBACK_TO_SQLITE", "false")
    assert connection._env_flag("DB_FALLBACK_TO_SQLITE") is False


def test_module_level_fallback_flag_defaults_false(monkeypatch):
    """Execute a private copy of the module with the env var unset (live module untouched)."""
    monkeypatch.delenv("DB_FALLBACK_TO_SQLITE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("SQLITE_FALLBACK_URL", "sqlite://")
    spec = importlib.util.spec_from_file_location("_connection_default_probe", connection.__file__)
    probe = importlib.util.module_from_spec(spec)  # intentionally not added to sys.modules
    spec.loader.exec_module(probe)
    assert probe.DB_FALLBACK_TO_SQLITE is False


def test_init_db_reraises_when_fallback_disabled(monkeypatch):
    monkeypatch.setattr(connection, "DB_FALLBACK_TO_SQLITE", False)
    monkeypatch.setattr(connection, "_active_database_url", SECRET_URL)
    switched = []
    monkeypatch.setattr(connection, "switch_to_sqlite_fallback", lambda **kw: switched.append(kw))

    class _FailingMetadata:
        def create_all(self, bind=None):
            raise SQLAlchemyError("down")

    monkeypatch.setattr(connection.Base, "metadata", _FailingMetadata())
    monkeypatch.setattr(connection, "get_engine", lambda: object())

    with pytest.raises(SQLAlchemyError):
        connection.init_db()
    assert switched == []
