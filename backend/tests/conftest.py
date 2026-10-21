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

import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from backend.auth.rate_limit import reset_guest_limiter
from backend.main import app


@pytest.fixture(autouse=True)
def _reset_guest_limiter():
    reset_guest_limiter()
    yield
    reset_guest_limiter()

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
