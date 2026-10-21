"""
Strict JSON request bodies for FastAPI routes.

Python's JSON parser accepts NaN / Infinity / -Infinity and overflowing numbers such as 1e999. Routes
built with `StrictJSONRoute` reject them while parsing, so FastAPI answers 400 instead of failing with a
500 when it tries to echo a non-finite float back in its own validation error.
"""
from __future__ import annotations

import json
import math

from fastapi import Request
from fastapi.routing import APIRoute


def reject_json_constant(name: str):
    raise ValueError(f"{name} is not a valid JSON number")


def parse_json_float(literal: str) -> float:
    value = float(literal)
    if not math.isfinite(value):  # e.g. 1e999 overflows to inf
        raise ValueError(f"{literal} is out of range for a JSON number")
    return value


class StrictJSONRequest(Request):
    """Request whose JSON body rejects NaN/Infinity/-Infinity literals and overflowing numbers
    such as 1e999 (Python's parser accepts all of them)."""

    async def json(self):
        if not hasattr(self, "_json"):
            self._json = json.loads(
                await self.body(),
                parse_constant=reject_json_constant,
                parse_float=parse_json_float,
            )
        return self._json


class StrictJSONRoute(APIRoute):
    """Route class giving handlers a non-finite-rejecting JSON body (FastAPI then answers 400, not a
    500 from trying to echo a non-finite float back in its own validation error)."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            return await original(StrictJSONRequest(request.scope, request.receive))

        return handler
