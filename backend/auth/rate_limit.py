"""
In-memory sliding-window rate limiting for guest-token issuance (POST /api/auth/guest).

The endpoint is unauthenticated, so without a limit anyone can mint unlimited identities and
thereby sidestep every per-user quota (for example the experiment trial cap).

Environment (read at request time, so it can be changed without re-importing):
  AUTH_GUEST_RATE_LIMIT            Max tokens per client key per window (default 20; 0 disables).
  AUTH_GUEST_RATE_WINDOW_SECONDS   Window length in seconds (default 3600).
  AUTH_GUEST_GLOBAL_LIMIT          Max tokens across ALL clients per window (default 2000; 0 disables).
  AUTH_TRUST_PROXY                 Set to 1 to take the client key from X-Forwarded-For instead of
                                   the socket peer. Set it ONLY when the app sits behind proxies
                                   that append the address they saw to that header (Render,
                                   Vercel, ...); otherwise all clients appear to share the proxy IP
                                   and one noisy client exhausts everyone's quota. When the app is
                                   directly reachable it must stay unset: clients could forge the
                                   header to dodge the limit.
  AUTH_TRUST_PROXY_HOPS            Number of trusted proxies in front of the app (int >= 1,
                                   default 1; invalid -> 1). The client key is the Nth entry of
                                   X-Forwarded-For counted from the RIGHT (N = hops): proxies append,
                                   so entries to the left of those are client-supplied and
                                   spoofable. A wrong value is unsafe in both directions: too high
                                   -> a client-controlled entry is used (spoofable); too low -> the
                                   key is a proxy address and many users collapse into one key.
                                   If the header has fewer than N entries, or the entry is not a
                                   valid IP, the socket peer is used instead.

Client keys are normalised: IPv6 zone IDs are stripped, IPv4-mapped IPv6 (::ffff:a.b.c.d) maps to
the IPv4 address, and IPv6 addresses are keyed on their /64 (a single subscriber typically owns a
whole /64, so per-address keys would be trivially rotated).
Invalid or negative values fall back to the defaults (the limiter stays ON).

Limitations
  * State is PER PROCESS. With several workers or instances each one counts separately, so the
    effective limits are multiplied by the number of processes, and counters reset on restart.
    A multi-instance deployment needs a shared store (for example Redis) or an edge/WAF limit.
  * Memory is bounded: a key stores at most `limit` timestamps, expired entries are evicted, and
    at most MAX_TRACKED_KEYS keys are tracked (least recently active key is dropped first). The
    global ceiling still applies if an attacker churns through many client keys.
  * The global ceiling is a blunt instrument: roughly 100 clients (default 20 each; or one IPv6 /64
    if keys were mis-derived) can exhaust 2000/hour and block NEW guests. Holders of existing
    tokens are unaffected. Alert on 429 responses from this endpoint.
  * If the request has no client address, the per-client limit is skipped (key "unknown" would
    otherwise be one shared bucket) and only the global ceiling applies; one warning is logged.
  * An attacker can only evict other clients' keys by creating more than MAX_TRACKED_KEYS new keys
    inside a window, which the global ceiling prevents unless it is 0 or above MAX_TRACKED_KEYS.
  * Rejected requests are not counted, so Retry-After is the time until the oldest counted token
    leaves the window.
"""
from __future__ import annotations

import ipaddress
import logging
import math
import os
import threading
import time
from collections import OrderedDict, deque
from typing import Callable, Deque, Optional, Tuple

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

DEFAULT_PER_CLIENT_LIMIT = 20
DEFAULT_WINDOW_SECONDS = 3600
DEFAULT_GLOBAL_LIMIT = 2000
MAX_TRACKED_KEYS = 10_000
_UNKNOWN_CLIENT = "unknown"


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning("%s is not an integer; using default %s.", name, default)
        return default
    if value < minimum:
        logger.warning("%s must be >= %s; using default %s.", name, minimum, default)
        return default
    return value


class SlidingWindowLimiter:
    """Thread-safe per-key + global sliding-window counter (see module docstring)."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = MAX_TRACKED_KEYS,
    ) -> None:
        self._clock = clock
        self._max_keys = max(1, int(max_keys))
        self._lock = threading.Lock()
        self._per_key: "OrderedDict[str, Deque[float]]" = OrderedDict()
        self._global: Deque[float] = deque()

    @staticmethod
    def _expire(stamps: Deque[float], cutoff: float) -> None:
        while stamps and stamps[0] <= cutoff:
            stamps.popleft()

    @staticmethod
    def _retry_after(stamps: Deque[float], now: float, window: float) -> int:
        return max(1, math.ceil(stamps[0] + window - now))

    def _evict_expired_keys(self, cutoff: float) -> None:
        for key in [k for k, stamps in self._per_key.items() if not stamps or stamps[-1] <= cutoff]:
            del self._per_key[key]

    def tracked_keys(self) -> int:
        with self._lock:
            return len(self._per_key)

    def reset(self) -> None:
        with self._lock:
            self._per_key.clear()
            self._global.clear()

    def check(self, key: str, limit: int, window: float, global_limit: int) -> Optional[int]:
        """Record a token issuance for `key`. Returns None if allowed, else Retry-After seconds."""
        if window <= 0:
            window = DEFAULT_WINDOW_SECONDS
        with self._lock:
            now = self._clock()
            cutoff = now - window

            self._expire(self._global, cutoff)
            stamps = self._per_key.get(key)
            if stamps is not None:
                self._expire(stamps, cutoff)

            retry = 0
            if global_limit > 0 and len(self._global) >= global_limit:
                retry = max(retry, self._retry_after(self._global, now, window))
            if limit > 0 and stamps is not None and len(stamps) >= limit:
                retry = max(retry, self._retry_after(stamps, now, window))
            if retry:
                if stamps is not None:
                    self._per_key.move_to_end(key)
                return retry

            if limit > 0:
                if stamps is None:
                    if len(self._per_key) >= self._max_keys:
                        self._evict_expired_keys(cutoff)
                        while len(self._per_key) >= self._max_keys:
                            self._per_key.popitem(last=False)  # least recently active key
                    stamps = self._per_key[key] = deque()
                stamps.append(now)
                self._per_key.move_to_end(key)
            if global_limit > 0:
                self._global.append(now)
            return None


_limiter = SlidingWindowLimiter()


def reset_guest_limiter(clock: Optional[Callable[[], float]] = None) -> None:
    """Clear all limiter state (tests). Optionally replace the time function (default: monotonic)."""
    _limiter._clock = clock or time.monotonic
    _limiter.reset()


def get_guest_limiter() -> SlidingWindowLimiter:
    return _limiter


def _normalize_ip(raw: str) -> Optional[str]:
    """Canonical limiter key for an IP string, or None if it is not an IP address.

    IPv4 -> dotted quad; IPv4-mapped IPv6 -> the IPv4 address; IPv6 -> its /64 network
    (zone IDs such as "%eth0" are stripped first).
    """
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    raw = raw.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def _trusted_hops() -> int:
    return _env_int("AUTH_TRUST_PROXY_HOPS", 1, minimum=1)


def client_key(request: Request) -> str:
    """Client identity for rate limiting (see module docstring for the proxy rules).

    Returns the normalised socket peer, or - with AUTH_TRUST_PROXY=1 - the normalised
    X-Forwarded-For entry that is AUTH_TRUST_PROXY_HOPS places from the right. Returns "unknown"
    when there is no usable client address.
    """
    host = request.client.host if request.client and request.client.host else ""
    peer = (_normalize_ip(host) or host.strip()) or _UNKNOWN_CLIENT
    if os.getenv("AUTH_TRUST_PROXY", "").strip() == "1":
        joined = ",".join(request.headers.getlist("x-forwarded-for"))
        entries = [e.strip() for e in joined.split(",") if e.strip()]
        hops = _trusted_hops()
        if len(entries) >= hops:
            key = _normalize_ip(entries[-hops])
            if key is not None:
                return key
        # fewer entries than trusted hops, or not an IP: fall back to the peer
    return peer


def guest_rate_limit_config() -> Tuple[int, int, int]:
    """(per-client limit, window seconds, global limit), read from the environment now."""
    window = _env_int("AUTH_GUEST_RATE_WINDOW_SECONDS", DEFAULT_WINDOW_SECONDS) or DEFAULT_WINDOW_SECONDS
    return (
        _env_int("AUTH_GUEST_RATE_LIMIT", DEFAULT_PER_CLIENT_LIMIT),
        window,
        _env_int("AUTH_GUEST_GLOBAL_LIMIT", DEFAULT_GLOBAL_LIMIT),
    )


_warned_unknown_client = False


def _warn_unknown_client_once() -> None:
    global _warned_unknown_client
    if not _warned_unknown_client:
        _warned_unknown_client = True
        logger.warning(
            "Guest token request without a client address: per-client limit skipped, "
            "only the global ceiling applies."
        )


def enforce_guest_rate_limit(request: Request) -> None:
    """FastAPI helper: raise 429 + Retry-After when the caller (or the whole service) is over limit."""
    limit, window, global_limit = guest_rate_limit_config()
    if limit <= 0 and global_limit <= 0:
        return
    key = client_key(request)
    if key == _UNKNOWN_CLIENT:
        _warn_unknown_client_once()
        limit = 0  # no identity to key on: rely on the global ceiling alone
        if global_limit <= 0:
            return
    retry = _limiter.check(key, limit, window, global_limit)
    if retry is not None:
        logger.warning("Guest token issuance throttled (retry in %ss)", retry)
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry)},
        )
