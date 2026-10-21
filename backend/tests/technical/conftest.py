import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.technical import main as technical_main

LAST_BAR = pd.Timestamp("2024-06-14")  # fixed, far from wall-clock "now"
N_BARS = 800


def make_ohlcv(n: int = N_BARS, end: pd.Timestamp = LAST_BAR) -> pd.DataFrame:
    """Deterministic synthetic OHLCV: trend + sine wave so SMA crossovers occur."""
    index = pd.bdate_range(end=end, periods=n)
    i = np.arange(n, dtype=float)
    close = 100.0 + 0.05 * i + 8.0 * np.sin(i / 12.0) + 2.0 * np.sin(i / 3.1)
    open_ = close + 0.3 * np.cos(i)
    high = np.maximum(open_, close) + 1.0 + 0.2 * np.abs(np.sin(i))
    low = np.minimum(open_, close) - 1.0 - 0.2 * np.abs(np.cos(i))
    volume = 1_000_000 + (i % 50) * 10_000
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=index,
    )


@pytest.fixture
def ohlcv() -> pd.DataFrame:
    return make_ohlcv()


@pytest.fixture
def fetch_calls(monkeypatch, ohlcv):
    """Patch the data seam with the synthetic frame; returns the recorded calls."""
    calls = []

    def fake_fetch_ohlcv(ticker, interval="1d", period="1mo", market="us"):
        calls.append({"ticker": ticker, "interval": interval, "period": period, "market": market})
        return ohlcv.copy()

    monkeypatch.setattr(technical_main.market_service, "fetch_ohlcv", fake_fetch_ohlcv)
    return calls


@pytest.fixture
def tclient(fetch_calls):
    return TestClient(app)
