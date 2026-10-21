"""
Error text must not leak to clients: handlers log the full exception server-side and return a
generic message while keeping the response shape and status codes.

Offline: every inner call that would reach a market/LLM/wealth service is monkeypatched to raise.
backend/chat/chat.py and the orchestrator are stubbed the same way as in
backend/tests/chat/test_chat_isolation.py (their optional dependencies are missing in this checkout).
"""
import asyncio
import sys
import types

import pytest
from fastapi.testclient import TestClient

from backend.main import app as main_app

SECRET = "secret-token-XYZ"


# --------------------------------------------------------------------------- peers compare

def test_peers_compare_hides_exception_text(monkeypatch):
    from backend.technical import main as technical_main

    def boom(symbol, limit=12):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(technical_main, "fetch_peer_comparison", boom)
    with TestClient(main_app) as c:
        r = c.get("/api/technical/peers/compare/AAPL")
    assert r.status_code == 200
    assert SECRET not in r.text
    assert r.json() == {"symbol": "AAPL", "error": "Peer comparison failed", "rows": []}


# --------------------------------------------------------------------------- stock advisor

def test_stock_advisor_recommend_hides_exception_text(monkeypatch):
    class Manager:
        async def run_workflow(self, user_input, market):
            raise RuntimeError(SECRET)

    pkg_names = ("backend.finverse_integration", "backend.finverse_integration.routes")
    for name in pkg_names:
        pkg = types.ModuleType(name)
        pkg.__path__ = []
        monkeypatch.setitem(sys.modules, name, pkg)
    mod = types.ModuleType("backend.finverse_integration.routes.wealth_routes")
    mod.get_wealth_manager = lambda: Manager()
    mod.map_wealth_state_to_response = lambda result: {"mapped": True}
    monkeypatch.setitem(sys.modules, "backend.finverse_integration.routes.wealth_routes", mod)

    with TestClient(main_app) as c:
        r = c.post("/api/chat/stock-advisor/recommend", json={"user_input": "ideas?"})
    assert r.status_code == 500
    assert SECRET not in r.text
    assert r.json()["detail"] == "Stock advisor request failed"


def test_stock_advisor_multi_pov_hides_exception_text(monkeypatch):
    from backend.chat import stock_advisor

    def boom(symbol, market, context=""):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(stock_advisor, "_run_multi_pov_langgraph", boom)
    with TestClient(main_app) as c:
        r = c.post("/api/chat/stock-advisor/multi-pov", json={"symbol": "AAPL", "market": "us"})
    assert r.status_code == 500
    assert SECRET not in r.text
    assert r.json()["detail"] == "Stock advisor request failed"


# --------------------------------------------------------------------------- chat orchestrator / chat.py

@pytest.fixture
def stubbed_chat(monkeypatch):
    """Import backend.chat.chat / orchestrator against the same stubs as test_chat_isolation.py."""
    names = ("backend.chat.chat", "backend.chat.orchestrator", "backend.chat.intent_router",
             "backend.chat.autogen_setup")
    saved = {n: sys.modules.pop(n, None) for n in names}

    pipelines = types.ModuleType("backend.chat.pipelines")
    pipelines.PipelineManager = type("PipelineManager", (), {})
    pipelines.PipelineResult = type("PipelineResult", (), {})
    pipelines.get_pipeline_manager = lambda: pipelines.PipelineManager()
    monkeypatch.setitem(sys.modules, "backend.chat.pipelines", pipelines)
    utils = types.ModuleType("backend.utils")
    utils.__path__ = []
    json_safe = types.ModuleType("backend.utils.json_safe")
    json_safe.make_json_safe = lambda value: value
    monkeypatch.setitem(sys.modules, "backend.utils", utils)
    monkeypatch.setitem(sys.modules, "backend.utils.json_safe", json_safe)

    try:
        import backend.chat.chat as chat_mod
        from backend.chat.orchestrator import ChatOrchestrator
        yield types.SimpleNamespace(chat=chat_mod, orch_cls=ChatOrchestrator)
    finally:
        for n, mod in saved.items():
            if mod is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = mod


def test_orchestrator_error_payload_hides_exception_text(stubbed_chat, monkeypatch):
    orch = object.__new__(stubbed_chat.orch_cls)
    orch.conversations = {}

    async def boom(ctx, message):
        raise RuntimeError(SECRET)
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(orch, "_handle_new_message", boom, raising=False)

    async def collect():
        return [chunk async for chunk in orch.process_message("err-session", "hi", "anon_test")]

    chunks = asyncio.run(collect())
    errors = [c for c in chunks if c["type"] == "error"]
    assert len(errors) == 1
    assert SECRET not in repr(errors[0])
    assert errors[0]["metadata"] == {"error": "Chat request failed"}


def test_general_chat_failure_text_hidden(stubbed_chat, monkeypatch):
    chat_mod = stubbed_chat.chat

    class Client:
        async def create(self, messages):
            raise RuntimeError(SECRET)

    monkeypatch.setattr(chat_mod, "get_model_client", lambda: (Client(), "fake"))
    chat_mod._general_sessions.clear()

    content, provider = asyncio.run(chat_mod._get_general_response("g-err", "hi", "anon_test"))
    assert SECRET not in content
    assert content == "⚠️ Chat request failed. Please try again."
    assert provider == "fake"
    chat_mod._general_sessions.clear()
