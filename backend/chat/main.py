"""Canonical chat feature routers; research is mounted separately at /api/research."""
from fastapi import APIRouter
from .super_agent import router as super_agent_router
from .stock_advisor import router as stock_advisor_router
from .sentiment import router as sentiment_router

router = APIRouter(tags=["AI Chat"])
router.include_router(super_agent_router)
router.include_router(stock_advisor_router)
router.include_router(sentiment_router)
