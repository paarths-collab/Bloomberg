"""Exception text must not reach callers of the chat/core services or stock advisor (offline).

Each failing inner call raises RuntimeError("secret-token-XYZ"); the value returned to the caller
must be the fixed generic message and must not contain the secret.
"""
import sys
import types

import pytest

from backend.chat import stock_advisor
from backend.chat.core import groq_agent as chat_groq_agent
from backend.chat.core import position_sizing_service as sizing
from backend.chat.core import research_service
from backend.chat.core import trade_levels_service

SECRET = "secret-token-XYZ"


def _boom(*args, **kwargs):
    raise RuntimeError(SECRET)


class _Boom:
    """Operand whose arithmetic raises, so a service's try block fails with the secret."""

    def _raise(self, *args):
        raise RuntimeError(SECRET)

    __rsub__ = __rmul__ = __sub__ = __mul__ = _raise


# --------------------------------------------------------------------------- groq agent

def test_chat_groq_generate_hides_exception_text(monkeypatch):
    monkeypatch.setattr(chat_groq_agent.requests, "post", _boom)
    out = chat_groq_agent.GroqAgent(api_key="test-key").generate_response("hi")
    assert out == "Error calling Groq API"
    assert SECRET not in out


def test_chat_groq_vision_hides_exception_text(monkeypatch):
    monkeypatch.setattr(chat_groq_agent.requests, "post", _boom)
    out = chat_groq_agent.GroqAgent(api_key="test-key").generate_vision_response(
        "describe", "data:image/png;base64,AAAA"
    )
    assert out == "Error calling Groq vision API"
    assert SECRET not in out


# --------------------------------------------------------------------------- position sizing

def test_kelly_criterion_hides_exception_text():
    out = sizing.PositionSizingService().kelly_criterion(win_rate=_Boom(), avg_win=2.0, avg_loss=1.0)
    assert out == {"error": "Position sizing failed"}
    assert SECRET not in str(out)


def test_fixed_fraction_hides_exception_text():
    out = sizing.PositionSizingService().fixed_fraction(risk_pct=_Boom())
    assert out == {"error": "Position sizing failed"}
    assert SECRET not in str(out)


# --------------------------------------------------------------------------- research service

def test_research_report_hides_exception_text(monkeypatch):
    monkeypatch.setattr(research_service.market_service, "get_fundamentals", _boom)
    out = research_service.generate_research_report("aapl")
    assert out == {"ticker": "aapl", "error": "Research report unavailable", "status": "error"}
    assert SECRET not in str(out)
    assert research_service.get_fundamentals_summary("aapl") == out


# --------------------------------------------------------------------------- trade levels

def test_trade_levels_hides_exception_text(monkeypatch):
    monkeypatch.setattr(trade_levels_service.market_service, "get_history", _boom)
    out = trade_levels_service.TradeLevelsService().get_levels("AAPL")
    assert out == {"ticker": "AAPL", "error": "Trade levels unavailable"}
    assert SECRET not in str(out)


# --------------------------------------------------------------------------- stock advisor (LLM text)

def test_stock_advisor_gemini_hides_exception_text(monkeypatch):
    fake_genai = types.ModuleType("google.generativeai")
    fake_genai.configure = _boom
    fake_google = types.ModuleType("google")
    fake_google.generativeai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    out = stock_advisor._call_gemini("prompt")
    assert out == "[Gemini error: AI analysis unavailable]"
    assert SECRET not in out


def test_stock_advisor_groq_hides_exception_text(monkeypatch):
    fake_groq = types.ModuleType("groq")
    fake_groq.Groq = _boom
    monkeypatch.setitem(sys.modules, "groq", fake_groq)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    out = stock_advisor._call_groq("prompt")
    assert out == "[Groq error: AI analysis unavailable]"
    assert SECRET not in out
