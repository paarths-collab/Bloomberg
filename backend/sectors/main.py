import math
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Body, Depends
from backend.auth import require_user
from backend.database.connection import get_db

# Unified services
from .service import sectors_service, normalize_treemap_market, SUPPORTED_TREEMAP_MARKETS
from backend.services.technical_analysis import technical_service
from backend.services.market_data import market_service

# Sector Intel services
from .intel_service import (
    refresh_sector,
    list_latest_snapshots,
    recommend_sectors_for_user,
    get_sector_constituents,
    get_markets,
    normalize_market,
    resolve_sector,
)

# Localized services (To be retired)
from .core.fundamentals_service import get_fundamentals_summary
from .core.stock_sentiment_service import fetch_duckduckgo_news
from .core.sector_service import fetch_sector_performance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Sectors & Treemaps"])

def _sanitize_for_json(value):
    """Recursively replace non-finite floats with None for JSON compliance."""
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

def _snapshot_to_dict(snapshot):
    return {
        "id": snapshot.id,
        "sector": snapshot.sector,
        "market": snapshot.market,
        "as_of": snapshot.as_of.isoformat() if snapshot.as_of else None,
        "news_item_ids": snapshot.news_item_ids,
        "sector_summary": snapshot.sector_summary,
        "momentum": snapshot.momentum,
        "risk_notes": snapshot.risk_notes,
        "who_should_invest": snapshot.who_should_invest,
        "suitable_profiles": snapshot.suitable_profiles,
        "top_stocks": snapshot.top_stocks,
        "score": snapshot.score,
        "llm_model": snapshot.llm_model,
    }

# --- Treemap routes (/api/sectors/treemap/*) ---

def _treemap_market_or_400(market: str) -> str:
    key = normalize_treemap_market(market)
    if key is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported market. Supported markets: {', '.join(SUPPORTED_TREEMAP_MARKETS)}",
        )
    return key


def _intel_market_or_400(market: Any) -> str:
    code = normalize_market(market)
    if code is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported market. Supported markets: {', '.join(get_markets())}",
        )
    return code


def _int_field_or_400(payload: Dict[str, Any], name: str, default: Optional[int], lo: int, hi: int) -> Optional[int]:
    value = payload.get(name, default)
    if value is None:
        return None
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"'{name}' must be an integer")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit() and len(value.strip()) <= 9:
        value = int(value.strip())
    if not isinstance(value, int):
        raise HTTPException(status_code=400, detail=f"'{name}' must be an integer")
    if not lo <= value <= hi:
        raise HTTPException(status_code=400, detail=f"'{name}' must be between {lo} and {hi}")
    return value


# Plain `def` routes below: FastAPI runs them in its threadpool, so blocking provider/DB work
# does not stall the event loop.

@router.get("/treemap/indices")
def get_indices(market: str = Query("india")):
    market_key = _treemap_market_or_400(market)
    try:
        indices = sectors_service._get_market_indices(market_key) # Use the fast list
        return _sanitize_for_json({"market": market_key, "count": len(indices), "indices": indices})
    except Exception:
        logger.exception("Treemap indices error for market=%s", market_key)
        return {"market": market_key, "count": 0, "indices": [], "error": "indices_unavailable"}

@router.get("/treemap/indices/live")
def get_indices_live(market: str = Query("india")):
    market_key = _treemap_market_or_400(market)
    try:
        indices = sectors_service.get_indices_live(market_key)
        return _sanitize_for_json({"market": market_key, "count": len(indices), "indices": indices})
    except Exception:
        logger.exception("Treemap live error for market=%s", market_key)
        return {"market": market_key, "count": 0, "indices": [], "error": "indices_unavailable"}

@router.get("/treemap/index/{index_id}")
def get_index_stocks(
    index_id: str, 
    market: str = Query("india"), 
    include_prices: bool = Query(True)
):
    market_key = _treemap_market_or_400(market)
    data = sectors_service.get_index_constituents(index_id, market_key, include_prices)
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    return _sanitize_for_json(data)
    
@router.get("/treemap/stock/{symbol}")
def get_treemap_stock(symbol: str, market: str = Query("india")):
    from backend.services.market_data import market_service
    q_key = market_service.normalize_ticker(symbol, market)
    
    # 1. Fetch live quotes for latest price
    quotes = market_service.fetch_multiple_quotes([q_key])
    q = quotes.get(q_key, {})
    
    # 2. Fetch comprehensive info for fundamentals
    info = market_service.get_fundamentals(q_key)
    if not isinstance(info, dict):
        info = {}

    return _sanitize_for_json({
        "symbol": symbol,
        "name": info.get("shortName") or info.get("longName") or symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "price": {
            "current": q.get("price") or info.get("currentPrice") or info.get("regularMarketPrice"),
            "change": q.get("change"),
            "change_percent": q.get("change_percent"),
            "open": info.get("open"),
            "day_high": info.get("dayHigh"),
            "day_low": info.get("dayLow"),
            "week_52_high": info.get("fiftyTwoWeekHigh"),
            "week_52_low": info.get("fiftyTwoWeekLow"),
        },
        "valuation": {
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "enterprise_value": info.get("enterpriseValue"),
            "price_to_book": info.get("priceToBook"),
            "price_to_sales": info.get("priceToSalesTrailing12Months"),
        },
        "financials": {
            "revenue": info.get("totalRevenue"),
            "eps_trailing": info.get("trailingEps"),
            "net_income": info.get("netIncomeToCommon"),
            "profit_margin": info.get("profitMargins"),
            "return_on_equity": info.get("returnOnEquity"),
        },
        "dividends": {
            "dividend_yield": info.get("dividendYield"),
        },
        "volume": {
            "current": info.get("volume"),
            "avg_3m": info.get("averageVolume"),
        },
        "trading": {
            "beta": info.get("beta"),
        },
        "balance_sheet": {
            "total_debt": info.get("totalDebt"),
        },
        "analyst": {
            "recommendation": info.get("recommendationKey"),
            "target_mean": info.get("targetMeanPrice"),
            "num_analysts": info.get("numberOfAnalystOpinions"),
        },
        "company": {
            "description": info.get("longBusinessSummary"),
            "website": info.get("website"),
            "employees": info.get("fullTimeEmployees"),
            "country": info.get("country"),
        }
    })

# --- Performance and Treemap routes ---

@router.get("/performance")
def get_sector_performance():
    data = fetch_sector_performance()
    return {"name": "Market", "children": data}

# --- Legacy /api/sector-intel routes ---

@router.get("/intel/latest")
def get_intel_latest(market: Optional[str] = Query(None), sector: Optional[str] = Query(None), db=Depends(get_db)):
    market_code = _intel_market_or_400(market) if market else None
    if sector:
        snapshots = [s for s in list_latest_snapshots(db, market_code) if s.sector.lower() == sector.lower()]
        if not snapshots: raise HTTPException(status_code=404, detail="Not found")
        return _snapshot_to_dict(snapshots[0])
    snapshots = list_latest_snapshots(db, market_code)
    return [_snapshot_to_dict(s) for s in snapshots]

@router.post("/intel/refresh")
def refresh_intel(payload: dict = Body(...), db=Depends(get_db), _user: str = Depends(require_user)):
    """Refresh ONE sector snapshot (authenticated). Refresh-all is not available over HTTP:
    it sleeps between sectors and would hold a worker and DB session for many minutes."""
    market = _intel_market_or_400(payload.get("market"))
    raw_sector = payload.get("sector")
    if not isinstance(raw_sector, str) or not raw_sector.strip():
        raise HTTPException(status_code=400, detail="'sector' is required (one sector per request)")
    sector = resolve_sector(market, raw_sector)
    if sector is None:
        raise HTTPException(status_code=400, detail=f"Unknown sector for market {market}")
    force = payload.get("force", False)
    if not isinstance(force, bool):
        raise HTTPException(status_code=400, detail="'force' must be a boolean")
    res = refresh_sector(db, sector, market, force=force)
    db.commit()
    return res

@router.post("/intel/recommend")
def recommend_intel(payload: dict = Body(...), db=Depends(get_db)):
    market = _intel_market_or_400(payload.get("market", "US"))
    risk_score = _int_field_or_400(payload, "risk_score", None, 0, 100)
    limit = _int_field_or_400(payload, "limit", 5, 1, 50)
    return recommend_sectors_for_user(
        db,
        market=market,
        risk_score=risk_score,
        limit=limit,
    )

@router.get("/intel/stocks/{sector}")
def sector_intel_stocks(
    sector: str,
    market: str = Query("US"),
    limit: int = Query(10, ge=1, le=50),
    include_fundamentals: bool = Query(True),
    include_technicals: bool = Query(True),
):
    market_code = _intel_market_or_400(market)
    stocks = get_sector_constituents(market_code, sector, limit=limit)
    enriched = []
    for stock in stocks:
        sym = stock["symbol"]
        item = {**stock, "market": market_code}
        if include_fundamentals:
            item["fundamentals"] = market_service.get_fundamentals(sym)
        if include_technicals: 
             # Use the NEW unified TechnicalAnalysisService
             indicators = technical_service.calculate_indicators(sym, range_period="6mo", interval="1d", market=market_code)
             rsi_list = indicators.get("rsi")
             item["technicals"] = {"rsi": rsi_list[-1] if rsi_list else None}
        enriched.append(item)
    return _sanitize_for_json({"sector": sector, "market": market_code, "stocks": enriched})
