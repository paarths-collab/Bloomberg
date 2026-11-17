import math
import logging
from fastapi import APIRouter, HTTPException, Query

# Unified services
from backend.services.market_data import market_service
from backend.services.technical_analysis import technical_service
from backend.core.safe_yfinance import VALID_INTERVALS, VALID_PERIODS

from .eia_service import EIAService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Markets & Macro"])

def _sanitize_for_json(value):
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception as exc:
            logger.debug("Failed to coerce scalar value %r: %s", value, exc)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (int, str, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_json(v) for v in value]
    return str(value)

def _validate_range_interval(range_: str, interval: str) -> None:
    """400 for a range / interval the data provider does not support (not a misleading 404)."""
    if range_ not in VALID_PERIODS:
        raise HTTPException(status_code=400, detail="Unsupported range")
    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Unsupported interval")

# --- Market Data (Legacy /api/market) ---

@router.get("/overview")
def get_market_data_overview():
    data = market_service.get_market_overview()
    return _sanitize_for_json({"indices": data})

@router.get("/candles/{symbol}")
def get_market_candles(
    symbol: str, 
    interval: str = Query("1d"), 
    range: str = Query("1y"),
    market: str = Query("US")
):
    """Fetch OHLCV candles with market safety."""
    _validate_range_interval(range, interval)
    data = market_service.fetch_candles(symbol, interval, range, market=market)
    if not data: 
        raise HTTPException(status_code=404, detail=f"No candle data found for {symbol} in {market} market")
    return {"symbol": symbol, "market": market, "data": _sanitize_for_json(data)}

@router.get("/indicators/{symbol}")
def get_market_indicators(
    symbol: str, 
    interval: str = Query("1d"), 
    range: str = Query("1y"),
    market: str = Query("US")
):
    """Fetch technical indicators with market safety."""
    _validate_range_interval(range, interval)
    data = technical_service.calculate_indicators(symbol, range, interval, market=market)
    if not data: 
        raise HTTPException(status_code=404, detail=f"Failed to calculate indicators for {symbol}")
    return {"symbol": symbol, "market": market, "indicators": data}

# --- EIA Data (Legacy /api/eia) ---

@router.get("/eia/latest")
def get_eia_latest():
    """Returns a summary of petroleum data from EIA."""
    service = EIAService()
    if not service.api_key:
        raise HTTPException(status_code=503, detail="EIA data source is not configured")
    result = service.get_petroleum_summary()
    if result.get("error"):
        raise HTTPException(status_code=502, detail="EIA data request failed")
    return result

