"""Auth routes: guest token issuance."""
from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from .rate_limit import enforce_guest_rate_limit, enforce_refresh_rate_limit
from .security import create_access_token, create_refresh_token, new_guest_id, user_from_refresh_token

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/guest")
def create_guest_token(request: Request):
    """Issue a bearer token for a new anonymous guest identity (no credentials needed).

    Rate limited per client and globally (see backend/auth/rate_limit.py); 429 + Retry-After.
    """
    enforce_guest_rate_limit(request)
    user_id = new_guest_id()
    return _credentials(user_id)


def _credentials(user_id):
    token, expires_at = create_access_token(user_id)
    return {
        "access_token": token,
        "refresh_token": create_refresh_token(user_id),
        "token_type": "bearer",
        "user_id": user_id,
        "expires_at": expires_at.isoformat(),
    }


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=8192)


@router.post("/refresh")
def refresh_guest_token(body: RefreshRequest, request: Request):
    """Renew credentials for an existing guest identity.

    Uses its own, more generous rate limiter (never /guest quota). Every attempt is counted,
    including rejected tokens, so invalid-token spam is not free; 429 + Retry-After when over limit.
    """
    enforce_refresh_rate_limit(request)
    user = user_from_refresh_token(body.refresh_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Guest credentials could not be renewed")
    return _credentials(user)
