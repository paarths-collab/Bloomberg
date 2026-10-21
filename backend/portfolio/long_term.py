"""
Long Term Strategy Routes

Exposes the long-term buy-and-hold analysis. The request keeps its original field
names; fields the core strategy does not model are accepted but ignored, and the
response lists them under ``ignored_fields``.
"""

import math
import re
from datetime import date
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator, model_validator

from .core import long_term_strategy as core

router = APIRouter(prefix="/api/long-term", tags=["Long Term Strategy"])

MAX_ALLOCATION_SYMBOLS = 25
SYMBOL_RE = re.compile(r"^[A-Za-z0-9.^=\-]{1,15}$")  # e.g. AAPL, BRK-B, RELIANCE.NS, ^GSPC, EURUSD=X

# Accepted for backwards compatibility but not modelled by the core strategy.
IGNORED_FIELDS = ("market", "risk_profile", "monthly_investment")


def _parse_date(value: Optional[str], name: str) -> Optional[str]:
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(f"{name} must be a YYYY-MM-DD date")


class LongTermAnalysisRequest(BaseModel):
    ticker: str
    market: str = "US"
    risk_profile: str = "moderate"
    # Range/finite check is done in the route: pydantic would echo an Infinity input back in
    # its 422 body, which the default JSON encoder cannot serialise (-> 500).
    capital: float = 10000.0
    monthly_investment: float = 500.0
    start_date: str = "2020-01-01"
    end_date: Optional[str] = None  # No upper bound if None
    allocation: Optional[Dict[str, float]] = None  # Optional {ticker: weight}; default 100% in `ticker`

    @field_validator("ticker")
    @classmethod
    def _check_ticker(cls, v: str) -> str:
        v = v.strip()
        if not SYMBOL_RE.match(v):
            raise ValueError("ticker must be 1-15 characters of letters, digits, . ^ = -")
        return v

    @field_validator("allocation")
    @classmethod
    def _check_allocation(cls, v: Optional[Dict[str, float]]) -> Optional[Dict[str, float]]:
        if v is None:
            return v
        if len(v) > MAX_ALLOCATION_SYMBOLS:
            raise ValueError(f"allocation may contain at most {MAX_ALLOCATION_SYMBOLS} symbols")
        for k in v:
            if not SYMBOL_RE.match(k.strip()):
                raise ValueError("allocation symbols must be 1-15 characters of letters, digits, . ^ = -")
        return v

    @field_validator("start_date")
    @classmethod
    def _check_start(cls, v: str) -> str:
        return _parse_date(v, "start_date")

    @field_validator("end_date")
    @classmethod
    def _check_end(cls, v: Optional[str]) -> Optional[str]:
        return _parse_date(v, "end_date")

    @model_validator(mode="after")
    def _check_range(self):
        if self.end_date and self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


@router.post("/analyze")
def analyze_long_term(request: LongTermAnalysisRequest):
    """
    Run a buy-and-hold analysis for ``ticker`` (or a custom ``allocation``).
    """
    ticker = request.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=422, detail="ticker must not be empty")

    if not math.isfinite(request.capital) or request.capital <= 0:
        raise HTTPException(status_code=422, detail="capital must be a finite number > 0")

    tickers: List[str] = [ticker]
    allocation: Optional[Dict[str, float]] = None
    if request.allocation:
        allocation = {k.strip().upper(): v for k, v in request.allocation.items()}
        tickers += [k for k in allocation if k != ticker]
    else:
        allocation = {ticker: 1.0}

    try:
        results = core.run_long_term_strategy(
            tickers=tickers,
            allocation=allocation,
            start_date=request.start_date,
            initial_capital=request.capital,
            end_date=request.end_date,
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Long-term analysis failed")

    if results.get("status") != "success":
        code = results.get("error_code")
        detail = results.get("error", "Analysis failed")
        if code == core.ERR_INVALID_INPUT:
            raise HTTPException(status_code=422, detail=detail)
        if code == core.ERR_DATA_UNAVAILABLE:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=500, detail="Long-term analysis failed")

    ignored: List[str] = [f for f in IGNORED_FIELDS if f in request.model_fields_set]
    return {
        "status": "success",
        "data": results,
        "ignored_fields": ignored,
    }
