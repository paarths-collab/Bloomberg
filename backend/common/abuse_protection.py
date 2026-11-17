"""
Global abuse protection for unauthenticated heavy / LLM routes.

One pure-ASGI middleware (`AbuseProtectionMiddleware`) applies, per request:

  (a) request-body size cap: MAX_REQUEST_BODY_BYTES (default 1_000_000), or MAX_IMAGE_BODY_BYTES
      (default 6_000_000) for paths ending in /interpret-image. Enforced on Content-Length (rejected
      before the body is read) AND on the streamed size (chunked bodies without Content-Length).
      413 when exceeded. 0 disables.
  (b) per-client sliding-window rate limit on HEAVY paths (see HEAVY_PATTERNS): HEAVY_RATE_LIMIT
      requests per HEAVY_RATE_WINDOW_SECONDS per client (default 30 / 3600; 0 disables). 429 plus
      Retry-After. One bucket per client across all heavy routes.
  (c) process-wide concurrency cap on heavy routes: HEAVY_MAX_CONCURRENCY (default 4; 0 disables).
      503 plus Retry-After when exceeded.

The client key is the proxy-aware `client_key` used by the auth limiters (AUTH_TRUST_PROXY /
AUTH_TRUST_PROXY_HOPS). Configuration is read on every request. State is per process (see
backend/auth/rate_limit.py for the same limitations). WebSocket /ws/live uses the helpers at the bottom
(`ws_*`): per-client message rate (same HEAVY_RATE_* values, own bucket) and WS_MAX_CONNECTIONS
concurrent connections (default 20; 0 disables).
"""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.auth.rate_limit import SlidingWindowLimiter, _env_int, client_key, _UNKNOWN_CLIENT

logger = logging.getLogger(__name__)

DEFAULT_MAX_BODY_BYTES = 1_000_000
DEFAULT_MAX_IMAGE_BODY_BYTES = 6_000_000
DEFAULT_HEAVY_RATE_LIMIT = 30
DEFAULT_HEAVY_WINDOW_SECONDS = 3600
DEFAULT_HEAVY_MAX_CONCURRENCY = 4
DEFAULT_WS_MAX_CONNECTIONS = 20

# (compiled full-match path regex, allowed methods or None for any non-OPTIONS method)
HEAVY_PATTERNS: List[Tuple["re.Pattern[str]", Optional[frozenset]]] = [
    (re.compile(r"/api/backtest/(run|heatmap|report|quantstats-report|interpret|interpret-image)"), None),
    (re.compile(r"/api/research/(analyze|report|interpret-image)"), None),
    (re.compile(r"/api/chat/(super-agent|stock-advisor/.*|sentiment/.*)"), None),
    (re.compile(r"/api/dashboard/(sentiment|crowd-insight)"), None),
    (re.compile(r"/api/sectors/intel/refresh"), None),
    (re.compile(r"/api/experiments/trials"), frozenset({"POST"})),
]

_heavy_limiter = SlidingWindowLimiter()
_ws_limiter = SlidingWindowLimiter()
_unknown_warned = False


class BodyTooLarge(HTTPException):
    """Raised from the wrapped `receive` when a streamed body passes the cap (handled as 413)."""

    def __init__(self) -> None:
        super().__init__(status_code=413, detail="Request body too large")


class _Counter:
    """Thread-safe active-count with a check-and-increment."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0

    def try_enter(self, cap: int) -> bool:
        with self._lock:
            if cap > 0 and self.active >= cap:
                return False
            self.active += 1
            return True

    def leave(self) -> None:
        with self._lock:
            self.active = max(0, self.active - 1)

    def reset(self) -> None:
        with self._lock:
            self.active = 0


_heavy_active = _Counter()
_ws_active = _Counter()


def reset_abuse_protection() -> None:
    """Clear all limiter / counter state (tests)."""
    _heavy_limiter.reset()
    _ws_limiter.reset()
    _heavy_active.reset()
    _ws_active.reset()


def max_body_bytes(path: str) -> int:
    if path.rstrip("/").endswith("/interpret-image"):
        return _env_int("MAX_IMAGE_BODY_BYTES", DEFAULT_MAX_IMAGE_BODY_BYTES)
    return _env_int("MAX_REQUEST_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)


def is_heavy(path: str, method: str) -> bool:
    method = (method or "").upper()
    if method == "OPTIONS":
        return False
    norm = path.rstrip("/") or "/"
    for pattern, methods in HEAVY_PATTERNS:
        if pattern.fullmatch(norm) and (methods is None or method in methods):
            return True
    return False


def heavy_rate_config() -> Tuple[int, int]:
    """(per-client limit, window seconds), read from the environment now."""
    window = _env_int("HEAVY_RATE_WINDOW_SECONDS", DEFAULT_HEAVY_WINDOW_SECONDS) or DEFAULT_HEAVY_WINDOW_SECONDS
    return _env_int("HEAVY_RATE_LIMIT", DEFAULT_HEAVY_RATE_LIMIT), window


def _check_rate(limiter: SlidingWindowLimiter, conn: HTTPConnection) -> Optional[int]:
    """Retry-After seconds when the client is over the heavy limit, else None."""
    global _unknown_warned
    limit, window = heavy_rate_config()
    if limit <= 0:
        return None
    key = client_key(conn)
    if key == _UNKNOWN_CLIENT:
        # No identity to key on: one shared bucket would let one caller starve everyone.
        if not _unknown_warned:
            _unknown_warned = True
            logger.warning("Heavy-route request without a client address: per-client limit skipped.")
        return None
    return limiter.check(key, limit, window, 0)


async def _send_json(send: Send, status: int, detail: str, headers: Optional[Dict[str, str]] = None) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    raw_headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    for name, value in (headers or {}).items():
        raw_headers.append((name.lower().encode("latin-1"), value.encode("latin-1")))
    await send({"type": "http.response.start", "status": status, "headers": raw_headers})
    await send({"type": "http.response.body", "body": body})


class AbuseProtectionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET")
        if method.upper() == "OPTIONS":  # CORS preflight carries no body and costs nothing
            await self.app(scope, receive, send)
            return

        # (a) body size: Content-Length first (reject before reading anything)
        limit = max_body_bytes(path)
        if limit > 0:
            for name, value in scope.get("headers", []):
                if name == b"content-length":
                    try:
                        declared = int(value.decode("latin-1").strip())
                    except ValueError:
                        break  # malformed: the streamed check below still applies
                    if declared > limit:
                        await _send_json(send, 413, "Request body too large")
                        return
                    break

        heavy = is_heavy(path, method)
        entered = False
        if heavy:
            # (c) concurrency first so a "busy" rejection does not burn the client's rate quota
            cap = _env_int("HEAVY_MAX_CONCURRENCY", DEFAULT_HEAVY_MAX_CONCURRENCY)
            if not _heavy_active.try_enter(cap):
                await _send_json(send, 503, "Server is busy, try again shortly.", {"Retry-After": "5"})
                return
            entered = True
            try:
                # (b) per-client rate limit
                retry = _check_rate(_heavy_limiter, HTTPConnection(scope))
            except BaseException:
                _heavy_active.leave()
                raise
            if retry is not None:
                _heavy_active.leave()
                logger.warning("Heavy route %s throttled (retry in %ss)", path, retry)
                await _send_json(
                    send, 429, "Too many requests. Please try again later.", {"Retry-After": str(retry)}
                )
                return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if limit > 0 and message["type"] == "http.request":
                received += len(message.get("body", b"") or b"")
                if received > limit:
                    raise BodyTooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            if not response_started:
                await _send_json(send, 413, "Request body too large")
        finally:
            if entered:
                _heavy_active.leave()


# ---------------------------------------------------------------------------
# WebSocket /ws/live helpers
# ---------------------------------------------------------------------------

def ws_try_connect() -> bool:
    """Reserve a connection slot; False when WS_MAX_CONNECTIONS is reached. Pair with ws_disconnect()."""
    return _ws_active.try_enter(_env_int("WS_MAX_CONNECTIONS", DEFAULT_WS_MAX_CONNECTIONS))


def ws_disconnect() -> None:
    _ws_active.leave()


def ws_check_message(conn: HTTPConnection) -> Optional[int]:
    """Count one inbound message for this client; Retry-After seconds when over the limit, else None."""
    return _check_rate(_ws_limiter, conn)


def ws_max_message_bytes() -> int:
    return _env_int("MAX_REQUEST_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)
