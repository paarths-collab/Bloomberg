import os
import tempfile

# Isolate the test run from the tracked ./boomerang.db. This MUST run before
# `backend.main` (and therefore the DB engine) is imported.
_test_db_url = os.environ.get("TEST_DATABASE_URL") or (
    "sqlite:///" + os.path.join(tempfile.mkdtemp(prefix="boomerang-test-"), "test.db")
)
os.environ["DATABASE_URL"] = _test_db_url
os.environ["SQLITE_FALLBACK_URL"] = _test_db_url

# Production defaults throttle POST /api/auth/guest; most tests mint many tokens from one test
# client host, so disable the limiter here. Limiter tests enable it explicitly via monkeypatch.
os.environ.setdefault("AUTH_GUEST_RATE_LIMIT", "0")
os.environ.setdefault("AUTH_GUEST_GLOBAL_LIMIT", "0")
os.environ.setdefault("AUTH_REFRESH_RATE_LIMIT", "0")
os.environ.setdefault("AUTH_REFRESH_GLOBAL_LIMIT", "0")
# Heavy-route throttling (rate + concurrency) and the live-socket caps are off for the general suite;
# the abuse-protection tests enable them explicitly via monkeypatch.
os.environ.setdefault("HEAVY_RATE_LIMIT", "0")
os.environ.setdefault("HEAVY_MAX_CONCURRENCY", "0")
os.environ.setdefault("WS_MAX_CONNECTIONS", "0")

import pytest
import asyncio
import socket
from httpx import AsyncClient, ASGITransport
from backend.auth.rate_limit import reset_guest_limiter
from backend.common.abuse_protection import reset_abuse_protection
from backend.main import app


@pytest.fixture(autouse=True)
def _offline_providers(monkeypatch):
    """Smoke tests must not construct native search clients or reach live APIs.

    Provider-specific regression tests can replace these stubs with their own fakes.
    HTTP ASGI clients and SQLite do not need sockets.
    """
    from backend.news.service import NewsService
    from backend.services.market_data import market_service
    monkeypatch.setattr(NewsService, "search_news", lambda *a, **k: [])
    monkeypatch.setattr(market_service, "get_market_overview", lambda: {"indices": {}})

    def no_network(*args, **kwargs):
        raise OSError("Live network is disabled in backend tests")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)


@pytest.fixture(autouse=True)
def _reset_guest_limiter():
    reset_guest_limiter()
    reset_abuse_protection()
    yield
    reset_guest_limiter()
    reset_abuse_protection()

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
