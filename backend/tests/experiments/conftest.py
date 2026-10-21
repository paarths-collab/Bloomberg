"""Fixtures for the experiment-trial tests. Offline: provider fetches are always monkeypatched."""
import pytest

from backend.backtest import service as bt
from backend.database.connection import SessionLocal, get_engine


@pytest.fixture
async def new_user(client):
    """Factory: issue a fresh guest identity -> auth headers."""

    async def _new():
        body = (await client.post("/api/auth/guest")).json()
        return {"Authorization": f"Bearer {body['access_token']}"}

    return _new


@pytest.fixture
async def user(new_user):
    return await new_user()


@pytest.fixture(autouse=True)
def no_live_fetch(monkeypatch):
    """Any test that forgets to patch the provider fails loudly instead of touching the network."""

    def boom(*args, **kwargs):
        raise AssertionError("live market-data fetch attempted in an offline test")

    monkeypatch.setattr(bt, "_fetch_candles_with_fallback", boom)


@pytest.fixture
def patch_fetch(monkeypatch):
    """patch_fetch(candles) or patch_fetch(exc=...) replaces the backtest service's candle fetcher."""

    def _patch(candles=None, exc=None):
        def fake(*args, **kwargs):
            if exc is not None:
                raise exc
            return candles

        monkeypatch.setattr(bt, "_fetch_candles_with_fallback", fake)

    return _patch


@pytest.fixture
def db():
    SessionLocal.configure(bind=get_engine())
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
