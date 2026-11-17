"""
JSON-safe 422 responses for request validation failures.

FastAPI's default handler echoes the offending `input` (and `ctx`) back in the 422 body. When a client
sends a JSON number such as NaN / Infinity into a field of the wrong type, that echo is a non-finite
float and rendering the response itself raises, turning a client error into a 500. This handler returns
the error type, location and message only, and keeps `ctx` entries only when they are plain finite
JSON scalars.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _safe_ctx(ctx: Any) -> Dict[str, Any]:
    if not isinstance(ctx, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, value in ctx.items():
        if isinstance(value, bool) or isinstance(value, (int, str)):
            out[str(key)] = value
        elif isinstance(value, float) and math.isfinite(value):
            out[str(key)] = value
    return out


def _safe_loc(loc: Any) -> List[Any]:
    return [part if isinstance(part, (int, str)) else str(part) for part in (loc or ())]


def sanitize_validation_errors(errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for err in errors:
        item: Dict[str, Any] = {
            "type": str(err.get("type", "value_error")),
            "loc": _safe_loc(err.get("loc")),
            "msg": str(err.get("msg", "Invalid value")),
        }
        ctx = _safe_ctx(err.get("ctx"))
        if ctx:
            item["ctx"] = ctx
        cleaned.append(item)
    return cleaned


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": sanitize_validation_errors(list(exc.errors()))})
