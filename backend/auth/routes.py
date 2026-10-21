"""Auth routes: guest token issuance."""
from __future__ import annotations

from fastapi import APIRouter

from .security import create_access_token, new_guest_id

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/guest")
def create_guest_token():
    """Issue a bearer token for a new anonymous guest identity (no credentials needed)."""
    user_id = new_guest_id()
    token, expires_at = create_access_token(user_id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user_id,
        "expires_at": expires_at.isoformat(),
    }
