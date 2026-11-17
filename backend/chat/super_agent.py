import asyncio
import logging
from fastapi import APIRouter, HTTPException
from .core.pipeline import InvestmentPipeline
from typing import Optional, Dict
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()
_pipeline: Optional[InvestmentPipeline] = None


def _get_pipeline() -> InvestmentPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = InvestmentPipeline()
    return _pipeline

class SuperAgentRequest(BaseModel):
    query: str
    # Important: default to None so ticker can be inferred from `query`.
    # Defaulting to "AAPL" caused NVDA (etc.) requests to be analyzed as Apple.
    ticker: Optional[str] = None
    market: Optional[str] = "us"
    portfolio: Optional[Dict[str, float]] = None
    session_id: Optional[str] = "default"
    approved_plan: Optional[Dict] = None

@router.post("/super-agent")
async def run_super_agent(payload: SuperAgentRequest):
    try:
        # Execute through Unified Pipeline
        # First call builds the pipeline (agent/client setup can block): keep it off the event loop.
        pipeline = await asyncio.to_thread(_get_pipeline)
        result = await pipeline.run(
            query=payload.query,
            ticker=payload.ticker,
            market=payload.market,
            portfolio=payload.portfolio,
            session_id=payload.session_id,
            approved_plan=payload.approved_plan
        )
        
        if str(result.get("report", "")).lower().startswith("error"):
            raise HTTPException(status_code=503, detail="AI analysis unavailable; check provider configuration")
        return result

    except HTTPException:
        raise
    except Exception:
        logger.exception("Super agent request failed")
        raise HTTPException(status_code=500, detail="Super agent request failed")
