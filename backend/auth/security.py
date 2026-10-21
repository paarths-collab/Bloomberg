"""
Signed bearer-token authentication (guest identities).

Tokens are HS256 JWTs issued by POST /api/auth/guest. There are no passwords or
accounts: a token simply proves "this client was issued identity <sub>", which
is what per-user data isolation (paper portfolios, chat history) keys on.

Environment:
  AUTH_SECRET_KEY        HMAC secret (>= 32 chars recommended). If unset, a random
                         per-process secret is generated: tokens then do not survive
                         restarts and are not valid across workers/instances.
  AUTH_TOKEN_TTL_HOURS   Token lifetime in hours (default 720 = 30 days).
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"  # pinned: tokens signed with any other algorithm (incl. "none") are rejected
GUEST_TOKEN_TYPE = "guest"
DEFAULT_TTL_HOURS = 720.0
MIN_SECRET_LENGTH = 32
MAX_SUBJECT_LENGTH = 128
CLOCK_SKEW_LEEWAY_SECONDS = 30  # tolerate small clock differences between instances

_generated_secret: Optional[str] = None
_warned: set = set()

_bearer_scheme = HTTPBearer(auto_error=False, description="Guest token from POST /api/auth/guest")


def _warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message)


def get_secret() -> str:
    """Return the signing secret (env AUTH_SECRET_KEY, else a random per-process secret)."""
    global _generated_secret
    configured = os.getenv("AUTH_SECRET_KEY", "")
    if configured:
        if len(configured) < MIN_SECRET_LENGTH:
            _warn_once(
                "short_secret",
                f"AUTH_SECRET_KEY is shorter than {MIN_SECRET_LENGTH} characters; use a longer random secret.",
            )
        return configured
    if _generated_secret is None:
        _generated_secret = secrets.token_urlsafe(48)
        _warn_once(
            "generated_secret",
            "AUTH_SECRET_KEY is not set: using a random per-process secret. Auth tokens will not "
            "survive restarts and will not be valid across workers or instances.",
        )
    return _generated_secret


def get_token_ttl() -> timedelta:
    raw = os.getenv("AUTH_TOKEN_TTL_HOURS")
    hours = DEFAULT_TTL_HOURS
    if raw:
        try:
            parsed = float(raw)
            if parsed > 0 and parsed == parsed and parsed != float("inf"):
                hours = parsed
            else:
                raise ValueError(raw)
        except ValueError:
            _warn_once("bad_ttl", f"Invalid AUTH_TOKEN_TTL_HOURS={raw!r}; using default {DEFAULT_TTL_HOURS:g}.")
    return timedelta(hours=hours)


def new_guest_id() -> str:
    return f"guest_{uuid.uuid4().hex}"


def create_access_token(user_id: str, *, ttl: Optional[timedelta] = None) -> Tuple[str, datetime]:
    """Sign a token for ``user_id``. Returns (token, expiry as aware UTC datetime)."""
    now = datetime.now(timezone.utc)
    expires_at = now + (ttl if ttl is not None else get_token_ttl())
    claims = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "typ": GUEST_TOKEN_TYPE,
    }
    return jwt.encode(claims, get_secret(), algorithm=ALGORITHM), expires_at


def user_from_token(token: Optional[str]) -> Optional[str]:
    """Verify a token and return its subject, or None if it is missing/invalid/expired."""
    if not token or not isinstance(token, str):
        return None
    try:
        claims = jwt.decode(
            token,
            get_secret(),
            algorithms=[ALGORITHM],
            leeway=CLOCK_SKEW_LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    if claims.get("typ") != GUEST_TOKEN_TYPE:
        return None
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub or len(sub) > MAX_SUBJECT_LENGTH:
        return None
    return sub


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency: authenticated user id from ``Authorization: Bearer <token>``, else 401."""
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Not authenticated")
    user_id = user_from_token(credentials.credentials)
    if user_id is None:
        raise _unauthorized("Invalid or expired token")
    return user_id


def optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[str]:
    """FastAPI dependency: authenticated user id, or None (invalid tokens are treated as anonymous)."""
    if credentials is None:
        return None
    return user_from_token(credentials.credentials)


def anonymous_identity(session_id: str) -> str:
    """Stable pseudo-identity for an unauthenticated chat session (never equals a real user id)."""
    digest = hashlib.sha256(f"anon-session:{session_id}".encode("utf-8")).hexdigest()[:32]
    return f"anon_{digest}"
