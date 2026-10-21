"""Shared fixtures for the backtest engine tests. All data is synthetic; nothing touches the network."""
import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.backtest import service


def make_candles(dates, opens, highs, lows, closes):
    return [
        {
            "date": str(d),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": 1000,
        }
        for d, o, h, l, c in zip(dates, opens, highs, lows, closes)
    ]


def candles_to_df(candles):
    return service.prepare_candles_df(candles)


def small_fixture_candles():
    """16 bars built so sma_crossover(fast=2, slow=3) opens a long, reverses to short, back to long
    and to short again (see test_backtest_engine.test_hand_computed_*)."""
    closes = [10, 10, 11, 12, 13, 12, 10, 9, 8, 9, 11, 12, 12, 11, 10, 9]
    opens = [10, 10, 10.5, 11.5, 12.5, 13, 11, 10.5, 9.5, 8.5, 8.5, 10.0, 11.5, 12, 11.5, 10.0]
    highs = [max(o, c) + 0.2 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 0.2 for o, c in zip(opens, closes)]
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-02", periods=len(closes))]
    return make_candles(dates, opens, highs, lows, closes)


def long_fixture_candles(n=500, seed=7):
    """Deterministic ~500 bar series with trends, reversals and noise so every strategy trades."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    noise = np.cumsum(rng.normal(0, 0.6, n))
    closes = 100 + 18 * np.sin(2 * np.pi * t / 90) + 7 * np.sin(2 * np.pi * t / 23) + noise
    closes = np.maximum(closes, 20.0)
    prev = np.r_[closes[0], closes[:-1]]
    opens = prev * (1 + rng.normal(0, 0.004, n))
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.004, n)))
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2020-01-01", periods=n)]
    return make_candles(dates, opens, highs, lows, closes)


@pytest.fixture
def small_candles():
    return small_fixture_candles()


@pytest.fixture
def long_candles():
    return long_fixture_candles()


@pytest.fixture
def patch_candles(monkeypatch):
    """patch_candles(candles) makes the backtest service read these candles instead of fetching."""
    calls = []

    def _patch(candles):
        def fake(**kwargs):
            calls.append(kwargs)
            return [dict(c) for c in candles]

        monkeypatch.setattr(service, "_fetch_candles_with_fallback", fake)
        return calls

    return _patch


@pytest.fixture(scope="module")
def api():
    """Minimal app with only the backtest router (avoids booting the whole backend)."""
    from backend.backtest.main import router

    app = FastAPI()
    app.include_router(router, prefix="/api/backtest")
    with TestClient(app) as client:
        yield client
