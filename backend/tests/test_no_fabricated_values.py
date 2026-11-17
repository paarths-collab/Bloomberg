"""Regression tests: numbers that used to be invented must be null when there is no real source.

No network: every provider call is monkeypatched.
"""
import asyncio
import sys
import types

import pandas as pd
import pytest

import backend.sectors.core.stock_sentiment_service as svc
from backend.dashboard import service as dash
from backend.services import market_data as md
from backend.services.market_data import MarketDataService


# --------------------------------------------------------------------------- sentiment service

def _stock(**over):
    data = {
        "symbol": "ZZZ",
        "company_name": "Zed Corp",
        "sector": "Tech",
        "market": "us",
        "currency": "$",
        "current_price": 100.0,
        "price_change_6m_pct": 0.0,
        "recommendation_key": "",
        "target_mean_price": None,
    }
    data.update(over)
    return data


def _run_pipeline(monkeypatch, ai_result, stock=None):
    stock = stock or _stock()
    monkeypatch.setattr(svc, "fetch_stock_data", lambda s: stock)
    monkeypatch.setattr(svc, "fetch_reddit_posts", lambda q: [])
    monkeypatch.setattr(svc, "fetch_duckduckgo_news", lambda *a, **k: {"articles": []})
    monkeypatch.setattr(svc, "analyze_with_gemini", lambda sd, rs: ai_result)
    return svc.analyze_stock_sentiment("ZZZ")


def test_heuristic_without_analyst_target_has_null_target_price():
    out = svc.generate_fallback_analysis(_stock(current_price=250.0), {"post_count": 0})
    assert out["target_price"] is None
    assert out["confidence"] is None


def test_heuristic_missing_price_does_not_default_to_zero_target():
    stock = _stock()
    stock.pop("current_price")
    out = svc.generate_fallback_analysis(stock, {"post_count": 0})
    assert out["target_price"] is None


def test_heuristic_uses_real_analyst_target_only():
    out = svc.generate_fallback_analysis(_stock(target_mean_price=123.456), {"post_count": 0})
    assert out["target_price"] == 123.46


def test_heuristic_has_no_canned_risks_or_catalysts():
    out = svc.generate_fallback_analysis(_stock(price_change_6m_pct=2.0), {"post_count": 0})
    assert out["risks"] == [] and out["catalysts"] == []


def test_heuristic_risks_only_from_data():
    down = svc.generate_fallback_analysis(_stock(price_change_6m_pct=-5.0), {"post_count": 0})
    assert down["risks"] == ["Negative price momentum"] and down["catalysts"] == []
    up = svc.generate_fallback_analysis(_stock(price_change_6m_pct=30.0), {"post_count": 0})
    assert up["catalysts"] == ["Strong price momentum"] and up["risks"] == []


def test_heuristic_tolerates_missing_6m_change():
    out = svc.generate_fallback_analysis(_stock(price_change_6m_pct=None), {"post_count": 0})
    assert "6-month" not in out["summary"]
    assert out["risks"] == [] and out["catalysts"] == []


def test_pipeline_heuristic_path(monkeypatch):
    stock = _stock(price_change_6m_pct=25.0)
    result = _run_pipeline(monkeypatch, svc.generate_fallback_analysis(stock, {"post_count": 0}), stock)
    assert result["analysis_status"] == "heuristic"
    assert result["sentiment"] == 0.7
    assert result["targetPrice"] is None
    assert result["confidence"] is None
    assert result["risks"] == [] and result["catalysts"] == ["Strong price momentum"]


def test_pipeline_model_without_confidence_is_model_with_null_confidence(monkeypatch):
    ai = {
        "source": "gemini",
        "outlook": "Bullish",
        "sentiment_score": 0.8,
        "recommendation": "BUY",
        "summary": "ok",
    }
    result = _run_pipeline(monkeypatch, ai)
    assert result["analysis_status"] == "model"
    assert result["confidence"] is None  # not the old fabricated 0.5
    assert result["targetPrice"] is None
    assert result["sentiment"] == 0.8


def test_pipeline_model_without_sentiment_has_null_sentiment(monkeypatch):
    result = _run_pipeline(monkeypatch, {"source": "gemini", "confidence": 0.9})
    assert result["analysis_status"] == "model"
    assert result["sentiment"] is None
    assert result["confidence"] == 0.9
    assert result["recommendation"] is None and result["outlook"] is None


def test_pipeline_model_keeps_real_values(monkeypatch):
    ai = {"source": "gemini", "sentiment_score": 0.3, "confidence": 0.65, "target_price": 150}
    result = _run_pipeline(monkeypatch, ai)
    assert (result["sentiment"], result["confidence"], result["targetPrice"]) == (0.3, 0.65, 150.0)


def test_pipeline_rejects_non_numeric_model_values(monkeypatch):
    ai = {"source": "gemini", "sentiment_score": "high", "confidence": float("nan"), "target_price": True}
    result = _run_pipeline(monkeypatch, ai)
    assert result["sentiment"] is None and result["confidence"] is None and result["targetPrice"] is None


def test_pipeline_unknown_source_is_unavailable(monkeypatch):
    result = _run_pipeline(monkeypatch, {"sentiment_score": 0.6})
    assert result["analysis_status"] == "unavailable"


def test_fetch_stock_data_single_observation_has_null_changes(monkeypatch):
    hist = pd.DataFrame(
        {"Close": [50.0], "Volume": [1000]}, index=pd.to_datetime(["2024-01-02"])
    )

    class FakeTicker:
        def __init__(self, symbol):
            self.history_df = hist
            self.info = {}
            self.quarterly_financials = None

        def history(self, period="6mo"):
            return self.history_df

    monkeypatch.setattr(svc.yf, "Ticker", FakeTicker)
    data = svc.fetch_stock_data("ZZZ")
    assert data["current_price"] == 50.0
    assert data["day_change"] is None and data["day_change_pct"] is None
    assert data["price_change_6m_pct"] is None


def test_fetch_stock_data_two_observations_unchanged(monkeypatch):
    hist = pd.DataFrame(
        {"Close": [100.0, 110.0], "Volume": [10, 10]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )

    class FakeTicker:
        def __init__(self, symbol):
            self.info = {}
            self.quarterly_financials = None

        def history(self, period="6mo"):
            return hist

    monkeypatch.setattr(svc.yf, "Ticker", FakeTicker)
    data = svc.fetch_stock_data("ZZZ")
    assert data["day_change"] == 10.0
    assert data["day_change_pct"] == 10.0
    assert data["price_change_6m_pct"] == 10.0


# --------------------------------------------------------------------------- dashboard confidence

def _component(available):
    return dash.SignalComponent(0.5 if available else None, "bullish" if available else "unavailable", available, {})


def test_estimate_confidence_is_not_hardcoded():
    assert dash._estimate_confidence(_component(True), _component(True)) is None
    assert dash._estimate_confidence(_component(True), _component(False)) is None


def test_crowd_insight_confidence_null_and_not_computed(monkeypatch):
    monkeypatch.setattr(dash, "_build_insider_component", lambda **k: _component(True))
    monkeypatch.setattr(dash, "_build_news_component", lambda **k: _component(True))
    out = dash.analyze_crowd_insight("AAPL", finnhub_key="k")
    assert out["signal"]["confidence"] is None
    assert out["signal"]["confidence_status"] == "not_computed"
    assert out["signal"]["score"] is not None  # real score still reported


def test_crowd_insight_unavailable_has_null_everything(monkeypatch):
    monkeypatch.setattr(dash, "_build_insider_component", lambda **k: _component(False))
    monkeypatch.setattr(dash, "_build_news_component", lambda **k: _component(False))
    out = dash.analyze_crowd_insight("AAPL")
    assert out["signal"]["score"] is None
    assert out["signal"]["confidence"] is None
    assert out["signal"]["label"] == "unavailable"


# --------------------------------------------------------------------------- market overview change

class _FakeFred:
    def __init__(self, series):
        self._series = series

    def fetch_series(self, series_id):
        return self._series.get(series_id)


def _overview(monkeypatch, fred_series=None, yf_closes=None):
    import backend.markets.fred_service as fred_mod

    fred_series = fred_series or {}
    monkeypatch.setattr(fred_mod, "FredDataService", lambda: _FakeFred(fred_series))

    def fake_history(symbol, period="5d", **kw):
        closes = (yf_closes or {}).get(symbol)
        if closes is None:
            return {"status": "error", "data": None}
        idx = pd.date_range("2024-01-01", periods=len(closes), freq="D")
        return {"status": "ok", "data": pd.DataFrame({"Close": closes}, index=idx)}

    monkeypatch.setattr(md, "safe_fetch_history", fake_history)
    return MarketDataService().get_market_overview()


def _series(values):
    return pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))


def test_single_fred_observation_has_null_change(monkeypatch):
    out = _overview(monkeypatch, fred_series={"SP500": _series([5000.0])})
    assert out["SP500"]["price"] == 5000.0
    assert out["SP500"]["change"] is None
    assert out["SP500"]["change_pct"] is None


def test_previous_zero_fred_has_null_change(monkeypatch):
    out = _overview(monkeypatch, fred_series={"VIXCLS": _series([0.0, 15.0])})
    assert out["VIXCLS"]["price"] == 15.0
    assert out["VIXCLS"]["change"] is None
    assert out["VIXCLS"]["change_pct"] is None


def test_two_observation_fred_change_unchanged(monkeypatch):
    out = _overview(monkeypatch, fred_series={"SP500": _series([100.0, 110.0])})
    assert out["SP500"]["change"] == 10.0
    assert out["SP500"]["change_pct"] == 10.0


def test_single_yfinance_observation_has_null_change(monkeypatch):
    out = _overview(monkeypatch, yf_closes={"^NSEI": [22000.0]})
    assert out["^NSEI"]["price"] == 22000.0
    assert out["^NSEI"]["change"] is None
    assert out["^NSEI"]["change_pct"] is None


def test_previous_zero_yfinance_has_null_change(monkeypatch):
    out = _overview(monkeypatch, yf_closes={"GC=F": [0.0, 2000.0]})
    assert out["GC=F"]["change"] is None and out["GC=F"]["change_pct"] is None


def test_two_observation_yfinance_change_unchanged(monkeypatch):
    out = _overview(monkeypatch, yf_closes={"^BSESN": [200.0, 190.0]})
    assert out["^BSESN"]["change"] == -10.0
    assert out["^BSESN"]["change_pct"] == -5.0


def test_period_change_helper():
    assert md._period_change(110.0, 100.0) == (10.0, 10.0)
    assert md._period_change(110.0, None) == (None, None)
    assert md._period_change(110.0, 0.0) == (None, None)
    assert md._period_change(110.0, float("nan")) == (None, None)


# --------------------------------------------------------------------------- heuristic: no rule fires

def test_heuristic_no_rule_fires_returns_null_score():
    out = svc.generate_fallback_analysis(_stock(price_change_6m_pct=2.0), {"post_count": 0})
    assert out["sentiment_score"] is None
    assert out["outlook"] is None and out["recommendation"] is None
    assert out["status"] == "heuristic_no_signal"
    assert out["target_price"] is None and out["confidence"] is None


def test_heuristic_no_data_at_all_returns_null_score():
    out = svc.generate_fallback_analysis(
        _stock(price_change_6m_pct=None, recommendation_key=None), {"post_count": 0}
    )
    assert out["sentiment_score"] is None and out["status"] == "heuristic_no_signal"


def test_heuristic_rule_derived_scores_kept():
    up = svc.generate_fallback_analysis(_stock(price_change_6m_pct=25.0), {"post_count": 0})
    assert up["sentiment_score"] == 0.7 and up["outlook"] == "Bullish" and up["status"] == "heuristic"
    down = svc.generate_fallback_analysis(_stock(price_change_6m_pct=-15.0, recommendation_key="SELL"), {"post_count": 0})
    assert down["sentiment_score"] == 0.25 and down["outlook"] == "Bearish"
    rec = svc.generate_fallback_analysis(_stock(recommendation_key="BUY"), {"post_count": 0})
    assert rec["sentiment_score"] == 0.65 and rec["recommendation"] == "BUY"
    reddit = svc.generate_fallback_analysis(_stock(), {"post_count": 20, "avg_score": 500})
    assert reddit["sentiment_score"] == 0.6


def test_pipeline_heuristic_no_signal_status(monkeypatch):
    stock = _stock(price_change_6m_pct=1.0)
    result = _run_pipeline(monkeypatch, svc.generate_fallback_analysis(stock, {"post_count": 0}), stock)
    assert result["analysis_status"] == "heuristic_no_signal"
    assert result["sentiment"] is None
    assert result["recommendation"] is None and result["outlook"] is None
    assert result["targetPrice"] is None and result["confidence"] is None


# --------------------------------------------------------------------------- chat minimal shape

def test_chat_minimal_sentiment_shape_has_no_fake_values():
    from backend.chat.core import stock_sentiment_service as chat_svc

    out = chat_svc._minimal_sentiment_shape("aapl")
    assert out["symbol"] == "AAPL" and out["ticker"] == "AAPL"
    assert out["score"] is None
    assert out["confidence"] is None
    assert out["sentiment"]["overall"] is None
    assert out["recommendation"] is None and out["outlook"] is None
    assert out["label"] == "unavailable"
    assert out["analysis_status"] == "unavailable"
    assert out["source"] == "fallback"
    for key in ("market_data", "news", "supply_chain"):  # response keys preserved
        assert key in out


def test_chat_analyze_falls_back_to_unavailable_shape(monkeypatch):
    from backend.chat.core import stock_sentiment_service as chat_svc

    def boom(_):
        raise RuntimeError("down")

    monkeypatch.setattr(chat_svc, "_RICH_AVAILABLE", True)
    monkeypatch.setattr(chat_svc, "_rich_analyze_stock_sentiment", boom)
    out = chat_svc.analyze_stock_sentiment("MSFT")
    assert out["analysis_status"] == "unavailable" and out["confidence"] is None


# --------------------------------------------------------------------------- POV parser confidence

def test_pov_parser_valid_confidence():
    from backend.chat.stock_advisor import _parse_pov_response

    pov = _parse_pov_response("VERDICT: BUY\nCONFIDENCE: 0.8\nREASONING: r\nKEY_FACTORS:\n- a", "Bull", "Groq")
    assert pov.confidence == 0.8 and pov.confidence_status == "ok"


def test_pov_parser_clamps_out_of_range():
    from backend.chat.stock_advisor import _parse_pov_response

    pov = _parse_pov_response("VERDICT: BUY\nCONFIDENCE: 7\nREASONING: r", "Bull", "Groq")
    assert pov.confidence == 1.0 and pov.confidence_status == "ok"


def test_pov_parser_missing_confidence_is_null():
    from backend.chat.stock_advisor import _parse_pov_response

    pov = _parse_pov_response("VERDICT: SELL\nREASONING: r", "Bear", "Groq")
    assert pov.confidence is None and pov.confidence_status == "confidence_missing"
    assert pov.model_dump()["confidence"] is None


def test_pov_parser_unparseable_confidence_is_null():
    from backend.chat.stock_advisor import _parse_pov_response

    for bad in ("high", "nan", "inf"):
        pov = _parse_pov_response(f"VERDICT: BUY\nCONFIDENCE: {bad}\nREASONING: r", "Bull", "Groq")
        assert pov.confidence is None and pov.confidence_status == "confidence_unparseable"


# --------------------------------------------------------------------------- chat price summaries

@pytest.fixture
def manager(monkeypatch):
    """Real backend.chat.pipelines, with the legacy modules missing from this checkout stubbed."""
    saved = sys.modules.pop("backend.chat.pipelines", None)
    stubs = {
        "backend.services.emotion_advisor_service": {"analyze_emotion_safe_advice": lambda **kw: {}},
        "backend.services.emotion_data_scraper": {"EmotionDataScraper": type("S", (), {})},
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
    ddg.DuckDuckGoMCPTool = type("DuckDuckGoMCPTool", (), {})
    monkeypatch.setitem(sys.modules, "backend.tools", tools)
    monkeypatch.setitem(sys.modules, "backend.tools.duckduckgo_mcp", ddg)
    try:
        import backend.chat.pipelines as module

        yield module.PipelineManager(use_gemini_formatting=False)
    finally:
        if saved is None:
            sys.modules.pop("backend.chat.pipelines", None)
        else:
            sys.modules["backend.chat.pipelines"] = saved


def test_stock_summary_missing_price_is_na_not_zero(manager):
    out = manager._create_stock_summary({"symbol": "ZZZ", "company_name": "Zed"})
    assert "| **Current Price** | N/A |" in out
    assert "| **Daily Change** |  N/A (N/A) |" in out
    assert "$0.00 |" not in out.split("## 📈 Returns")[0]
    assert "| **Previous Close** | N/A |" in out
    assert "| **Volume** | N/A |" in out


def test_stock_summary_real_price_still_formatted(manager):
    out = manager._create_stock_summary({
        "symbol": "ZZZ", "company_name": "Zed", "current_price": 1234.5,
        "daily_change": -2.5, "daily_change_pct": -0.2, "previous_close": 1237.0, "volume": 1500,
    })
    assert "| **Current Price** | $1,234.50 |" in out
    assert "$-2.50" in out and "-0.20%" in out
    assert "| **Volume** | 1,500 |" in out


def test_enhanced_summary_missing_price_is_na_not_zero(manager):
    out = asyncio.run(manager._create_stock_summary_enhanced({"symbol": "ZZZ", "company_name": "Zed"}))
    assert "Current Price: N/A" in out and "Daily Change: N/A" in out
    assert "Previous Close: N/A" in out and "52-Week Range: N/A - N/A" in out


def _core_pipeline(monkeypatch, levels):
    from backend.chat.core import pipeline as core

    pipe = core.InvestmentPipeline.__new__(core.InvestmentPipeline)
    pipe.memory = core._StubVectorStore()
    pipe._agent = None
    calls = []

    class Levels:
        def get_levels(self, ticker):
            return levels

    class Sizing:
        def fixed_fraction(self, capital):
            calls.append(capital)
            return {"shares": 1}

    pipe.trade_levels = Levels()
    pipe.sizing = Sizing()
    return pipe, calls


def test_core_pipeline_skips_sizing_without_entry_price():
    for levels in ({"error": "No data"}, {"current_price": None, "stop_loss": 9.0}, {"current_price": 0, "stop_loss": 0}):
        pipe, calls = _core_pipeline(None, levels)
        out = asyncio.run(pipe.run("analyze", ticker="AAPL"))
        assert calls == [] and out["strategy"]["position_sizing"] == {}


def test_core_pipeline_sizes_with_real_levels():
    pipe, calls = _core_pipeline(None, {"current_price": 100.0, "stop_loss": 95.0})
    out = asyncio.run(pipe.run("analyze", ticker="AAPL"))
    assert calls == [100000.0] and out["strategy"]["position_sizing"] == {"shares": 1}


# --------------------------------------------------------------------------- chat fundamentals rows

_FUNDAMENTAL_LABELS = [
    "Market Cap", "P/E (Trailing)", "P/E (Forward)", "PEG Ratio", "Price/Book", "Price/Sales",
    "EV/Revenue", "EV/EBITDA", "Profit Margin", "Operating Margin", "ROE", "ROA", "Revenue Growth",
    "Earnings Growth", "Total Cash", "Total Debt", "Debt/Equity", "Current Ratio", "Free Cash Flow",
    "EPS (Trailing)", "EPS (Forward)", "Book Value", "Dividend Rate", "Dividend Yield", "Payout Ratio",
    "Rating", "Rating Score", "Target High", "Target Mean", "Target Low", "# of Analysts", "Beta",
    "Short Ratio", "Short % of Float", "Institutional Ownership", "Insider Ownership",
]


def _row(out, label):
    prefix = f"| **{label}** | "
    lines = [ln for ln in out.splitlines() if ln.startswith(prefix)]
    assert len(lines) == 1, label
    return lines[0][len(prefix):].rstrip(" |")


def test_stock_summary_missing_fundamentals_are_na_not_zero(manager):
    out = manager._create_stock_summary({"symbol": "ZZZ", "company_name": "Zed"})
    for label in _FUNDAMENTAL_LABELS:
        assert _row(out, label) == "N/A", label
    assert "- **Employees:** N/A" in out
    assert "0.00B" not in out and "0.0%" not in out and "0.00%" not in out


def test_stock_summary_null_fundamentals_do_not_break_formatting(manager):
    data = {"symbol": "ZZZ", "company_name": "Zed", "analyst_rating": None, "returns": {"1m": None, "1y": 12.5}}
    out = manager._create_stock_summary(data)
    assert "Error formatting" not in out
    assert _row(out, "Rating") == "N/A"
    assert "**1Y:** +12.50%" in out and "1M" not in out


def test_stock_summary_real_fundamentals_formatted(manager):
    out = manager._create_stock_summary({
        "symbol": "ZZZ", "company_name": "Zed", "employees": 1200, "market_cap": 2.5e12,
        "trailing_pe": 31.256, "profit_margin": 0.256, "total_cash": 5e9, "total_debt": 0,
        "eps_trailing": 6.4, "dividend_yield": 0.0, "analyst_rating": "buy", "analyst_rating_score": 1.8,
        "target_mean": 210.5, "num_analysts": 40, "beta": 1.1, "short_pct_of_float": 0.012,
    })
    assert _row(out, "Market Cap") == "$2500.00B"
    assert _row(out, "P/E (Trailing)") == "31.26"
    assert _row(out, "Profit Margin") == "25.6%"
    assert _row(out, "Total Cash") == "$5.00B"
    assert _row(out, "Total Debt") == "$0.00B"  # a real zero is still shown
    assert _row(out, "Dividend Yield") == "0.00%"
    assert _row(out, "Rating") == "BUY" and _row(out, "Rating Score") == "1.8/5"
    assert _row(out, "Target Mean") == "$210.50" and _row(out, "# of Analysts") == "40"
    assert _row(out, "Short % of Float") == "1.20%"
    assert "- **Employees:** 1,200" in out
    assert _row(out, "Revenue Growth") == "N/A"  # still-missing ones stay N/A


def test_enhanced_summary_missing_moving_average_parts_are_na(manager):
    data = {
        "symbol": "ZZZ", "company_name": "Zed",
        "technical_indicators": {"available": True, "moving_averages": {"sma_200": 100.0}},
    }
    out = asyncio.run(manager._create_stock_summary_enhanced(data))
    assert "SMA20=N/A" in out and "SMA50=N/A" in out and "SMA200=$100.00" in out
