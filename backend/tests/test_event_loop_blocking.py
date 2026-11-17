"""
Routes that do blocking I/O must not stall the event loop: while one is busy in a blocking call,
/health still answers promptly. Each test stubs the blocking call with time.sleep().
"""
import asyncio
import time

import pytest

BLOCK_SECONDS = 0.8
HEALTH_BUDGET = 0.35  # well below BLOCK_SECONDS; an event-loop stall would push /health past it


def _slow(*args, **kwargs):
    time.sleep(BLOCK_SECONDS)
    return {"symbol": "AAPL", "name": "Apple", "market_data": {"price": 1.0}, "price": 1.0,
            "sentiment": {}, "outlook": "neutral", "recommendation": "hold"}


async def _health_latency_during(client, slow_request):
    """Start the slow request, then /health right behind it; return (health latency, slow response).

    The clock starts BEFORE either task is created and stops when /health completes, so a handler that
    blocks the event loop delays /health by ~BLOCK_SECONDS (the health task cannot even start).
    """
    t0 = time.perf_counter()

    async def health():
        response = await client.get("/health")
        return time.perf_counter() - t0, response

    slow_task = asyncio.create_task(slow_request())
    health_task = asyncio.create_task(health())
    elapsed, response = await health_task
    assert response.status_code == 200
    return elapsed, await slow_task


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/chat/sentiment/analyze/AAPL", None),
    ("get", "/api/chat/sentiment/quick/AAPL", None),
    ("post", "/api/chat/sentiment/analyze", {"symbol": "AAPL"}),
])
async def test_sentiment_routes_do_not_block_the_loop(client, monkeypatch, method, path, body):
    import backend.chat.sentiment as sentiment

    monkeypatch.setattr(sentiment, "analyze_stock_sentiment", _slow)

    def request():
        return client.get(path) if method == "get" else client.post(path, json=body)

    elapsed, response = await _health_latency_during(client, request)
    assert response.status_code == 200
    assert elapsed < HEALTH_BUDGET, f"/health took {elapsed:.2f}s while a sentiment call blocked"


async def test_sentiment_batch_does_not_block_the_loop(client, monkeypatch):
    import backend.chat.sentiment as sentiment

    monkeypatch.setattr(sentiment, "analyze_multiple_stocks", lambda symbols: [_slow() for _ in symbols[:1]])
    elapsed, response = await _health_latency_during(
        client, lambda: client.post("/api/chat/sentiment/batch", json={"symbols": ["AAPL"]}))
    assert response.status_code == 200
    assert elapsed < HEALTH_BUDGET


async def test_super_agent_pipeline_construction_does_not_block_the_loop(client, monkeypatch):
    import backend.chat.super_agent as super_agent

    class Pipeline:
        async def run(self, **kwargs):
            return {"report": "fine"}

    def slow_factory():
        time.sleep(BLOCK_SECONDS)  # e.g. first-call agent / client construction
        return Pipeline()

    monkeypatch.setattr(super_agent, "_get_pipeline", slow_factory)
    elapsed, response = await _health_latency_during(
        client, lambda: client.post("/api/chat/super-agent", json={"query": "hello"}))
    assert response.status_code == 200
    assert elapsed < HEALTH_BUDGET


async def test_pipeline_run_does_not_block_the_loop_on_trade_levels(monkeypatch):
    """InvestmentPipeline.run (used by /api/chat/super-agent and /ws/live) runs get_levels off-loop."""
    from backend.chat.core.pipeline import InvestmentPipeline

    class Levels:
        def get_levels(self, ticker):
            time.sleep(BLOCK_SECONDS)
            return {"current_price": 10.0, "stop_loss": 9.0}

    class Memory:
        def add(self, **kwargs):
            time.sleep(0.2)

    pipeline = InvestmentPipeline.__new__(InvestmentPipeline)
    pipeline._agent = None
    pipeline.trade_levels = Levels()
    pipeline.memory = Memory()
    pipeline.sizing = type("S", (), {"fixed_fraction": lambda self, capital: {"shares": 1}})()

    gaps = []

    async def heartbeat():
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.02)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    beat = asyncio.create_task(heartbeat())
    try:
        result = await pipeline.run(query="analyze", ticker="AAPL", market="us")
    finally:
        beat.cancel()
    assert result["strategy"]["trade_levels"]["current_price"] == 10.0
    assert gaps and max(gaps) < 0.3, f"event loop stalled for {max(gaps):.2f}s"


async def test_ws_live_pipeline_construction_does_not_block_the_loop(monkeypatch):
    import backend.main as main

    def slow_factory():
        time.sleep(BLOCK_SECONDS)
        raise RuntimeError("stop after the blocking part")

    monkeypatch.setattr(main, "_get_pipeline", slow_factory)
    # The websocket handler wraps the factory in asyncio.to_thread; assert the wrapper is used
    # by driving the handler against a fake socket while a heartbeat runs.
    sent = []

    class FakeSocket:
        client = type("C", (), {"host": "127.0.0.1"})()
        headers = type("H", (), {"getlist": lambda self, name: []})()
        scope = {"type": "websocket"}

        def __init__(self):
            self._messages = ['{"query": "hi"}']

        async def accept(self):
            pass

        async def receive_text(self):
            if self._messages:
                return self._messages.pop(0)
            raise main.WebSocketDisconnect()

        async def send_json(self, data):
            sent.append(data)

        async def close(self, code=1000):
            pass

    gaps = []

    async def heartbeat():
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.02)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    beat = asyncio.create_task(heartbeat())
    try:
        await main.websocket_endpoint(FakeSocket())
    finally:
        beat.cancel()
    assert gaps and max(gaps) < 0.3, f"event loop stalled for {max(gaps):.2f}s"


async def test_stock_advisor_recommend_profile_query_runs_off_the_loop(client, monkeypatch):
    import backend.chat.stock_advisor as advisor
    from backend.auth import security

    def slow_profile(db, user):
        time.sleep(BLOCK_SECONDS)
        return ""

    monkeypatch.setattr(advisor, "_load_profile_context", slow_profile)
    token = security.create_access_token("blocking-test-user")[0]
    elapsed, _ = await _health_latency_during(
        client,
        lambda: client.post("/api/chat/stock-advisor/recommend", json={"user_input": "ideas?"},
                            headers={"Authorization": f"Bearer {token}"}),
    )
    assert elapsed < HEALTH_BUDGET
