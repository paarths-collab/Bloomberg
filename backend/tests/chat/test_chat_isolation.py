"""
Chat identity isolation: a client-supplied user_id must never select whose profile is read or
whose conversation is accessed; identity comes from the bearer token (or is anonymous).

Offline: no LLM/agent calls. backend/chat/chat.py and the orchestrator cannot be imported in this
checkout (they depend on modules that do not exist, e.g. backend.utils.json_safe and
backend.services.emotion_advisor_service), so those are stubbed just for these tests.
"""
import sys
import types
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.auth import security
from backend.main import app as main_app

SECRET_GOAL = "ALICE-PRIVATE-GOAL-7731"


def _token(user_id):
    return security.create_access_token(user_id)[0]


def _hdr(user_id):
    return {"Authorization": f"Bearer {_token(user_id)}"}


# --------------------------------------------------------------------------- recommend

@pytest.fixture
def wealth_calls(monkeypatch):
    """Stub the (missing) wealth workflow module and record what text reaches the 'LLM'."""
    calls = []

    class Manager:
        async def run_workflow(self, user_input, market):
            calls.append(user_input)
            return {"ok": True}

    for name in ("backend.finverse_integration", "backend.finverse_integration.routes"):
        pkg = types.ModuleType(name)
        pkg.__path__ = []
        monkeypatch.setitem(sys.modules, name, pkg)
    mod = types.ModuleType("backend.finverse_integration.routes.wealth_routes")
    mod.get_wealth_manager = lambda: Manager()
    mod.map_wealth_state_to_response = lambda result: {"mapped": True}
    monkeypatch.setitem(sys.modules, "backend.finverse_integration.routes.wealth_routes", mod)
    return calls


def test_recommend_ignores_client_supplied_user_id(wealth_calls):
    alice, bob = "guest_" + "a" * 32, "guest_" + "b" * 32
    with TestClient(main_app) as c:
        save = c.post("/api/profile/save", headers=_hdr(alice),
                      json={"name": "Alice", "age": 41, "primary_goal": SECRET_GOAL})
        assert save.status_code == 200, save.text

        # Alice (token) gets her own profile folded into the prompt
        r = c.post("/api/chat/stock-advisor/recommend", headers=_hdr(alice), json={"user_input": "ideas?"})
        assert r.status_code == 200, r.text
        assert SECRET_GOAL in wealth_calls[-1] and wealth_calls[-1].endswith("ideas?")

        # Bob names Alice in the body -> no leak
        wealth_calls.clear()
        r = c.post("/api/chat/stock-advisor/recommend", headers=_hdr(bob),
                   json={"user_input": "ideas?", "user_id": alice})
        assert r.status_code == 200
        assert wealth_calls == ["ideas?"]

        # anonymous, naming Alice -> no leak, no personalisation
        r = c.post("/api/chat/stock-advisor/recommend", json={"user_input": "ideas?", "user_id": alice})
        assert r.status_code == 200
        assert wealth_calls[-1] == "ideas?"

        # a forged/invalid token is anonymous, not "whoever it claims to be"
        r = c.post("/api/chat/stock-advisor/recommend", headers={"Authorization": "Bearer junk"},
                   json={"user_input": "ideas?", "user_id": alice})
        assert r.status_code == 200
        assert wealth_calls[-1] == "ideas?"
        assert all(SECRET_GOAL not in call for call in wealth_calls[1:])


def test_recommend_queries_profile_with_token_identity_only(wealth_calls, monkeypatch):
    """Direct check on the SQL parameter: token id, or no query at all for anonymous callers."""
    seen = []
    from backend.chat import stock_advisor

    class FakeDB:
        def execute(self, stmt, params=None):
            seen.append(params)
            return types.SimpleNamespace(mappings=lambda: types.SimpleNamespace(first=lambda: None))

    main_app.dependency_overrides[stock_advisor.get_db] = lambda: FakeDB()
    try:
        with TestClient(main_app) as c:
            bob = "guest_" + "b" * 32
            c.post("/api/chat/stock-advisor/recommend", headers=_hdr(bob),
                   json={"user_input": "x", "user_id": "guest_" + "a" * 32})
            assert seen == [{"uid": bob}]
            seen.clear()
            c.post("/api/chat/stock-advisor/recommend", json={"user_input": "x", "user_id": "guest_" + "a" * 32})
            assert seen == []
    finally:
        main_app.dependency_overrides.pop(stock_advisor.get_db, None)


# --------------------------------------------------------------------------- chat.py routes

@pytest.fixture
def chat_env(monkeypatch):
    """Import backend.chat.chat against stubs, with a real ChatOrchestrator session store."""
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

        orch = object.__new__(ChatOrchestrator)
        orch.conversations = {}
        identities = []

        async def process_message(session_id, user_message, user_id="default"):
            ctx = orch.get_or_create_conversation(session_id, user_id)  # real ownership logic
            ctx.add_message("user", user_message)
            identities.append(user_id)
            yield {"type": "text", "content": "ok", "metadata": {"user_id": ctx.user_id}}

        orch.process_message = process_message
        monkeypatch.setattr(chat_mod, "get_chat_orchestrator", lambda: orch)

        test_app = FastAPI()
        test_app.include_router(chat_mod.router)
        yield types.SimpleNamespace(mod=chat_mod, orch=orch, app=test_app, identities=identities)
    finally:
        for n, mod in saved.items():
            if mod is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = mod


ALICE, BOB = "guest_" + "a" * 32, "guest_" + "b" * 32


def test_rest_identity_comes_from_token_not_body(chat_env):
    c = TestClient(chat_env.app)
    r = c.post("/api/chat/message", headers=_hdr(ALICE), json={"message": "hi", "user_id": BOB, "session_id": "s1"})
    assert r.status_code == 200
    assert r.json()["responses"][0]["metadata"]["user_id"] == ALICE

    r = c.post("/api/chat/message", json={"message": "hi", "user_id": ALICE})  # anonymous
    anon = r.json()["responses"][0]["metadata"]["user_id"]
    assert anon.startswith("anon_") and anon not in (ALICE, BOB)

    r = c.post("/api/chat/message", headers={"Authorization": "Bearer junk"}, json={"message": "hi", "user_id": ALICE})
    assert r.json()["responses"][0]["metadata"]["user_id"].startswith("anon_")
    r = c.post("/api/chat/message", headers={"Authorization": "Bearer " + security.create_access_token(ALICE, ttl=timedelta(seconds=-120))[0]},
               json={"message": "hi"})
    assert r.json()["responses"][0]["metadata"]["user_id"].startswith("anon_")  # expired token != Alice


def test_sessions_cannot_be_read_or_hijacked_across_users(chat_env):
    c = TestClient(chat_env.app)
    assert c.post("/api/chat/message", headers=_hdr(ALICE),
                  json={"message": "my secret question", "session_id": "shared-id"}).status_code == 200

    # Bob and anonymous callers: cannot post into it, see no history, cannot clear it
    assert c.post("/api/chat/message", headers=_hdr(BOB),
                  json={"message": "x", "session_id": "shared-id"}).status_code == 403
    assert c.post("/api/chat/message", json={"message": "x", "session_id": "shared-id"}).status_code == 403
    for hdr in (_hdr(BOB), {}):
        hist = c.get("/api/chat/history/shared-id", headers=hdr).json()
        assert hist["count"] == 0 and hist["messages"] == []
        c.delete("/api/chat/history/shared-id", headers=hdr)
    assert chat_env.orch.conversations["shared-id"].user_id == ALICE  # not cleared, not replaced

    own = c.get("/api/chat/history/shared-id", headers=_hdr(ALICE)).json()
    assert own["count"] == 1 and own["messages"][0]["content"] == "my secret question"

    # session listing is scoped to the caller
    assert [s["session_id"] for s in c.get("/api/chat/sessions", headers=_hdr(ALICE)).json()["sessions"]] == ["shared-id"]
    assert c.get("/api/chat/sessions", headers=_hdr(BOB)).json()["sessions"] == []
    assert c.get("/api/chat/sessions").json()["sessions"] == []

    c.delete("/api/chat/history/shared-id", headers=_hdr(ALICE))
    assert "shared-id" not in chat_env.orch.conversations


def test_websocket_identity_from_token_only(chat_env):
    c = TestClient(chat_env.app)

    def talk(url, **kw):
        with c.websocket_connect(url, **kw) as ws:
            assert ws.receive_json()["type"] == "system"
            ws.send_json({"message": "hello"})
            assert ws.receive_json()["type"] == "user"
            return ws.receive_json()["metadata"]["user_id"]

    assert talk(f"/api/chat/ws?session_id=w1&token={_token(ALICE)}&user_id={BOB}") == ALICE
    assert talk(f"/api/chat/ws?session_id=w2&user_id={ALICE}").startswith("anon_")  # anonymous, claim ignored
    assert talk("/api/chat/ws?session_id=w3&token=garbage&user_id=" + ALICE).startswith("anon_")
    assert talk("/api/chat/ws?session_id=w4", headers={"Authorization": f"Bearer {_token(BOB)}"}) == BOB

    # Bob cannot attach to Alice's session
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/api/chat/ws?session_id=w1&token={_token(BOB)}"):
            pass
    # nor can an anonymous client
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/api/chat/ws?session_id=w1"):
            pass


def test_general_chat_history_is_namespaced_by_identity(chat_env, monkeypatch):
    class Client:
        async def create(self, messages):
            return types.SimpleNamespace(content="reply")

    monkeypatch.setattr(chat_env.mod, "get_model_client", lambda: (Client(), "fake"))
    chat_env.mod._general_sessions.clear()
    c = TestClient(chat_env.app)

    with c.websocket_connect(f"/api/chat/ws-general?session_id=g1&token={_token(ALICE)}") as ws:
        ws.receive_json()
        ws.send_json({"message": "alice says hi"})
        kinds = [ws.receive_json()["type"] for _ in range(3)]
        assert kinds == ["user", "thinking", "result"]

    own = c.get("/api/chat/general/history/g1", headers=_hdr(ALICE)).json()
    assert own["count"] == 2 and own["messages"][0]["content"] == "alice says hi"
    for hdr in (_hdr(BOB), {}):
        assert c.get("/api/chat/general/history/g1", headers=hdr).json()["count"] == 0
        c.delete("/api/chat/general/history/g1", headers=hdr)
    assert c.get("/api/chat/general/history/g1", headers=_hdr(ALICE)).json()["count"] == 2

    # Bob using the same session id gets a separate conversation
    with c.websocket_connect(f"/api/chat/ws-general?session_id=g1&token={_token(BOB)}") as ws:
        ws.receive_json()
        ws.send_json({"message": "bob here"})
        [ws.receive_json() for _ in range(3)]
    assert c.get("/api/chat/general/history/g1", headers=_hdr(BOB)).json()["messages"][0]["content"] == "bob here"
    assert c.get("/api/chat/general/history/g1", headers=_hdr(ALICE)).json()["messages"][0]["content"] == "alice says hi"
