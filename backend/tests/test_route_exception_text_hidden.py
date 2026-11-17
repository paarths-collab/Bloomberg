"""
Behavioural companion to test_no_exception_leaks.py: for representative routes of every router
cleaned up in the "no exception text in responses" change, the inner function the route calls is
made to raise RuntimeError("secret-token-XYZ") and the response body must not contain it.

Offline: nothing here reaches a market-data, LLM or news provider.
"""
import types

import pytest
import requests
from fastapi.testclient import TestClient

from backend.main import app as main_app

SECRET = "secret-token-XYZ"


def _boom(*args, **kwargs):
    raise RuntimeError(SECRET)


async def _aboom(*args, **kwargs):
    raise RuntimeError(SECRET)


@pytest.fixture
def client():
    with TestClient(main_app) as c:
        yield c


def _assert_hidden(response, status, expected=None):
    assert response.status_code == status, response.text
    assert SECRET not in response.text
    if expected is not None:
        assert response.json() == expected


# --------------------------------------------------------------------------- research

def test_research_analyze_hides_exception_text(client, monkeypatch):
    from backend.research import main as research_main

    monkeypatch.setattr(research_main, "generate_research_report", _boom)
    r = client.post("/api/research/analyze", json={"symbol": "AAPL"})
    _assert_hidden(r, 500, {"detail": "Research request failed"})


def test_research_analyze_keeps_deliberate_400(client, monkeypatch):
    """A fixed, service-defined message ("Stock not found") is still a 400 with that message."""
    from backend.research import main as research_main

    monkeypatch.setattr(research_main, "generate_research_report", lambda symbol: {"error": "Stock not found"})
    r = client.post("/api/research/analyze", json={"symbol": "ZZZZ"})
    _assert_hidden(r, 400, {"detail": "Stock not found"})


def test_research_report_hides_exception_text(client, monkeypatch):
    from backend.research import main as research_main

    monkeypatch.setattr(research_main.market_service, "get_history", _boom)
    r = client.post("/api/research/report", json={"symbol": "AAPL"})
    _assert_hidden(r, 500, {"detail": "QuantStats report generation failed"})


def test_research_service_data_fetch_error_is_generic(monkeypatch):
    from backend.research import service

    monkeypatch.setattr(service, "get_fundamentals_summary", _boom)
    assert service.generate_research_report("AAPL") == {"error": "Data fetch failed"}


# --------------------------------------------------------------------------- screener

def test_screener_scan_hides_exception_text(client, monkeypatch):
    from backend.screener import main as screener_main

    monkeypatch.setattr(screener_main._SERVICE, "run_scan", _boom)
    r = client.get("/api/screener/scan")
    _assert_hidden(r, 500, {"detail": "Screener request failed"})


# --------------------------------------------------------------------------- dashboard

def test_dashboard_sentiment_hides_exception_text(client, monkeypatch):
    from backend.dashboard import main as dashboard_main

    monkeypatch.setattr(dashboard_main, "get_market_sentiment", _boom)
    r = client.post("/api/dashboard/sentiment", json={"message": "feeling nervous"})
    _assert_hidden(r, 500, {"detail": "Dashboard sentiment request failed"})


def test_dashboard_crowd_insight_hides_exception_text(client, monkeypatch):
    from backend.dashboard import main as dashboard_main

    monkeypatch.setattr(dashboard_main, "analyze_crowd_insight", _boom)
    r = client.post("/api/dashboard/crowd-insight", json={"ticker": "AAPL"})
    _assert_hidden(r, 500, {"detail": "Crowd insight request failed"})


def test_dashboard_signal_components_hide_exception_text(monkeypatch):
    from backend.dashboard import service

    class BoomAgent:
        def __init__(self, *a, **kw):
            pass

        def analyze(self, ticker):
            raise RuntimeError(SECRET)

    monkeypatch.setattr(service, "InsiderAgent", BoomAgent)
    insider = service._build_insider_component("AAPL", True, "key", {})
    assert insider.label == "error" and SECRET not in repr(insider)

    monkeypatch.setattr(service, "NewsService", lambda: types.SimpleNamespace(search_news=_boom))
    news = service._build_news_component("AAPL", True)
    assert news.label == "error" and SECRET not in repr(news)


def test_insider_agent_http_error_does_not_return_url_or_token(monkeypatch):
    from backend.dashboard.core import insider_agent

    def failing_get(url, **kwargs):
        raise requests.exceptions.ConnectionError(f"{url}?token={SECRET}")

    monkeypatch.setattr(insider_agent.requests, "get", failing_get)
    agent = insider_agent.InsiderAgent("key", {"key": "k", "hosts": {"fmp": "example.invalid"}})
    out = agent._safe_request("https://finnhub.io/api/v1/stock/insider-transactions", params={"token": SECRET})
    assert SECRET not in repr(out)
    assert out == {"error": "API request failed"}


# --------------------------------------------------------------------------- news

def test_news_latest_hides_exception_text(client, monkeypatch):
    from backend.news import main as news_main

    monkeypatch.setattr(news_main._NEWS_SERVICE, "search_news", _boom)
    r = client.get("/api/news/latest")
    _assert_hidden(r, 500, {"detail": "News request failed"})


def test_news_live_fallback_message_is_fixed(client, monkeypatch):
    from backend.news import main as news_main

    monkeypatch.setattr(news_main.live_news_service, "get_news", _boom)
    monkeypatch.setattr(news_main.live_news_service, "get_cached_news", _boom)
    r = client.get("/api/news/live")
    _assert_hidden(r, 200)
    assert r.json()["message"] == "Live news temporarily unavailable"
    assert r.json()["articles"] == []


def test_news_article_summary_hides_exception_text(client, monkeypatch):
    from backend.news import main as news_main

    monkeypatch.setattr(news_main.live_news_service, "summarize_article", _boom)
    r = client.get("/api/news/article-summary", params={"url": "https://example.com/a"})
    _assert_hidden(r, 500, {"detail": "Article summary request failed"})


# --------------------------------------------------------------------------- network

def test_network_graph_hides_exception_text(client, monkeypatch):
    from backend.network import main as network_main

    monkeypatch.setattr(network_main, "get_network_graph", _boom)
    r = client.get("/api/network/AAPL")
    _assert_hidden(r, 500, {"detail": "Network graph request failed"})


# --------------------------------------------------------------------------- peers

def test_peers_hides_exception_text(client, monkeypatch):
    from backend.peers import main as peers_main

    monkeypatch.setattr(peers_main, "fetch_stock_peers", _boom)
    r = client.get("/api/peers/AAPL")
    _assert_hidden(r, 500, {"detail": "Failed to fetch peers"})


def test_peers_compare_debug_flag_does_not_echo_exception_text(client, monkeypatch):
    from backend.peers import main as peers_main

    monkeypatch.setattr(peers_main, "fetch_peer_comparison", _boom)
    r = client.get("/api/peers/compare/AAPL", params={"debug": "true"})
    _assert_hidden(r, 200)
    assert r.json()["error"] == "Peer comparison failed"
    assert r.json()["partial"] is True


# --------------------------------------------------------------------------- markets / FRED

class _BoomFred:
    def __getattr__(self, name):
        return _boom


@pytest.fixture
def boom_fred(client):
    from backend.markets.fred_routes import get_fred_service

    main_app.dependency_overrides[get_fred_service] = lambda: _BoomFred()
    try:
        yield client
    finally:
        main_app.dependency_overrides.pop(get_fred_service, None)


@pytest.mark.parametrize("path", [
    "/api/fred/series/GDP",
    "/api/fred/series/GDP/latest",
    "/api/fred/latest",
    "/api/fred/dashboard",
    "/api/fred/smart/GDP",
])
def test_fred_routes_hide_exception_text(boom_fred, path):
    r = boom_fred.get(path)
    _assert_hidden(r, 500, {"detail": "FRED data request failed"})


def test_fred_sync_hides_exception_text(boom_fred):
    from backend.auth import create_access_token

    headers = {"Authorization": "Bearer " + create_access_token("fred-boom-user")[0]}
    r = boom_fred.post("/api/fred/sync/all", headers=headers)
    _assert_hidden(r, 500, {"detail": "FRED data request failed"})


def test_fred_service_unconfigured_message_is_fixed(client, monkeypatch):
    """A live-provider request without credentials maps to a fixed 503 (no provider text)."""
    from backend.markets import fred_routes
    from backend.markets.fred_service import FredDataService, FredUnavailable

    def missing_key(self, *a, **kw):
        raise FredUnavailable(f"FRED_API_KEY is {SECRET}")

    monkeypatch.setattr(FredDataService, "fetch_series", missing_key)
    r = client.get("/api/fred/latest-live?series_ids=GDP")
    _assert_hidden(r, 503, {"detail": "FRED service is not configured"})


def test_eia_error_does_not_return_url_or_api_key(monkeypatch):
    from backend.markets import eia_service

    monkeypatch.setenv("EIA_API_KEY", SECRET)

    def failing_get(url, params=None, **kwargs):
        raise requests.exceptions.ConnectionError(f"{url}?api_key={params['api_key']}")

    monkeypatch.setattr(eia_service.requests, "get", failing_get)
    out = eia_service.EIAService().get_petroleum_summary()
    assert SECRET not in repr(out)
    assert out == {"error": "EIA data request failed"}


def test_eia_without_key_makes_no_request(monkeypatch):
    from backend.markets import eia_service

    monkeypatch.delenv("EIA_API_KEY", raising=False)
    monkeypatch.setattr(eia_service.requests, "get", _boom)
    assert eia_service.EIAService().get_petroleum_summary() == {"error": "EIA data source is not configured"}


def test_no_hardcoded_eia_key_in_source():
    from pathlib import Path

    from backend.markets import eia_service

    source = Path(eia_service.__file__).read_text(encoding="utf-8")
    assert "API_KEY =" not in source and "jvRlsf" not in source


# --------------------------------------------------------------------------- sectors

def test_sectors_treemap_live_hides_exception_text(client, monkeypatch):
    from backend.sectors import main as sectors_main

    monkeypatch.setattr(sectors_main.sectors_service, "get_indices_live", _boom)
    r = client.get("/api/sectors/treemap/indices/live", params={"market": "us"})
    _assert_hidden(r, 200, {"market": "us", "count": 0, "indices": [], "error": "indices_unavailable"})


def test_sector_sentiment_service_errors_are_generic(monkeypatch):
    from backend.sectors.core import stock_sentiment_service as svc

    class BoomTicker:
        def __init__(self, symbol):
            pass

        @property
        def history(self):
            return _boom

    monkeypatch.setattr(svc.yf, "Ticker", BoomTicker)
    out = svc.fetch_stock_data("AAPL")
    assert SECRET not in repr(out)
    assert out == {"error": "Market data unavailable", "symbol": "AAPL"}

    monkeypatch.setattr(svc, "analyze_stock_sentiment", _boom)
    results = svc.analyze_multiple_stocks(["AAPL"])
    assert SECRET not in repr(results)
    assert results == [{"symbol": "AAPL", "error": "Sentiment analysis failed"}]


# --------------------------------------------------------------------------- chat sub-routers

def test_chat_sentiment_hides_exception_text(client, monkeypatch):
    from backend.chat import sentiment

    monkeypatch.setattr(sentiment, "analyze_stock_sentiment", _boom)
    r = client.get("/api/chat/sentiment/analyze/AAPL")
    _assert_hidden(r, 500, {"detail": "Sentiment analysis failed"})
    r = client.get("/api/chat/sentiment/quick/AAPL")
    _assert_hidden(r, 500, {"detail": "Quick analysis failed"})
    r = client.post("/api/chat/sentiment/analyze", json={"symbol": "AAPL"})
    _assert_hidden(r, 500, {"detail": "Sentiment analysis failed"})
    monkeypatch.setattr(sentiment, "analyze_multiple_stocks", _boom)
    r = client.post("/api/chat/sentiment/batch", json={"symbols": ["AAPL"]})
    _assert_hidden(r, 500, {"detail": "Batch analysis failed"})


def test_super_agent_hides_exception_text(client, monkeypatch):
    from backend.chat import super_agent

    monkeypatch.setattr(super_agent, "_get_pipeline", lambda: types.SimpleNamespace(run=_aboom))
    r = client.post("/api/chat/super-agent", json={"query": "analyse AAPL"})
    _assert_hidden(r, 500, {"detail": "Super agent request failed"})


# --------------------------------------------------------------------------- core

def test_safe_yfinance_errors_are_generic(monkeypatch):
    from backend.core import safe_yfinance

    monkeypatch.setattr(safe_yfinance.yf, "Ticker", _boom)
    history = safe_yfinance.safe_fetch_history("LEAKTEST1", period="1mo", interval="1d", rate_limit=False)
    info = safe_yfinance.safe_fetch_info("LEAKTEST2")
    assert SECRET not in repr(history) and SECRET not in repr(info)
    assert history["error"] == "Market data request failed"
    assert info["error"] == "Market data request failed"
