import json
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

# Internal services
from .fundamentals_service import get_fundamentals_summary
from .peer_service import fetch_peer_comparison
from .peers_legacy_service import fetch_stock_peers

# Unified services
from backend.services.market_data import market_service
from .core.strategy_service import (
    STRATEGY_REGISTRY,
    NoDataError,
    analyze_dataframe,
    get_available_strategies,
    get_strategy,
    normalize_period,
    resolve_fetch_period,
    validate_params,
)
from .core.json_utils import make_json_safe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Technical & Fundamentals"])

# --- Technical Analysis (Legacy /api/technical) ---

@router.get("/strategies")
async def get_strategies():
    return {"strategies": get_available_strategies()}

class AnalyzeRequest(BaseModel):
    symbol: str
    strategy: str
    period: Optional[str] = None
    range_: Optional[str] = Field(None, alias="range")
    interval: str = "1d"
    market: str = "US"
    params: Optional[Any] = None

    model_config = ConfigDict(populate_by_name=True)


def _parse_params(params: Any) -> Dict[str, Any]:
    """Accept a JSON object, or a JSON string encoding one; anything else is a 400."""
    if params is None or params == "":
        return {}
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except ValueError:
            raise HTTPException(status_code=400, detail="params must be valid JSON")
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="params must be a JSON object")
    return params


def _run_analysis(
    symbol: str,
    strategy: str,
    period: Optional[str],
    range_: Optional[str],
    interval: str,
    market: str,
    params: Any,
) -> Dict[str, Any]:
    """Shared implementation behind GET and POST /analyze."""
    try:
        symbol = (symbol or "").strip()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol is required")

        # `range` is an alias for `period`; an explicit `period` wins.
        try:
            canonical_period = normalize_period(period or range_ or "1y")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        strategy_id = (strategy or "").strip().lower()
        if strategy_id not in STRATEGY_REGISTRY:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown strategy '{strategy}'. Valid strategies: {', '.join(STRATEGY_REGISTRY)}",
            )

        strategy_params = _parse_params(params)
        try:
            instance = get_strategy(strategy_id, **strategy_params)
            validate_params(instance, strategy_params)
        except (TypeError, ValueError, OverflowError) as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid params for strategy '{strategy_id}': {e}"
            )

        interval = (interval or "1d").strip().lower()
        try:
            fetch_period = resolve_fetch_period(canonical_period, interval)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        df = market_service.fetch_ohlcv(
            symbol, interval=interval, period=fetch_period, market=market
        )
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="No data")

        try:
            result = analyze_dataframe(
                df, symbol, strategy_id, strategy_params, canonical_period, interval
            )
        except NoDataError:
            raise HTTPException(status_code=404, detail="No data")
        result["market"] = market
        return make_json_safe(result)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Technical analysis failed for %s (%s)", symbol, strategy)
        raise HTTPException(status_code=500, detail="Technical analysis failed")


@router.get("/analyze")
def analyze_strategy_get(
    symbol: str,
    strategy: str,
    period: Optional[str] = Query(None, description="Default 1y"),
    range: Optional[str] = Query(None, description="Alias for period"),
    interval: str = "1d",
    market: str = "US",
    params: Optional[str] = Query(None, description="Strategy params as a JSON object string"),
):
    """
    Run a registered strategy over market data and return its signals.

    GET takes query params (symbol, strategy, period=1y, interval=1d, market=US,
    params=<JSON object string>); POST takes the same fields as a JSON body
    (params as an object). `range` is accepted as an alias for `period`.

    Periods: 1mo/1m, 3mo/3m, 6mo/6m, 1y, 2y, 5y, max/all. A longer history is
    fetched so indicators are warmed up; the output is then trimmed to the
    requested window measured back from the LAST BAR date (not wall-clock now).

    Response:
        {
          "symbol", "strategy", "parameters": {effective params},
          "period": canonical period, "interval", "market",
          "start": first bar in window, "end": last bar, "bars": bars in window,
          "truncated_history": true if the fetched history starts after the
              requested window start (window shorter than requested),
          "signals": [{"date", "type": "buy"|"sell", "price": close}]
              emitted on bars where the signal changes to +1 (buy) / -1 (sell)
              vs. the previous bar (changes to 0 emit nothing),
          "latest_signal": {"date", "signal": 1|0|-1, "label": "buy"|"sell"|"neutral"},
          "indicators": {column: [{"time", "value"}]} (NaN omitted),
          "assumptions": text
        }
    Dates are YYYY-MM-DD for daily+ intervals, ISO datetimes for intraday.

    Intraday intervals are capped at the provider limit (1m: 7d; 2m-90m: 60d;
    60m/1h: 730d); a longer period is a 400. Params must be positive-integer
    windows (oversold/overbought: finite numbers, oversold < overbought).

    Errors: 400 (unknown strategy/period, bad params), 404 (no data),
    500 (generic message; details are only logged).
    """
    return _run_analysis(symbol, strategy, period, range, interval, market, params)


@router.post("/analyze", description=analyze_strategy_get.__doc__)
def analyze_strategy_post(body: AnalyzeRequest):
    return _run_analysis(
        body.symbol, body.strategy, body.period, body.range_,
        body.interval, body.market, body.params,
    )

# --- Fundamentals (Legacy /api/fundamentals) ---

@router.get("/fundamentals/summary/{symbol}")
def get_fundamental_summary(symbol: str):
    data = get_fundamentals_summary(symbol)
    if not data or not data.get("name"):
        raise HTTPException(status_code=404, detail="Not found")
    return data

# --- Peers (Legacy /api/peers) ---

@router.get("/peers/compare/{symbol}")
def get_peer_comparison_route(symbol: str, limit: int = Query(12)):
    try:
        data = fetch_peer_comparison(symbol, limit=limit)
        return make_json_safe(data)
    except Exception as e:
        return make_json_safe({"symbol": symbol, "error": str(e), "rows": []})

@router.get("/peers/{symbol}")
def get_peers_route(symbol: str):
    peers = fetch_stock_peers(symbol)
    return {"symbol": symbol.upper(), "peers": peers, "count": len(peers)}
