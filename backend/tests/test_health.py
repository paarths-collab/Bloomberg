import pytest

@pytest.mark.asyncio
async def test_main_health(client):
    """Test retrieving health status."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_main_health_reports_only_safe_fields(client):
    """/health must expose exactly the safe status fields."""
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "version", "database_connected", "database_fallback_active"}
    assert isinstance(body["database_connected"], bool)
    assert isinstance(body["database_fallback_active"], bool)
    assert body["status"] == ("ok" if body["database_connected"] else "degraded")


@pytest.mark.asyncio
async def test_main_health_degraded_when_database_down(client, monkeypatch):
    """A failing DB yields HTTP 200 with status "degraded" (Render health check stays green)."""
    from backend.database import connection

    def _boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(connection, "get_engine", _boom)
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database_connected"] is False
