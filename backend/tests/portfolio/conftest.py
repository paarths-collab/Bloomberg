import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.services.market_data import market_service

PREFIXES = ["/api/profile"]


@pytest.fixture(autouse=True)
def prices(monkeypatch):
    """Offline price table. Missing symbols mimic the provider's failure value (0.0)."""
    table = {"AAPL": 100.0, "MSFT": 200.0, "TSLA": 50.0}

    def fake_get_current_price(ticker):
        value = table.get(ticker, 0.0)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(market_service, "get_current_price", fake_get_current_price)

    def fake_get_price_quote(ticker):
        # Delegates at call time so tests that re-patch get_current_price still take effect.
        value = market_service.get_current_price(ticker)
        return {"price": value, "source": "live" if value else None, "as_of": None}

    monkeypatch.setattr(market_service, "get_price_quote", fake_get_price_quote)
    return table


@pytest.fixture
async def new_user(client):
    """Factory: issue a fresh guest identity -> (user_id, auth headers)."""

    async def _new():
        body = (await client.post("/api/auth/guest")).json()
        return body["user_id"], {"Authorization": f"Bearer {body['access_token']}"}

    return _new


@pytest.fixture(params=PREFIXES, ids=["profile-prefix"])
def prefix(request):
    return request.param
