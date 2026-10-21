"""
backend.chat.pipelines must run its baseline backtest through backend.backtest.service
(it used to import the nonexistent backend.services.backtest_service).

Offline: market data is replaced by synthetic candles and no LLM/web call is made. The modules
pipelines.py imports that do not exist in this checkout (emotion advisor/scraper, company
resolver, DuckDuckGo tool) are stubbed, the same way test_chat_isolation.py stubs missing
optional dependencies.
"""
import asyncio
import sys
import types

import numpy as np
import pandas as pd
import pytest

from backend.backtest import service as backtest_service

SECRET = "secret-token-XYZ"


def _candles(n=260, seed=3):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    closes = 100 + 12 * np.sin(2 * np.pi * t / 60) + np.cumsum(rng.normal(0, 0.5, n))
    opens = np.r_[closes[0], closes[:-1]]
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2023-01-02", periods=n)]
    return [
        {"date": d, "open": float(o), "high": float(max(o, c) + 0.3), "low": float(min(o, c) - 0.3),
         "close": float(c), "volume": 1000}
        for d, o, c in zip(dates, opens, closes)
    ]


@pytest.fixture
def pipelines(monkeypatch):
    """Import the real backend.chat.pipelines against stubs for its missing legacy modules."""
    saved = sys.modules.pop("backend.chat.pipelines", None)

    class _Scraper:
        def scrape_social_sentiment(self, ticker):
            return {"reddit": {"posts": 0}}

    stubs = {
        "backend.services.emotion_advisor_service": {"analyze_emotion_safe_advice": lambda **kw: {}},
        "backend.services.emotion_data_scraper": {"EmotionDataScraper": _Scraper},
        "backend.services.company_resolver": {"resolve_company_identity": lambda *a, **kw: {}},
    }
    for name, attrs in stubs.items():
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        monkeypatch.setitem(sys.modules, name, mod)
    tools = types.ModuleType("backend.tools")
    tools.__path__ = []
    ddg = types.ModuleType("backend.tools.duckduckgo_mcp")
    ddg.DuckDuckGoMCPTool = type("DuckDuckGoMCPTool", (), {"search": lambda self, q, n=6: ""})
    monkeypatch.setitem(sys.modules, "backend.tools", tools)
    monkeypatch.setitem(sys.modules, "backend.tools.duckduckgo_mcp", ddg)

    try:
        import backend.chat.pipelines as module
        yield module
    finally:
        if saved is None:
            sys.modules.pop("backend.chat.pipelines", None)
        else:
            sys.modules["backend.chat.pipelines"] = saved


@pytest.fixture
def manager(pipelines, monkeypatch):
    mgr = pipelines.PipelineManager(use_gemini_formatting=False)

    async def sharpe(ticker, market):
        return 1.25

    async def summary(stock_data):
        return "summary"

    monkeypatch.setattr(pipelines, "get_comprehensive_stock_data",
                        lambda ticker, market: {"company_name": "Test Corp"})
    monkeypatch.setattr(mgr, "_calculate_sharpe_ratio", sharpe)
    monkeypatch.setattr(mgr, "_create_stock_summary_enhanced", summary)
    return mgr


def _run(mgr):
    return asyncio.run(mgr.run_stock_info_pipeline(
        "TEST", market="US", include_technicals=False, include_web_search=False, include_backtest=True,
    ))


def test_pipelines_use_the_backtest_package(pipelines):
    assert pipelines.run_backtest_service is backtest_service.run_backtest_service


def test_stock_info_pipeline_runs_backtest_through_backtest_service(manager, monkeypatch):
    calls = []

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        return _candles()

    monkeypatch.setattr(backtest_service, "_fetch_candles_with_fallback", fake_fetch)

    result = _run(manager)

    assert result.success, result.data
    assert len(calls) == 1
    assert calls[0]["symbol"] == "TEST"
    assert calls[0]["interval"] == "1d"
    assert calls[0]["range_period"] == "1y"
    bt = result.data["backtest"]
    assert bt["strategy"] == "momentum"
    assert bt["error"] is None
    assert isinstance(bt["metrics"], dict) and bt["metrics"]


def test_stock_info_pipeline_survives_backtest_provider_failure(manager, monkeypatch):
    def failing_fetch(**kwargs):
        raise backtest_service.MarketDataError(SECRET)

    monkeypatch.setattr(backtest_service, "_fetch_candles_with_fallback", failing_fetch)

    result = _run(manager)

    assert result.success, result.data
    assert result.data["backtest"] == {"strategy": "momentum", "metrics": None, "error": "Backtest unavailable"}
    assert SECRET not in repr(result.data)


def test_stock_info_pipeline_failure_hides_exception_text(manager, pipelines, monkeypatch):
    def boom(ticker, market):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(pipelines, "get_comprehensive_stock_data", boom)

    result = _run(manager)

    assert result.success is False
    assert SECRET not in result.summary
    assert SECRET not in repr(result.data)
    assert result.data == {"error": "Stock analysis failed"}
