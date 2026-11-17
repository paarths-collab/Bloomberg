"""Canonical authenticated profile and paper-portfolio routes at /api/profile."""
from fastapi import APIRouter

from backend.portfolio.investor_profile import (  # noqa: F401  (re-exported for compatibility)
    ProfilePayload,
    TradeRequest,
    execute_trade,
    get_portfolio,
    load_profile,
    save_profile,
    shared_router,
)

router = APIRouter(prefix="", tags=["Investor Profile"])
router.include_router(shared_router)
