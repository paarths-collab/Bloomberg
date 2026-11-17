"""Advanced portfolio analysis; investor records live at /api/profile."""
from fastapi import APIRouter
from .long_term import router as long_term_router

router = APIRouter(tags=["Portfolio"])
router.include_router(long_term_router)
