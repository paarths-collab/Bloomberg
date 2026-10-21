import logging
from fastapi import APIRouter, HTTPException, Query
from .service import fetch_stock_peers
from .comparison_service import fetch_peer_comparison
from .core.json_utils import make_json_safe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Peers"])


@router.get("/compare/{symbol}")
def get_peer_comparison(
    symbol: str,
    limit: int = Query(12, ge=3, le=40),
    debug: bool = Query(False)
):
    """
    Get peer comparison metrics for a stock.
    """
    try:
        data = fetch_peer_comparison(symbol, limit=limit, debug=debug)
        return make_json_safe(data)
    except Exception:
        logger.exception("Error fetching peer comparison for %s", symbol)
        # Never propagate provider/config failures as a hard 500 to the UI.
        # Return a minimal shape so frontend can render gracefully.
        fallback_symbol = symbol.strip().upper()
        fallback = {
            "symbol": fallback_symbol,
            "count": 1,
            "rows": [
                {
                    "symbol": fallback_symbol,
                    "name": fallback_symbol,
                    "price": None,
                    "pe": None,
                    "market_cap": None,
                    "div_yield": None,
                    "net_profit_q": None,
                    "profit_q_var": None,
                    "sales_q": None,
                    "sales_q_var": None,
                    "roce": None,
                }
            ],
            "partial": True,
            "message": "Peer comparison data source temporarily unavailable. Showing fallback row.",
        }
        if debug:
            # `debug` is client-controlled, so never echo the exception text here.
            fallback["error"] = "Peer comparison failed"
        return make_json_safe(fallback)


@router.get("/{symbol}")
def get_peers(symbol: str):
    """
    Get peer companies for a stock.
    """
    try:
        peers = fetch_stock_peers(symbol)

        return {
            "symbol": symbol.upper(),
            "peers": peers,
            "count": len(peers),
            "source": "Financial Modeling Prep",
        }

    except Exception:
        logger.exception("Error fetching peers for %s", symbol)
        raise HTTPException(status_code=500, detail="Failed to fetch peers")
