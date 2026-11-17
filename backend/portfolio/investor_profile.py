"""
Investor Profile & paper-portfolio API (single shared implementation).

The handlers are mounted once, at /api/profile, by backend/profile/main.py.

Every route requires a bearer token (see backend/auth). The acting user is the
token's subject; a client-supplied ``user_id`` is ignored when it matches and
rejected with 403 when it differs.

Notes on write semantics:
  - /trade is optimistic (compare-and-swap on the holdings JSON, retried, then 409).
  - /save is a plain upsert. Profile fields are replaced; ``existing_investments`` is
    optional: omitted or blank keeps the stored holdings, while a non-blank value REPLACES
    them wholesale WITHOUT compare-and-swap (a concurrent trade can be overwritten).
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.auth.security import require_user
from backend.common.json_routes import StrictJSONRoute
from backend.database.connection import get_db
from backend.portfolio.core.risk_metrics import compute_portfolio_risk, load_price_history
from backend.services.market_data import market_service

logger = logging.getLogger(__name__)

SYMBOL_RE = re.compile(r"^[A-Z0-9.\-^=]{1,20}$")
MAX_TRADE_ATTEMPTS = 5
SELL_TOLERANCE = 1e-9
DUST_QUANTITY = 1e-6

MAX_HOLDINGS = 500
MAX_RISK_SYMBOLS = 50
MAX_HOLDINGS_JSON_CHARS = 200_000
RISK_PERIODS = ("6mo", "1y", "2y", "5y")


shared_router = APIRouter(tags=["Investor Profile"], route_class=StrictJSONRoute)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ProfileValidationError(ValueError):
    """Deliberate input validation failure raised by this module.

    The message is always fixed text written here (never exception text from a library), so it
    is safe to return to the client as a 422 detail. Any other exception is not client-safe.
    """


def _normalize_symbol(value: Any) -> str:
    if not isinstance(value, str):
        raise ProfileValidationError("symbol must be a string")
    symbol = value.strip().upper()
    if not SYMBOL_RE.match(symbol):
        raise ProfileValidationError("symbol must be 1-20 characters of A-Z, 0-9, '.', '-', '^' or '='")
    return symbol


_Num = dict(strict=True, allow_inf_nan=False)  # real JSON numbers only (no bool / numeric strings)


class ProfilePayload(BaseModel):
    # Deprecated: identity comes from the bearer token. Accepted for backward
    # compatibility; a value that differs from the authenticated user gives 403.
    user_id: Optional[str] = Field(default=None, max_length=128)
    name: Optional[str] = Field(default=None, max_length=200)
    age: Optional[int] = Field(default=None, ge=0, le=150, strict=True)
    monthly_income: Optional[float] = Field(default=None, ge=-1e12, le=1e12, **_Num)
    monthly_savings: Optional[float] = Field(default=None, ge=-1e12, le=1e12, **_Num)
    risk_tolerance: Optional[str] = Field(default="moderate", max_length=50)
    horizon_years: Optional[int] = Field(default=5, ge=0, le=100, strict=True)
    primary_goal: Optional[str] = Field(default=None, max_length=1000)
    # Optional holdings JSON ({"AAPL": {"quantity", "avg_price", "total_invested"}}, at most
    # MAX_HOLDINGS entries). Omitted or blank keeps the stored holdings; a non-blank value replaces
    # them wholesale (no compare-and-swap). Invalid/oversized -> 422. Stored in normalised form.
    existing_investments: Optional[str] = Field(default=None, max_length=MAX_HOLDINGS_JSON_CHARS)
    market: Optional[str] = Field(default="US", max_length=20)

    @field_validator("existing_investments")
    @classmethod
    def _validate_holdings(cls, value):
        if value is None or not value.strip():
            return None
        if not value.lstrip().startswith("{"):
            raise ProfileValidationError("existing_investments must be a JSON object of holdings")
        try:
            raw = json.loads(value)
        except (ValueError, TypeError, RecursionError):
            # json's error text is not ours to echo back; keep the message fixed.
            raise ProfileValidationError("existing_investments must be valid holdings JSON")
        return json.dumps(_normalize_holdings(raw))  # raises ProfileValidationError with a specific message


class TradeRequest(BaseModel):
    user_id: Optional[str] = Field(default=None, max_length=128)  # deprecated, see ProfilePayload
    symbol: str
    amount: Optional[float] = Field(default=0.0, ge=0, **_Num)  # cash to invest/raise
    quantity: Optional[float] = Field(default=0.0, ge=0, **_Num)  # shares (preferred over amount)
    price: Optional[float] = Field(default=None, gt=0, **_Num)  # execution price, else live
    side: str = Field(..., pattern="^(buy|sell)$")

    @field_validator("symbol", mode="before")
    @classmethod
    def _validate_symbol(cls, value):
        return _normalize_symbol(value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_identity(requested: Optional[str], auth_user: str) -> None:
    if requested is not None and requested != auth_user:
        raise HTTPException(status_code=403, detail="user_id does not match the authenticated user")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_iso(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _normalize_holdings(raw: Any) -> Dict[str, Dict[str, Any]]:
    """Validate/normalise a holdings mapping; raises ValueError if it is malformed."""
    if not isinstance(raw, dict):
        raise ProfileValidationError("holdings must be a JSON object keyed by symbol")
    if len(raw) > MAX_HOLDINGS:
        raise ProfileValidationError(f"at most {MAX_HOLDINGS} holdings are allowed")
    result: Dict[str, Dict[str, Any]] = {}
    for key, data in raw.items():
        symbol = _normalize_symbol(key)
        if not isinstance(data, dict):
            raise ProfileValidationError(f"holding for {symbol} must be an object")
        qty, avg, invested = data.get("quantity"), data.get("avg_price"), data.get("total_invested")
        if not (_is_number(qty) and qty > 0):
            raise ProfileValidationError(f"holding for {symbol}: quantity must be a positive number")
        if not (_is_number(avg) and avg >= 0) or not (_is_number(invested) and invested >= 0):
            raise ProfileValidationError(f"holding for {symbol}: avg_price/total_invested must be non-negative numbers")
        holding = {"quantity": float(qty), "avg_price": float(avg), "total_invested": float(invested)}
        if isinstance(data.get("last_trade_at"), str):
            holding["last_trade_at"] = data["last_trade_at"]
        result[symbol] = holding
    return result


def _parse_holdings_blob(blob: Optional[str]) -> Dict[str, Dict[str, Any]]:
    if blob is None or not str(blob).strip():
        return {}
    try:
        return _normalize_holdings(json.loads(blob))
    except (ValueError, TypeError, RecursionError):
        logger.exception("Stored holdings are not valid JSON holdings")
        raise HTTPException(
            status_code=409,
            detail="Stored holdings are not valid. Re-save the profile with valid holdings.",
        )


def _read_holdings_blob(db, user_id: str) -> Tuple[bool, Optional[str]]:
    """Return (row_exists, existing_investments) for the user."""
    row = db.execute(
        text("SELECT existing_investments FROM user_profiles WHERE user_id = :uid"),
        {"uid": user_id},
    ).first()
    if row is None:
        return False, None
    return True, row[0]


def _compare_and_swap_holdings(db, user_id: str, old: Optional[str], new: str) -> bool:
    """Write ``new`` only if the stored blob still equals ``old``. Returns True if a row changed."""
    if old is None:
        sql = (
            "UPDATE user_profiles SET existing_investments = :new, updated_at = CURRENT_TIMESTAMP "
            "WHERE user_id = :uid AND existing_investments IS NULL"
        )
        params = {"new": new, "uid": user_id}
    else:
        sql = (
            "UPDATE user_profiles SET existing_investments = :new, updated_at = CURRENT_TIMESTAMP "
            "WHERE user_id = :uid AND existing_investments = :old"
        )
        params = {"new": new, "uid": user_id, "old": old}
    return db.execute(text(sql), params).rowcount == 1


def _ensure_profile_row(db, user_id: str) -> None:
    """Create a minimal profile row if missing; safe against concurrent creation."""
    try:
        db.execute(
            text("INSERT INTO user_profiles (user_id) VALUES (:uid)"),
            {"uid": user_id},
        )
        db.commit()
    except IntegrityError:
        # Another request created the row first (user_id is UNIQUE) - that is fine.
        db.rollback()


def _valid_price(value: Any) -> Optional[float]:
    if _is_number(value) and value > 0:
        return float(value)
    return None


def _live_price(symbol: str) -> Optional[float]:
    """Live price, or None when unavailable (provider returns 0.0/None or raises)."""
    try:
        return _valid_price(market_service.get_current_price(symbol))
    except Exception:
        logger.warning("Price lookup failed for %s", symbol, exc_info=True)
        return None


# Provider price source -> holding ``price_status``. "live" is reserved for a genuine current quote.
_PRICE_STATUS_BY_SOURCE = {
    "live": "live",
    "previous_close": "previous_close",
    "last_close_5d": "stale",
}


def _price_quote(symbol: str) -> Tuple[Optional[float], str, Optional[str]]:
    """(price, price_status, as_of) for valuation; (None, "unavailable", None) when no usable price.

    ``as_of`` is the quote/bar time when the provider reports one, else None.
    """
    try:
        quote = market_service.get_price_quote(symbol)
    except Exception:
        logger.warning("Price lookup failed for %s", symbol, exc_info=True)
        return None, "unavailable", None
    price = _valid_price(quote.get("price")) if isinstance(quote, dict) else None
    if price is None:
        return None, "unavailable", None
    status = _PRICE_STATUS_BY_SOURCE.get(quote.get("source"), "stale")  # unknown source: not "live"
    as_of = quote.get("as_of")
    return price, status, as_of if isinstance(as_of, str) else None


def _apply_trade(
    holdings: Dict[str, Dict[str, Any]], symbol: str, side: str, qty: Optional[float],
    amount: Optional[float], price: float,
) -> Tuple[Dict[str, Dict[str, Any]], float, float]:
    """Return (new_holdings, executed_qty, executed_amount). Raises HTTPException(400) on invalid trades."""
    if qty is not None:
        exec_qty = qty
        exec_amount = qty * price
    else:
        exec_amount = amount
        exec_qty = amount / price
    if not (math.isfinite(exec_qty) and math.isfinite(exec_amount) and exec_qty > 0 and exec_amount > 0):
        raise HTTPException(status_code=400, detail="Trade size is out of range")
    if exec_qty < DUST_QUANTITY:
        raise HTTPException(status_code=400, detail=f"Trade quantity is below the minimum of {DUST_QUANTITY:g} shares")

    new_holdings = {k: dict(v) for k, v in holdings.items()}
    current = new_holdings.get(symbol)
    now = _now_iso()

    if side == "buy":
        if current is None and len(new_holdings) >= MAX_HOLDINGS:
            raise HTTPException(status_code=400, detail=f"A portfolio can hold at most {MAX_HOLDINGS} symbols")
        held = current["quantity"] if current else 0.0
        invested = current["total_invested"] if current else 0.0
        new_qty = held + exec_qty
        new_total = invested + exec_amount
        if not (math.isfinite(new_qty) and math.isfinite(new_total)):
            raise HTTPException(status_code=400, detail="Trade size is out of range")
        new_holdings[symbol] = {
            "quantity": new_qty,
            "avg_price": new_total / new_qty,
            "total_invested": new_total,
            "last_trade_at": now,
        }
    else:
        held = current["quantity"] if current else 0.0
        if exec_qty > held * (1 + SELL_TOLERANCE):
            raise HTTPException(status_code=400, detail=f"Not enough shares to sell. Own: {held}")
        if exec_qty > held:  # within tolerance: clamp, and keep the amount consistent with it
            exec_qty = held
            exec_amount = exec_qty * price
        # Moving-average cost basis: avg price is unchanged, cost basis shrinks pro rata.
        new_qty = held - exec_qty
        if new_qty < DUST_QUANTITY:
            del new_holdings[symbol]
        else:
            new_holdings[symbol] = {
                "quantity": new_qty,
                "avg_price": current["avg_price"],
                "total_invested": current["total_invested"] * (new_qty / held),
                "last_trade_at": now,
            }
    return new_holdings, exec_qty, exec_amount


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@shared_router.post("/save")
def save_profile(payload: ProfilePayload, user: str = Depends(require_user), db=Depends(get_db)):
    """Save or update the authenticated user's investor profile.

    Blank/omitted ``existing_investments`` keeps stored holdings; a non-blank value overwrites them
    without compare-and-swap (see module docstring)."""
    _check_identity(payload.user_id, user)

    holdings_json = payload.existing_investments  # already validated/normalised (None = keep stored)

    try:
        db.execute(
            text("""
                INSERT INTO user_profiles
                    (user_id, name, age, monthly_income, monthly_savings,
                     risk_tolerance, horizon_years, primary_goal,
                     existing_investments, market, updated_at)
                VALUES
                    (:user_id, :name, :age, :monthly_income, :monthly_savings,
                     :risk_tolerance, :horizon_years, :primary_goal,
                     :existing_investments, :market, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    age = EXCLUDED.age,
                    monthly_income = EXCLUDED.monthly_income,
                    monthly_savings = EXCLUDED.monthly_savings,
                    risk_tolerance = EXCLUDED.risk_tolerance,
                    horizon_years = EXCLUDED.horizon_years,
                    primary_goal = EXCLUDED.primary_goal,
                    existing_investments = COALESCE(EXCLUDED.existing_investments, user_profiles.existing_investments),
                    market = EXCLUDED.market,
                    updated_at = CURRENT_TIMESTAMP
            """),
            {
                "user_id": user,
                "name": payload.name,
                "age": payload.age,
                "monthly_income": payload.monthly_income,
                "monthly_savings": payload.monthly_savings,
                "risk_tolerance": payload.risk_tolerance,
                "horizon_years": payload.horizon_years,
                "primary_goal": payload.primary_goal,
                "existing_investments": holdings_json,
                "market": payload.market,
            },
        )
        db.commit()
        return {"status": "ok", "message": "Profile saved"}
    except Exception:
        db.rollback()
        logger.exception("Failed to save profile")
        raise HTTPException(status_code=500, detail="Failed to save profile")


@shared_router.get("/load")
def load_profile(user_id: Optional[str] = None, user: str = Depends(require_user), db=Depends(get_db)):
    """Load the authenticated user's investor profile."""
    _check_identity(user_id, user)
    try:
        row = db.execute(
            text("SELECT * FROM user_profiles WHERE user_id = :uid"),
            {"uid": user},
        ).mappings().first()

        if not row:
            return {"status": "not_found", "profile": None}

        profile = dict(row)
        for key in ("created_at", "updated_at"):
            profile[key] = _to_iso(profile.get(key))
        return {"status": "ok", "profile": profile}
    except Exception:
        logger.exception("Failed to load profile")
        raise HTTPException(status_code=500, detail="Failed to load profile")


@shared_router.post("/trade")
def execute_trade(trade: TradeRequest, user: str = Depends(require_user), db=Depends(get_db)):
    """Execute a mock trade (buy/sell) against the authenticated user's paper portfolio."""
    _check_identity(trade.user_id, user)

    symbol = trade.symbol  # already stripped/uppercased/validated
    qty_in = trade.quantity if trade.quantity and trade.quantity > 0 else None
    amount_in = trade.amount if trade.amount and trade.amount > 0 else None
    if qty_in is None and amount_in is None:
        raise HTTPException(status_code=400, detail="Must specify amount or quantity")

    exec_price = trade.price
    if exec_price is None:
        exec_price = _live_price(symbol)
        if exec_price is None:
            raise HTTPException(status_code=400, detail=f"Could not fetch price for {symbol}")

    try:
        # Optimistic concurrency: read the holdings blob, compute, and write back only if
        # it is unchanged (compare-and-swap); otherwise re-read and retry.
        for _ in range(MAX_TRADE_ATTEMPTS):
            exists, old_blob = _read_holdings_blob(db, user)
            if not exists:
                _ensure_profile_row(db, user)
                exists, old_blob = _read_holdings_blob(db, user)
                if not exists:
                    continue

            holdings = _parse_holdings_blob(old_blob)
            new_holdings, qty, amount = _apply_trade(
                holdings, symbol, trade.side, qty_in, amount_in, exec_price
            )

            if _compare_and_swap_holdings(db, user, old_blob, json.dumps(new_holdings)):
                db.commit()
                return {
                    "status": "ok",
                    "message": f"{trade.side.upper()} {qty:.4f} {symbol} @ ${exec_price:.2f}",
                    "symbol": symbol,
                    "side": trade.side,
                    "quantity": qty,
                    "price": exec_price,
                    "amount": amount,
                    "portfolio": new_holdings,
                }
            db.rollback()  # lost the race: drop the txn and retry on fresh data

        raise HTTPException(status_code=409, detail="Portfolio was modified concurrently; please retry")
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Trade failed")
        raise HTTPException(status_code=500, detail="Trade failed")


@shared_router.get("/portfolio")
def get_portfolio(user_id: Optional[str] = None, user: str = Depends(require_user), db=Depends(get_db)):
    """
    Portfolio with live valuation and P/L. Holdings whose live price is unavailable are
    reported with null price/value/P&L and ``price_status: "unavailable"`` - cost basis is
    never substituted for a missing price - and portfolio totals are null in that case.

    ``valued_at`` (UTC ISO-8601) is when the prices were fetched, i.e. the as-of time of the
    whole valuation.

    Each holding's ``price_status`` says where its price came from
    (``market_service.get_price_quote`` -> ``safe_yfinance.safe_get_price_quote``):
    ``"live"`` - the provider's current quote; ``"previous_close"`` - the provider only had a
    previous close; ``"stale"`` - the last close of the 5-day history; ``"unavailable"`` - no
    usable price. ``price_as_of`` (UTC ISO-8601 or null) is that price's own timestamp when the
    provider reports one (quote time for "live", bar date for "stale"; null for
    "previous_close"/"unavailable"). "live" means the provider's current-quote field, which outside
    market hours is the last traded price. Totals are computed from every available price,
    whatever its status, so a ``previous_close``/``stale`` row still counts toward them.
    """
    _check_identity(user_id, user)
    try:
        _, blob = _read_holdings_blob(db, user)
        portfolio_map = _parse_holdings_blob(blob)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Portfolio fetch failed")
        raise HTTPException(status_code=500, detail="Portfolio fetch failed")

    holdings: List[Dict[str, Any]] = []
    unpriced: List[str] = []
    total_invested = 0.0
    total_value = 0.0

    for symbol, data in portfolio_map.items():
        qty = data["quantity"]
        avg = data["avg_price"]
        invested = data["total_invested"]
        total_invested += invested

        price, price_status, price_as_of = _price_quote(symbol)
        if price is None:
            unpriced.append(symbol)
            holdings.append({
                "symbol": symbol,
                "quantity": qty,
                "avg_price": avg,
                "total_invested": invested,
                "current_price": None,
                "current_value": None,
                "pl": None,
                "pl_pct": None,
                "price_status": "unavailable",
                "price_as_of": None,
            })
            continue

        current_val = qty * price
        pl = current_val - invested
        total_value += current_val
        holdings.append({
            "symbol": symbol,
            "quantity": qty,
            "avg_price": avg,
            "total_invested": invested,
            "current_price": price,
            "current_value": current_val,
            "pl": pl,
            "pl_pct": (pl / invested * 100) if invested > 0 else 0,
            "price_status": price_status,
            "price_as_of": price_as_of,
        })

    valued_at = _now_iso()  # prices were fetched in the loop above (also set when none were available)

    # Priced holdings first (largest value first), unpriced last by cost basis.
    holdings.sort(key=lambda h: (h["current_value"] is None, -(h["current_value"] if h["current_value"] is not None else h["total_invested"])))

    complete = not unpriced
    total_pl = total_value - total_invested if complete else None
    return {
        "holdings": holdings,
        "total_invested": total_invested,
        "total_value": total_value if complete else None,
        "total_pl": total_pl,
        "total_pl_pct": ((total_pl / total_invested * 100) if total_invested > 0 else 0) if complete else None,
        "valuation_complete": complete,
        "unpriced_symbols": unpriced,
        "valued_at": valued_at,
    }


@shared_router.get("/portfolio/risk")
def get_portfolio_risk(
    user_id: Optional[str] = None,
    benchmark: Optional[str] = Query(default=None, max_length=20),
    period: Literal["6mo", "1y", "2y", "5y"] = "1y",
    risk_free_rate: float = Query(default=0.0, ge=0.0, le=0.2, allow_inf_nan=False),
    user: str = Depends(require_user),
    db=Depends(get_db),
):
    """
    Historical risk (beta, Sharpe, max drawdown, volatility) of the authenticated user's CURRENT
    holdings held statically over ``period``, computed from price history (see
    backend/portfolio/core/risk_metrics.py for the method). ``benchmark`` defaults to SPY, or ^NSEI
    when the profile's market is India. An empty portfolio returns 200 with unavailable metrics.

    ``as_of`` and ``valued_at`` carry the same UTC ISO-8601 timestamp, taken once the price history
    had been fetched (``as_of`` is the pre-existing field; ``valued_at`` matches GET /portfolio).
    Per-price timestamps are not provided by the price helpers.
    """
    _check_identity(user_id, user)
    if benchmark is not None:
        try:
            benchmark = _normalize_symbol(benchmark)
        except ProfileValidationError as exc:
            # Our own fixed validation text only (see ProfileValidationError).
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception:
            logger.exception("Benchmark validation failed")
            raise HTTPException(status_code=422, detail="benchmark must be a valid ticker symbol")

    try:
        row = db.execute(
            text("SELECT existing_investments, market FROM user_profiles WHERE user_id = :uid"),
            {"uid": user},
        ).first()
    except Exception:
        logger.exception("Risk lookup failed")
        raise HTTPException(status_code=500, detail="Risk lookup failed")
    blob, market = (row[0], row[1]) if row is not None else (None, None)
    holdings = _parse_holdings_blob(blob)

    if benchmark is None:
        benchmark = "^NSEI" if str(market or "").strip().lower() in ("india", "in") else "SPY"

    quantities = {symbol: data["quantity"] for symbol, data in holdings.items()}
    if len(quantities) > MAX_RISK_SYMBOLS:
        raise HTTPException(
            status_code=422,
            detail=f"Risk metrics support at most {MAX_RISK_SYMBOLS} holdings (portfolio has {len(quantities)})",
        )
    db.close()  # holdings are read; don't hold a DB connection during the upstream price fetches
    try:
        if quantities:
            price_history = load_price_history(list(quantities), period=period)
            benchmark_history = load_price_history([benchmark], period=period).get(benchmark)
        else:
            price_history, benchmark_history = {}, None

        result = compute_portfolio_risk(
            quantities,
            price_history,
            benchmark_history,
            benchmark_symbol=benchmark,
            risk_free_rate=risk_free_rate,
        )
    except Exception:
        logger.exception("Risk computation failed")
        raise HTTPException(status_code=500, detail="Risk computation failed")
    valued_at = _now_iso()
    return {**result, "period": period, "as_of": valued_at, "valued_at": valued_at}
