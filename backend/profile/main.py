"""
Profile routes mounted at /api/profile (save, load, trade, portfolio).

This is a thin alias: the implementation is shared with
/api/portfolio/api/investor-profile/* and lives in backend/portfolio/investor_profile.py.
"""
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
