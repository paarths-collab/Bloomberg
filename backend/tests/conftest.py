import os
import tempfile

# Isolate the test run from the tracked ./boomerang.db. This MUST run before
# `backend.main` (and therefore the DB engine) is imported.
_test_db_url = os.environ.get("TEST_DATABASE_URL") or (
    "sqlite:///" + os.path.join(tempfile.mkdtemp(prefix="boomerang-test-"), "test.db")
)
os.environ["DATABASE_URL"] = _test_db_url
os.environ["SQLITE_FALLBACK_URL"] = _test_db_url

import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from backend.main import app

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
