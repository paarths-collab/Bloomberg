import logging
from fastapi import APIRouter, HTTPException
from .core.graph_service import get_network_graph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Network Graph"])

@router.get("/{symbol}")
def get_graph(symbol: str):
    """
    Returns nodes and links for D3 Force-Directed Graph.
    """
    try:
        data = get_network_graph(symbol)
        return data
    except Exception:
        logger.exception("Network graph failed for %s", symbol)
        raise HTTPException(status_code=500, detail="Network graph request failed")
