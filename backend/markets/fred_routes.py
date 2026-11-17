"""
FRED Data Routes - API endpoints for FRED index data
"""
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import json
import logging
import re
from backend.auth import require_user
from backend.markets.fred_service import FredUnavailable
from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from pydantic import BaseModel

from backend.markets.fred_service import FredDataService, ALL_DEFAULT_SERIES
from backend.database.connection import get_db_session
from backend.database.models import FredData


router = APIRouter(
    prefix="/fred",
    tags=["FRED Data"]
)

GOLD_SERIES_IDS = {"GOLDAMGBD228NLBM"}
logger = logging.getLogger(__name__)


def _fetch_gold_price_from_yf(max_age_hours: int = 12) -> Optional[Dict[str, Any]]:
    cache_path = Path(__file__).resolve().parents[1] / "cache" / "gold_price.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_at = payload.get("cached_at")
            if cached_at:
                cached_dt = datetime.fromisoformat(cached_at)
                if datetime.utcnow() - cached_dt < timedelta(hours=max_age_hours):
                    return payload.get("payload")
        except Exception as exc:
            logger.debug("Failed to read cached gold price payload: %s", exc)

    try:
        import yfinance as yf
    except Exception as exc:
        logger.debug("Failed to fetch gold price from yfinance: %s", exc)
        return None

    try:
        symbols = ["XAUUSD=X", "GC=F", "GOLD"]
        price = None
        prev = None
        used_symbol = None
        for symbol in symbols:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            if hist.empty:
                continue
            closes = hist["Close"].dropna()
            if closes.empty:
                continue
            last = closes.iloc[-1]
            prev_close = closes.iloc[-2] if len(closes) > 1 else None
            if last is not None and last > 0:
                price = float(last)
                prev = float(prev_close) if prev_close is not None else None
                used_symbol = symbol
                break
        if price is None:
            return None

        change = (price - prev) if (price is not None and prev is not None) else None
        change_pct = (change / prev * 100) if (change is not None and prev not in (None, 0)) else None

        payload = {
            "value": price,
            "previous": prev,
            "change": change,
            "change_pct": change_pct,
            "date": date.today().isoformat(),
            "symbol": used_symbol,
            "status": "success",
        }
        cache_path.write_text(
            json.dumps({"cached_at": datetime.utcnow().isoformat(), "payload": payload}),
            encoding="utf-8",
        )
        return payload
    except Exception:
        return None


# ============ Input validation ============

SERIES_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
MAX_SERIES_IDS = 25
MAX_DAYS = 3650
MAX_AGE_HOURS_LIMIT = 24 * 365
SERIES_TYPES = {"index", "rate", "economic", "commodity", "fx", "spread"}


def _check_series_id(series_id: str) -> str:
    if not isinstance(series_id, str) or not SERIES_ID_RE.fullmatch(series_id):
        raise HTTPException(status_code=422, detail="Invalid series ID")
    return series_id


def _parse_series_ids(raw: Optional[str], default: Optional[List[str]] = None, max_ids: int = MAX_SERIES_IDS) -> Optional[List[str]]:
    """Split a comma-separated id list, validate each id and cap the count."""
    if not raw:
        return default
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    if not ids:
        return default
    if len(ids) > max_ids or any(not SERIES_ID_RE.fullmatch(i) for i in ids):
        raise HTTPException(status_code=422, detail="Invalid series IDs")
    return ids


def _check_days(days: int) -> int:
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= MAX_DAYS:
        raise HTTPException(status_code=400, detail=f"days must be between 1 and {MAX_DAYS}")
    return days


def _parse_iso_date(value: Optional[str], name: str) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{name} must be a valid YYYY-MM-DD date")


def _read_json_cache(path: Path) -> Optional[Dict[str, Any]]:
    """Parse a JSON cache file; anything that is not a JSON object (or is unreadable) is 'no cache'."""
    try:
        if not path.exists():
            return None
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _cached_payload(cache: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    payload = cache.get("payload") if cache else None
    return payload if isinstance(payload, dict) else None


# ============ Pydantic Models ============

class SyncRequest(BaseModel):
    series_id: str
    series_type: str = "index"
    days: int = 365


class BulkSyncRequest(BaseModel):
    days: int = 365


class SeriesResponse(BaseModel):
    series_id: str
    date: str
    value: Optional[float]


# ============ Helper Functions ============

def get_fred_service():
    """Dependency to get FRED service.

    Constructing the service never requires an API key (cached reads work without one), so
    there is no 503 here. Endpoints that need the live provider get ``FredUnavailable`` from
    the service and map it to 503 themselves.
    """
    return FredDataService()


# ============ Sync Endpoints ============

@router.post("/sync/series")
def sync_single_series(
    request: SyncRequest,
    _user: str = Depends(require_user),
    service: FredDataService = Depends(get_fred_service)
):
    """Sync a single FRED series to database (authenticated: writes the DB and uses provider quota)"""
    _check_series_id(request.series_id)
    if request.series_type not in SERIES_TYPES:
        raise HTTPException(status_code=400, detail=f"series_type must be one of: {', '.join(sorted(SERIES_TYPES))}")
    _check_days(request.days)
    try:
        result = service.fetch_and_store_series(
            series_id=request.series_id,
            series_type=request.series_type,
            start_date=date.today() - timedelta(days=request.days),
            end_date=date.today()
        )
        return result
    except FredUnavailable:
        raise HTTPException(status_code=503, detail="FRED service is not configured")
    except Exception:
        logger.exception("FRED route sync_single_series failed")
        raise HTTPException(status_code=500, detail="FRED data request failed")


@router.post("/sync/indices")
def sync_all_indices(
    request: BulkSyncRequest = BulkSyncRequest(),
    _user: str = Depends(require_user),
    service: FredDataService = Depends(get_fred_service)
):
    """Sync all default index series (SP500, DJIA, NASDAQ100, etc.)"""
    _check_days(request.days)
    try:
        results = service.sync_all_indices(days=request.days)
        return {
            "status": "completed",
            "series_count": len(results),
            "results": results
        }
    except FredUnavailable:
        raise HTTPException(status_code=503, detail="FRED service is not configured")
    except Exception:
        logger.exception("FRED route sync_all_indices failed")
        raise HTTPException(status_code=500, detail="FRED data request failed")


@router.post("/sync/rates")
def sync_all_rates(
    request: BulkSyncRequest = BulkSyncRequest(),
    _user: str = Depends(require_user),
    service: FredDataService = Depends(get_fred_service)
):
    """Sync all default interest rate series"""
    _check_days(request.days)
    try:
        results = service.sync_all_rates(days=request.days)
        return {
            "status": "completed",
            "series_count": len(results),
            "results": results
        }
    except FredUnavailable:
        raise HTTPException(status_code=503, detail="FRED service is not configured")
    except Exception:
        logger.exception("FRED route sync_all_rates failed")
        raise HTTPException(status_code=500, detail="FRED data request failed")


@router.post("/sync/all")
def sync_all_series(
    request: BulkSyncRequest = BulkSyncRequest(),
    _user: str = Depends(require_user),
    service: FredDataService = Depends(get_fred_service)
):
    """Sync all default FRED series (indices + rates)"""
    _check_days(request.days)
    try:
        results = service.sync_all(days=request.days)
        return {
            "status": "completed",
            "indices_count": len(results.get("indices", [])),
            "rates_count": len(results.get("rates", [])),
            "results": results
        }
    except FredUnavailable:
        raise HTTPException(status_code=503, detail="FRED service is not configured")
    except Exception:
        logger.exception("FRED route sync_all_series failed")
        raise HTTPException(status_code=500, detail="FRED data request failed")


# ============ Query Endpoints ============

@router.get("/series/{series_id}")
def get_series_data(
    series_id: str,
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: Optional[int] = Query(None, ge=1, le=100000, description="Limit number of records (>=1)"),
    service: FredDataService = Depends(get_fred_service)
):
    """Get cached data for a specific FRED series"""
    _check_series_id(series_id)
    start = _parse_iso_date(start_date, "start_date")
    end = _parse_iso_date(end_date, "end_date")
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start_date must not be after end_date")
    try:
        data = service.get_cached_series(series_id, start, end)

        if limit is not None:
            data = data[:limit]
        
        return {
            "series_id": series_id,
            "count": len(data),
            "data": data
        }
    except FredUnavailable:
        raise HTTPException(status_code=503, detail="FRED service is not configured")
    except Exception:
        logger.exception("FRED route get_series_data failed")
        raise HTTPException(status_code=500, detail="FRED data request failed")


@router.get("/series/{series_id}/latest")
def get_series_latest(
    series_id: str,
    service: FredDataService = Depends(get_fred_service)
):
    """Get the latest value for a specific series"""
    _check_series_id(series_id)
    try:
        data = service.get_cached_latest([series_id])
        if not data:
            raise HTTPException(status_code=404, detail=f"No data found for {series_id}")
        return data[series_id]
    except HTTPException:
        raise
    except FredUnavailable:
        raise HTTPException(status_code=503, detail="FRED service is not configured")
    except Exception:
        logger.exception("FRED route get_series_latest failed")
        raise HTTPException(status_code=500, detail="FRED data request failed")


@router.get("/latest")
def get_all_latest(
    series_ids: Optional[str] = Query(None, description="Comma-separated series IDs (max 25)"),
    service: FredDataService = Depends(get_fred_service)
):
    """Get latest values for multiple series"""
    ids = _parse_series_ids(series_ids, None)
    try:
        data = service.get_cached_latest(ids)
        return {
            "count": len(data),
            "data": data
        }
    except FredUnavailable:
        raise HTTPException(status_code=503, detail="FRED service is not configured")
    except Exception:
        logger.exception("FRED route get_all_latest failed")
        raise HTTPException(status_code=500, detail="FRED data request failed")


@router.get("/latest-live")
def get_latest_live(
    series_ids: Optional[str] = Query(None, description="Comma-separated series IDs (max 25)"),
    service: FredDataService = Depends(get_fred_service)
):
    """Fetch latest values directly from FRED (no cache)."""
    ids = _parse_series_ids(series_ids, list(ALL_DEFAULT_SERIES.keys()))
    try:
        end_date = date.today()
        start_date = end_date - timedelta(days=90)
        data: Dict[str, Dict] = {}

        for series_id in ids:
            series = service.fetch_series(series_id, start_date, end_date)
            series = series.dropna()
            if series.empty:
                data[series_id] = {
                    "series_id": series_id,
                    "status": "error",
                    "message": "No data returned",
                }
                continue

            latest_value = float(series.iloc[-1])
            latest_date = series.index[-1].strftime("%Y-%m-%d")
            prev_value = float(series.iloc[-2]) if len(series) > 1 else None
            change = latest_value - prev_value if prev_value is not None else None
            change_pct = (change / prev_value * 100) if prev_value not in (None, 0) else None

            meta = ALL_DEFAULT_SERIES.get(series_id, {"title": series_id, "type": "index"})
            data[series_id] = {
                "series_id": series_id,
                "title": meta.get("title", series_id),
                "type": meta.get("type", "index"),
                "value": latest_value,
                "date": latest_date,
                "previous": prev_value,
                "change": change,
                "change_pct": change_pct,
                "status": "success",
            }

        return {
            "count": len(data),
            "data": data,
        }
    except FredUnavailable:
        raise HTTPException(status_code=503, detail="FRED service is not configured")
    except Exception:
        logger.exception("FRED route get_latest_live failed")
        raise HTTPException(status_code=500, detail="FRED data request failed")


@router.get("/latest-cached")
def get_latest_cached(
    series_ids: Optional[str] = Query(None, description="Comma-separated series IDs (max 25)"),
    max_age_hours: int = Query(24, ge=0, le=MAX_AGE_HOURS_LIMIT, description="Max age before refresh"),
    service: FredDataService = Depends(get_fred_service)
):
    """Get latest values from cache, refresh only if stale/missing."""
    ids = _parse_series_ids(series_ids, list(ALL_DEFAULT_SERIES.keys()))
    try:
        data: Dict[str, Dict] = {}

        with get_db_session() as db:
            repo = service  # keep naming consistent
            for series_id in ids:
                try:
                    latest = db.query(FredData).filter(FredData.series_id == series_id).order_by(FredData.date.desc()).first()
                    needs_refresh = True
                    if latest and latest.updated_at:
                        age = datetime.utcnow() - latest.updated_at.replace(tzinfo=None)
                        needs_refresh = age > timedelta(hours=max_age_hours)

                    if (latest is None or needs_refresh) and service.api_key:
                        series_info = ALL_DEFAULT_SERIES.get(series_id, {"type": "index"})
                        service.fetch_and_store_series(series_id, series_info["type"], start_date=date.today() - timedelta(days=365), end_date=date.today())

                    rows = (
                        db.query(FredData)
                        .filter(FredData.series_id == series_id)
                        .order_by(FredData.date.desc())
                        .limit(2)
                        .all()
                    )

                    if not rows:
                        if series_id in GOLD_SERIES_IDS:
                            gold_payload = _fetch_gold_price_from_yf(max_age_hours=max_age_hours)
                            if gold_payload:
                                data[series_id] = {
                                    "series_id": series_id,
                                    "title": "Gold Price (Yahoo Finance)",
                                    "type": "commodity",
                                    "value": gold_payload.get("value"),
                                    "date": gold_payload.get("date"),
                                    "previous": gold_payload.get("previous"),
                                    "change": gold_payload.get("change"),
                                    "change_pct": gold_payload.get("change_pct"),
                                    "status": "success",
                                    "updated_at": None,
                                    "source": "yfinance",
                                }
                                continue
                        data[series_id] = {
                            "series_id": series_id,
                            "status": "error",
                            "message": "Gold price unavailable from Yahoo Finance" if series_id in GOLD_SERIES_IDS else "No cached data",
                        }
                        continue

                    latest_row = rows[0]
                    prev_row = rows[1] if len(rows) > 1 else None
                    latest_value = latest_row.value
                    prev_value = prev_row.value if prev_row else None
                    change = (latest_value - prev_value) if (latest_value is not None and prev_value is not None) else None
                    change_pct = (change / prev_value * 100) if (change is not None and prev_value not in (None, 0)) else None

                    meta = ALL_DEFAULT_SERIES.get(series_id, {"title": series_id, "type": "index"})
                    if series_id in GOLD_SERIES_IDS and latest_value is None:
                        gold_payload = _fetch_gold_price_from_yf(max_age_hours=max_age_hours)
                        if gold_payload:
                            data[series_id] = {
                                "series_id": series_id,
                                "title": "Gold Price (Yahoo Finance)",
                                "type": "commodity",
                                "value": gold_payload.get("value"),
                                "date": gold_payload.get("date"),
                                "previous": gold_payload.get("previous"),
                                "change": gold_payload.get("change"),
                                "change_pct": gold_payload.get("change_pct"),
                                "status": "success",
                                "updated_at": None,
                                "source": "yfinance",
                            }
                            continue

                    data[series_id] = {
                        "series_id": series_id,
                        "title": meta.get("title", series_id),
                        "type": meta.get("type", "index"),
                        "value": latest_value,
                        "date": latest_row.date.isoformat(),
                        "previous": prev_value,
                        "change": change,
                        "change_pct": change_pct,
                        "status": "success",
                        "updated_at": latest_row.updated_at.isoformat() if latest_row.updated_at else None,
                        "stale": bool(needs_refresh and not service.api_key),
                        "source": "fred_cache",
                    }
                except Exception:
                    logger.exception("FRED latest value failed for %s", series_id)
                    data[series_id] = {
                        "series_id": series_id,
                        "status": "error",
                        "message": "Series data unavailable",
                    }

        return {
            "count": len(data),
            "data": data,
        }
    except FredUnavailable:
        raise HTTPException(status_code=503, detail="FRED service is not configured")
    except Exception:
        logger.exception("FRED route get_latest_cached failed")
        raise HTTPException(status_code=500, detail="FRED data request failed")


@router.get("/trending-news")
def get_trending_news(
    series_ids: Optional[str] = Query(None, description="Comma-separated series IDs (optional, max 25)"),
    max_age_hours: int = Query(12, ge=0, le=MAX_AGE_HOURS_LIMIT, description="Max age before refresh"),
    limit: int = Query(6, ge=1, le=50, description="Max articles to return")
):
    """Fetch DuckDuckGo news for the most volatile index."""
    ids = _parse_series_ids(series_ids, [
        k for k, v in ALL_DEFAULT_SERIES.items() if v.get("type") == "index"
    ])
    try:
        # NewsService handles availability checks

        cache_path = Path(__file__).resolve().parents[1] / "cache" / "fred_trending_news.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # A malformed cache (non-object JSON, bad timestamps) is treated as "no cache".
        cached_payload = _read_json_cache(cache_path)
        if cached_payload is not None:
            try:
                cached_at = cached_payload.get("cached_at")
                cached_body = _cached_payload(cached_payload)
                if cached_at and cached_body is not None:
                    cached_dt = datetime.fromisoformat(cached_at)
                    age = datetime.utcnow() - cached_dt
                    if age < timedelta(hours=max_age_hours):
                        payload = dict(cached_body)
                        payload["cached"] = True
                        payload["cached_at"] = cached_at
                        return payload
            except (ValueError, TypeError, OverflowError):
                cached_payload = None

        trending = None
        service = FredDataService()
        with get_db_session() as db:
            for series_id in ids:
                latest = (
                    db.query(FredData)
                    .filter(FredData.series_id == series_id)
                    .order_by(FredData.date.desc())
                    .first()
                )

                needs_refresh = True
                if latest and latest.updated_at:
                    age = datetime.utcnow() - latest.updated_at.replace(tzinfo=None)
                    needs_refresh = age > timedelta(hours=max_age_hours)

                if (latest is None or needs_refresh) and service.api_key:
                    series_info = ALL_DEFAULT_SERIES.get(series_id, {"type": "index"})
                    service.fetch_and_store_series(
                        series_id,
                        series_info["type"],
                        start_date=date.today() - timedelta(days=365),
                        end_date=date.today(),
                    )

                rows = (
                    db.query(FredData)
                    .filter(FredData.series_id == series_id)
                    .order_by(FredData.date.desc())
                    .limit(2)
                    .all()
                )
                if not rows:
                    continue

                latest_row = rows[0]
                prev_row = rows[1] if len(rows) > 1 else None
                latest_value = latest_row.value
                prev_value = prev_row.value if prev_row else None
                change_pct = (
                    ((latest_value - prev_value) / prev_value) * 100
                    if (latest_value is not None and prev_value not in (None, 0))
                    else None
                )

                if change_pct is None:
                    continue

                score = abs(change_pct)
                if trending is None or score > trending["score"]:
                    meta = ALL_DEFAULT_SERIES.get(series_id, {"title": series_id})
                    trending = {
                        "series_id": series_id,
                        "title": meta.get("title", series_id),
                        "date": latest_row.date.isoformat(),
                        "value": latest_value,
                        "change_pct": change_pct,
                        "score": score,
                    }

        if not trending:
            return {
                "status": "error",
                "message": "No cached data to determine trending index.",
                "articles": [],
            }

        from backend.news.service import NewsService
        news_service = NewsService()
        
        query = f"{trending['title']} index news"
        
        try:
            # Use centralized news service
            results = news_service.search_news(query)[:limit]
            
            articles = []
            for item in results:
                articles.append({
                    "title": item.get("title"),
                    "url": item.get("href") or item.get("url"),
                    "source": item.get("source"),
                    "date": item.get("date"),
                    "summary": item.get("body"),
                })
        except Exception:
            logger.exception("Trending news fetch failed")
            cached_body = _cached_payload(cached_payload)
            if cached_body is not None:
                payload = dict(cached_body)
                payload["cached"] = True
                payload["cached_at"] = cached_payload.get("cached_at")
                payload["status"] = "stale"
                payload["message"] = "News fetch failed; serving cached results."
                return payload
            raise

        payload = {
            "status": "success",
            "trending": trending,
            "query": query,
            "articles": articles,
        }
        cache_path.write_text(
            json.dumps({"cached_at": datetime.utcnow().isoformat(), "payload": payload}),
            encoding="utf-8"
        )
        payload["cached"] = False
        payload["cached_at"] = datetime.utcnow().isoformat()
        return payload
    except FredUnavailable:
        raise HTTPException(status_code=503, detail="FRED service is not configured")
    except Exception:
        logger.exception("FRED route get_trending_news failed")
        raise HTTPException(status_code=500, detail="FRED data request failed")


@router.get("/index-news")
def get_index_news(
    series_ids: Optional[str] = Query(None),
    max_age_hours: int = Query(12, ge=0, le=MAX_AGE_HOURS_LIMIT),
    limit: int = Query(5, ge=1, le=50),
    refresh: bool = Query(False),
    background_tasks: BackgroundTasks = None,
):
    from backend.news.service import NewsService
    ids = [s.strip() for s in series_ids.split(",")] if series_ids else [
        k for k, v in ALL_DEFAULT_SERIES.items() if v.get("type") == "index"
    ]
    if len(ids) > 30 or any(not SERIES_ID_RE.fullmatch(s) for s in ids):
        raise HTTPException(status_code=422, detail="Invalid series IDs")
    cache_dir = Path(__file__).resolve().parents[1] / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for series_id in ids:
        title = ALL_DEFAULT_SERIES.get(series_id, {}).get("title", series_id)
        query = f"{title} news"
        cache_path = cache_dir / f"fred_index_news_{series_id}.json"
        # Non-object JSON or a non-object "payload" is treated as no cache.
        cached = _read_json_cache(cache_path)
        if cached is not None and _cached_payload(cached) is None:
            cached = None
        try:
            if cached and not refresh:
                age = datetime.utcnow() - datetime.fromisoformat(cached["cached_at"])
                if age < timedelta(hours=max_age_hours) and cached["payload"].get("articles"):
                    results[series_id] = {**cached["payload"], "cached": True}
                    continue
        except (ValueError, KeyError, TypeError, OverflowError):
            cached = None
        try:
            items = NewsService().search_news(query)[:limit]
            articles = [{"title": i.get("title"), "url": i.get("href") or i.get("url"),
                         "summary": i.get("body"), "source": i.get("source"), "date": i.get("date")} for i in items]
            payload = {"status": "success" if articles else "empty", "title": title,
                       "query": query, "articles": articles, "cached": False}
            if articles:
                cache_path.write_text(json.dumps({"cached_at": datetime.utcnow().isoformat(), "payload": payload}))
            results[series_id] = payload
        except Exception:
            logger.exception("Index news fetch failed")
            if cached and cached["payload"].get("articles"):
                results[series_id] = {**cached["payload"], "status": "stale", "cached": True}
            else:
                results[series_id] = {"status": "unavailable", "title": title, "articles": []}
    return {"status": "success" if all(v["status"] == "success" for v in results.values()) else "partial",
            "count": len(results), "data": results}


@router.get("/dashboard")
def get_index_dashboard(
    service: FredDataService = Depends(get_fred_service)
):
    """Get dashboard overview with all indices and rates"""
    try:
        return service.get_index_dashboard()
    except FredUnavailable:
        raise HTTPException(status_code=503, detail="FRED service is not configured")
    except Exception:
        logger.exception("FRED route get_index_dashboard failed")
        raise HTTPException(status_code=500, detail="FRED data request failed")


# ============ Metadata Endpoints ============

@router.get("/available-series")
async def get_available_series():
    """Get list of all available series that can be synced"""
    return {
        "total": len(ALL_DEFAULT_SERIES),
        "series": [
            {
                "series_id": k,
                "type": v["type"],
                "title": v["title"]
            }
            for k, v in ALL_DEFAULT_SERIES.items()
        ]
    }


# ============ Auto-fetch Endpoint ============

@router.get("/smart/{series_id}")
def get_series_smart(
    series_id: str,
    max_age_hours: int = Query(24, ge=0, le=MAX_AGE_HOURS_LIMIT, description="Max age before refetch"),
    service: FredDataService = Depends(get_fred_service)
):
    """Get series data with automatic refresh if stale"""
    _check_series_id(series_id)
    try:
        series_info = ALL_DEFAULT_SERIES.get(series_id, {"type": "index"})
        data = service.get_series_with_fallback(
            series_id,
            series_type=series_info["type"],
            max_age_hours=max_age_hours
        )
        return {
            "series_id": series_id,
            "count": len(data),
            "data": data
        }
    except FredUnavailable:
        raise HTTPException(status_code=503, detail="FRED service is not configured")
    except Exception:
        logger.exception("FRED route get_series_smart failed")
        raise HTTPException(status_code=500, detail="FRED data request failed")

