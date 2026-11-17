"""
Global abuse protection (body-size cap, heavy-route rate limit and concurrency cap, /ws/live caps)
and JSON-safe 422 responses. All offline: heavy routes are hit with bodies that fail validation (422),
which still passes through the middleware, or with stubbed handlers.
"""
import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketDisconnect

from backend.common import abuse_protection as ap
from backend.common.abuse_protection import AbuseProtectionMiddleware
from backend.main import app

HEAVY = "/api/dashboard/sentiment"  # heavy path; an empty body fails validation (422) instantly


def _enable(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))


# --------------------------------------------------------------------------- (a) body size

async def test_oversized_content_length_is_413(client, monkeypatch):
    _enable(monkeypatch, MAX_REQUEST_BODY_BYTES=100)
    big = await client.post(HEAVY, content=b'{"message": "' + b"x" * 300 + b'"}',
                            headers={"content-type": "application/json"})
    assert big.status_code == 413
    small = await client.post(HEAVY, json={})
    assert small.status_code == 422  # under the cap: reaches validation


async def test_413_applies_to_every_route_not_only_heavy(client, monkeypatch):
    _enable(monkeypatch, MAX_REQUEST_BODY_BYTES=50)
    r = await client.post("/api/auth/refresh", content=b'{"refresh_token": "' + b"a" * 200 + b'"}',
                          headers={"content-type": "application/json"})
    assert r.status_code == 413


async def test_image_routes_get_the_larger_cap(client, monkeypatch):
    _enable(monkeypatch, MAX_REQUEST_BODY_BYTES=100, MAX_IMAGE_BODY_BYTES=1000)
    ok = await client.post("/api/backtest/interpret-image", content=b"x" * 500,
                           headers={"content-type": "application/json"})
    assert ok.status_code != 413
    too_big = await client.post("/api/backtest/interpret-image", content=b"x" * 1500,
                                headers={"content-type": "application/json"})
    assert too_big.status_code == 413
    # the same 500 bytes on a normal route is over the small cap
    other = await client.post(HEAVY, content=b"x" * 500, headers={"content-type": "application/json"})
    assert other.status_code == 413


async def test_streamed_body_without_content_length_is_413(client, monkeypatch):
    _enable(monkeypatch, MAX_REQUEST_BODY_BYTES=100)

    async def chunks():
        for _ in range(5):
            yield b"y" * 40  # 200 bytes total, no Content-Length (chunked)

    r = await client.post(HEAVY, content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert r.json()["detail"] == "Request body too large"

    async def small_chunks():
        yield b"{}"

    ok = await client.post(HEAVY, content=small_chunks(), headers={"content-type": "application/json"})
    assert ok.status_code == 422


async def test_413_works_on_a_plain_asgi_app_with_a_reading_handler(monkeypatch):
    """The cap holds even for a handler that swallows nothing and reads the stream itself."""
    _enable(monkeypatch, MAX_REQUEST_BODY_BYTES=100)
    mini = FastAPI()
    mini.add_middleware(AbuseProtectionMiddleware)

    from fastapi import Request

    @mini.post("/raw")
    async def raw(request: Request):
        return {"n": len(await request.body())}

    async with AsyncClient(transport=ASGITransport(app=mini), base_url="http://t") as c:
        assert (await c.post("/raw", content=b"a" * 50)).json() == {"n": 50}
        assert (await c.post("/raw", content=b"a" * 500)).status_code == 413


async def test_body_cap_zero_disables(client, monkeypatch):
    _enable(monkeypatch, MAX_REQUEST_BODY_BYTES=0)
    r = await client.post(HEAVY, content=b'{"message": "' + b"x" * 5000 + b'"}',
                          headers={"content-type": "application/json"})
    assert r.status_code != 413


# --------------------------------------------------------------------------- (b) rate limit

async def test_heavy_rate_limit_429_with_retry_after(client, monkeypatch):
    _enable(monkeypatch, HEAVY_RATE_LIMIT=3, HEAVY_RATE_WINDOW_SECONDS=3600)
    for _ in range(3):
        assert (await client.post(HEAVY, json={})).status_code == 422
    blocked = await client.post(HEAVY, json={})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    # one bucket across heavy routes
    assert (await client.post("/api/chat/super-agent", json={})).status_code == 429
    # non-heavy routes are untouched
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/api/news/live?cached_only=true")).status_code == 200
    # GET on the experiments list is not heavy; only POST /trials is
    for _ in range(3):
        assert (await client.get("/api/experiments/trials")).status_code != 429


async def test_experiments_trials_post_is_heavy(client, monkeypatch):
    _enable(monkeypatch, HEAVY_RATE_LIMIT=1)
    first = await client.post("/api/experiments/trials", json={})
    assert first.status_code != 429
    assert (await client.post("/api/experiments/trials", json={})).status_code == 429


@pytest.mark.parametrize("path,method", [
    ("/api/backtest/run", "POST"), ("/api/backtest/heatmap", "POST"), ("/api/backtest/report", "POST"),
    ("/api/backtest/quantstats-report", "POST"), ("/api/backtest/interpret", "POST"),
    ("/api/backtest/interpret-image", "POST"), ("/api/research/analyze", "POST"),
    ("/api/research/report", "POST"), ("/api/research/interpret-image", "POST"),
    ("/api/chat/super-agent", "POST"), ("/api/chat/stock-advisor/recommend", "POST"),
    ("/api/chat/stock-advisor/multi-pov", "POST"), ("/api/chat/sentiment/analyze/AAPL", "GET"),
    ("/api/chat/sentiment/quick/AAPL", "GET"), ("/api/dashboard/sentiment", "POST"),
    ("/api/dashboard/crowd-insight", "POST"), ("/api/sectors/intel/refresh", "POST"),
    ("/api/experiments/trials", "POST"), ("/api/backtest/run/", "POST"),
])
def test_heavy_pattern_matches(path, method):
    assert ap.is_heavy(path, method)


@pytest.mark.parametrize("path,method", [
    ("/health", "GET"), ("/api/news/live", "GET"), ("/api/backtest/strategies", "GET"),
    ("/api/backtest/report/download/x.html", "GET"), ("/api/experiments/trials", "GET"),
    ("/api/backtest/run", "OPTIONS"), ("/api/markets/candles/AAPL", "GET"),
])
def test_non_heavy_paths(path, method):
    assert not ap.is_heavy(path, method)


async def test_heavy_rate_limit_zero_disables(client, monkeypatch):
    _enable(monkeypatch, HEAVY_RATE_LIMIT=0)
    for _ in range(40):
        assert (await client.post(HEAVY, json={})).status_code == 422


async def test_config_is_read_per_request(client, monkeypatch):
    _enable(monkeypatch, HEAVY_RATE_LIMIT=1)
    assert (await client.post(HEAVY, json={})).status_code == 422
    assert (await client.post(HEAVY, json={})).status_code == 429
    monkeypatch.setenv("HEAVY_RATE_LIMIT", "0")
    assert (await client.post(HEAVY, json={})).status_code == 422


async def test_rate_limit_window_expires(client, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(ap._heavy_limiter, "_clock", lambda: clock["t"])
    _enable(monkeypatch, HEAVY_RATE_LIMIT=1, HEAVY_RATE_WINDOW_SECONDS=60)
    assert (await client.post(HEAVY, json={})).status_code == 422
    blocked = await client.post(HEAVY, json={})
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["retry-after"]) <= 60
    clock["t"] += 61
    assert (await client.post(HEAVY, json={})).status_code == 422


async def test_clients_are_keyed_proxy_aware(client, monkeypatch):
    _enable(monkeypatch, HEAVY_RATE_LIMIT=2, AUTH_TRUST_PROXY=1, AUTH_TRUST_PROXY_HOPS=1)

    def xff(ip):
        return {"x-forwarded-for": f"9.9.9.9, {ip}"}

    for _ in range(2):
        assert (await client.post(HEAVY, json={}, headers=xff("1.1.1.1"))).status_code == 422
    assert (await client.post(HEAVY, json={}, headers=xff("1.1.1.1"))).status_code == 429
    # a different client address (the entry the trusted proxy appended) has its own budget
    assert (await client.post(HEAVY, json={}, headers=xff("2.2.2.2"))).status_code == 422
    # the spoofable left-hand entry does not buy a fresh budget
    spoof = {"x-forwarded-for": "7.7.7.7, 1.1.1.1"}
    assert (await client.post(HEAVY, json={}, headers=spoof)).status_code == 429


async def test_xff_ignored_without_trust_proxy(client, monkeypatch):
    monkeypatch.delenv("AUTH_TRUST_PROXY", raising=False)
    _enable(monkeypatch, HEAVY_RATE_LIMIT=1)
    assert (await client.post(HEAVY, json={}, headers={"x-forwarded-for": "3.3.3.3"})).status_code == 422
    assert (await client.post(HEAVY, json={}, headers={"x-forwarded-for": "4.4.4.4"})).status_code == 429


async def test_preflight_is_never_throttled(client, monkeypatch):
    _enable(monkeypatch, HEAVY_RATE_LIMIT=1, HEAVY_MAX_CONCURRENCY=1)
    assert (await client.post(HEAVY, json={})).status_code == 422
    r = await client.options(HEAVY, headers={"origin": "http://localhost:3000",
                                             "access-control-request-method": "POST"})
    assert r.status_code == 200


async def test_rejections_carry_cors_headers(client, monkeypatch):
    _enable(monkeypatch, HEAVY_RATE_LIMIT=1)
    hdr = {"origin": "http://localhost:3000"}
    await client.post(HEAVY, json={}, headers=hdr)
    r = await client.post(HEAVY, json={}, headers=hdr)
    assert r.status_code == 429
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


# --------------------------------------------------------------------------- (c) concurrency

async def test_heavy_concurrency_cap_503_then_recovers(client, monkeypatch):
    import backend.chat.super_agent as sa

    started = asyncio.Event()
    release = asyncio.Event()

    class SlowPipeline:
        async def run(self, **kwargs):
            started.set()
            await release.wait()
            return {"report": "fine"}

    monkeypatch.setattr(sa, "_get_pipeline", lambda: SlowPipeline())
    _enable(monkeypatch, HEAVY_MAX_CONCURRENCY=1)

    first = asyncio.create_task(client.post("/api/chat/super-agent", json={"query": "hi"}))
    await asyncio.wait_for(started.wait(), 5)
    busy = await client.post("/api/chat/super-agent", json={"query": "hi"})
    assert busy.status_code == 503
    assert "busy" in busy.json()["detail"].lower()
    assert "retry-after" in busy.headers
    # non-heavy routes stay available while the heavy slot is taken
    assert (await client.get("/health")).status_code == 200
    release.set()
    assert (await first).status_code == 200
    assert (await client.post("/api/chat/super-agent", json={"query": "hi"})).status_code == 200


async def test_busy_rejection_does_not_burn_rate_quota(client, monkeypatch):
    import backend.chat.super_agent as sa

    started, release = asyncio.Event(), asyncio.Event()

    class SlowPipeline:
        async def run(self, **kwargs):
            started.set()
            await release.wait()
            return {"report": "ok"}

    monkeypatch.setattr(sa, "_get_pipeline", lambda: SlowPipeline())
    _enable(monkeypatch, HEAVY_MAX_CONCURRENCY=1, HEAVY_RATE_LIMIT=2)
    first = asyncio.create_task(client.post("/api/chat/super-agent", json={"query": "a"}))
    await asyncio.wait_for(started.wait(), 5)
    assert (await client.post("/api/chat/super-agent", json={"query": "b"})).status_code == 503
    release.set()
    assert (await first).status_code == 200
    # 1 slot used by `first`; the 503 did not count, so one more is still allowed
    assert (await client.post("/api/chat/super-agent", json={"query": "c"})).status_code == 200
    assert (await client.post("/api/chat/super-agent", json={"query": "d"})).status_code == 429


async def test_concurrency_slot_released_when_handler_raises(monkeypatch):
    _enable(monkeypatch, HEAVY_MAX_CONCURRENCY=1)
    mini = FastAPI()
    mini.add_middleware(AbuseProtectionMiddleware)

    @mini.post("/api/dashboard/sentiment")
    async def boom():
        raise RuntimeError("handler failure")

    async with AsyncClient(transport=ASGITransport(app=mini, raise_app_exceptions=False),
                           base_url="http://t") as c:
        for _ in range(3):
            assert (await c.post("/api/dashboard/sentiment")).status_code == 500
    assert ap._heavy_active.active == 0


# --------------------------------------------------------------------------- /ws/live

def test_ws_message_rate_limit_closes_with_policy_code(monkeypatch):
    _enable(monkeypatch, HEAVY_RATE_LIMIT=2)
    with TestClient(app) as tc:
        with tc.websocket_connect("/ws/live") as ws:
            for _ in range(2):
                ws.send_text("not json")
                assert ws.receive_json()["message"] == "Invalid JSON payload"
            ws.send_text("not json")
            err = ws.receive_json()
            assert err["status"] == "error" and err["retry_after"] >= 1
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
            assert exc.value.code == 1008
    assert ap._ws_active.active == 0


def test_ws_connection_cap_rejects_with_try_again_later(monkeypatch):
    _enable(monkeypatch, WS_MAX_CONNECTIONS=1)
    with TestClient(app) as tc:
        with tc.websocket_connect("/ws/live") as first:
            first.send_text("x")
            assert first.receive_json()["message"] == "Invalid JSON payload"
            with tc.websocket_connect("/ws/live") as second:
                err = second.receive_json()
                assert err["status"] == "error" and "connections" in err["message"]
                with pytest.raises(WebSocketDisconnect) as exc:
                    second.receive_text()
                assert exc.value.code == 1013
        # the slot frees when the first socket closes
        with tc.websocket_connect("/ws/live") as third:
            third.send_text("x")
            assert third.receive_json()["message"] == "Invalid JSON payload"
    assert ap._ws_active.active == 0


def test_ws_oversized_message_closes_1009(monkeypatch):
    _enable(monkeypatch, MAX_REQUEST_BODY_BYTES=50)
    with TestClient(app) as tc:
        with tc.websocket_connect("/ws/live") as ws:
            ws.send_text("z" * 200)
            assert ws.receive_json()["message"] == "Message too large"
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
            assert exc.value.code == 1009


def test_ws_non_object_json_is_rejected_not_crashed():
    with TestClient(app) as tc:
        with tc.websocket_connect("/ws/live") as ws:
            ws.send_text(json.dumps([1, 2]))
            assert ws.receive_json()["message"] == "Invalid JSON payload"


# --------------------------------------------------------------------------- JSON-safe 422

NAN_BODIES = [
    ("/api/dashboard/sentiment", b'{"message": NaN}'),
    ("/api/chat/super-agent", b'{"query": NaN}'),
    ("/api/chat/sentiment/analyze", b'{"symbol": NaN}'),
    ("/api/research/analyze", b'{"symbol": NaN}'),
    ("/api/technical/analyze", b'{"symbol": NaN, "strategy": "x"}'),
    ("/api/portfolio/api/long-term/analyze", b'{"ticker": NaN}'),
    ("/api/auth/refresh", b'{"refresh_token": NaN}'),
    ("/api/dashboard/sentiment", b'{"message": Infinity}'),
    ("/api/chat/super-agent", b'{"query": -Infinity}'),
    ("/api/dashboard/sentiment", b'{"message": 1e999}'),
]


@pytest.mark.parametrize("path,body", NAN_BODIES)
async def test_non_finite_json_in_wrong_typed_field_is_4xx_never_500(client, path, body):
    r = await client.post(path, content=body, headers={"content-type": "application/json"})
    assert 400 <= r.status_code < 500, (path, r.status_code, r.text[:200])
    r.json()  # body is valid JSON


async def test_validation_error_body_has_no_echoed_input(client):
    r = await client.post("/api/dashboard/sentiment", json={"message": {"nested": [1, 2]}, "market": 5})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail and all(set(e) <= {"type", "loc", "msg", "ctx"} for e in detail)
    assert all("input" not in e for e in detail)
    assert any(e["loc"][-1] == "message" for e in detail)


async def test_validation_handler_drops_non_finite_input_and_non_json_ctx():
    from fastapi.exceptions import RequestValidationError
    from backend.common.validation_errors import validation_exception_handler

    exc = RequestValidationError([{
        "type": "string_type", "loc": ("body", "x", 0), "msg": "Input should be a valid string",
        "input": float("nan"), "ctx": {"error": ValueError("boom"), "limit": 3, "bad": float("inf"), "name": "n"},
    }])
    resp = await validation_exception_handler(None, exc)
    payload = json.loads(resp.body)  # would raise if non-finite / non-JSON values leaked
    assert resp.status_code == 422
    assert payload["detail"] == [{
        "type": "string_type", "loc": ["body", "x", 0], "msg": "Input should be a valid string",
        "ctx": {"limit": 3, "name": "n"},
    }]
