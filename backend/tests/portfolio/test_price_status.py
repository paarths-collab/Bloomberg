"""
Price-source labelling: GET /api/profile/portfolio sets price_status from where the price came from
("live" only for a genuine current quote), and safe_get_price_quote / candle volume handling that feed
it. Offline: yfinance is stubbed.
"""
import types

import numpy as np
import pandas as pd
import pytest

from backend.core import safe_yfinance
from backend.services.market_data import market_service


async def _buy(client, prefix, hdr, symbol, qty, price):
    r = await client.post(prefix + "/trade", json={"symbol": symbol, "side": "buy", "quantity": qty,
                                                   "price": price}, headers=hdr)
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- safe_get_price_quote

@pytest.fixture
def fake_provider(monkeypatch):
    state = types.SimpleNamespace(info={}, history=None, info_fail=False)

    class FakeTicker:
        def __init__(self, symbol):
            pass

        @property
        def info(self):
            if state.info_fail:
                raise RuntimeError("provider down")
            return dict(state.info)

        def history(self, **kw):
            return state.history if state.history is not None else pd.DataFrame()

    monkeypatch.setattr(safe_yfinance.yf, "Ticker", FakeTicker)
    safe_yfinance.clear_cache()
    yield state
    safe_yfinance.clear_cache()


def _hist(close=77.0):
    idx = pd.to_datetime(["2024-06-12", "2024-06-13"])
    return pd.DataFrame({"Close": [70.0, close]}, index=idx)


def test_quote_source_live_with_market_time(fake_provider):
    fake_provider.info = {"currentPrice": 101.5, "previousClose": 99.0, "regularMarketTime": 1718300000}
    q = safe_yfinance.safe_get_price_quote("QLIVE")
    assert q["price"] == 101.5 and q["source"] == "live"
    assert q["as_of"].startswith("2024-06-13") and q["as_of"].endswith("+00:00")


def test_quote_regular_market_price_is_live_without_time(fake_provider):
    fake_provider.info = {"regularMarketPrice": 55.0}
    q = safe_yfinance.safe_get_price_quote("QREG")
    assert (q["price"], q["source"], q["as_of"]) == (55.0, "live", None)


def test_quote_previous_close_source(fake_provider):
    fake_provider.info = {"currentPrice": None, "regularMarketPrice": 0, "previousClose": 98.0}
    q = safe_yfinance.safe_get_price_quote("QPREV")
    assert (q["price"], q["source"], q["as_of"]) == (98.0, "previous_close", None)


def test_quote_last_close_5d_source_with_bar_date(fake_provider):
    fake_provider.info = {}
    fake_provider.history = _hist(77.0)
    q = safe_yfinance.safe_get_price_quote("Q5D")
    assert q["price"] == 77.0 and q["source"] == "last_close_5d"
    assert q["as_of"].startswith("2024-06-13")


def test_quote_unavailable(fake_provider):
    fake_provider.info_fail = True
    q = safe_yfinance.safe_get_price_quote("QNONE")
    assert q == {"price": None, "source": None, "as_of": None}


def test_non_finite_info_price_falls_through_and_safe_get_price_unchanged(fake_provider):
    fake_provider.info = {"currentPrice": float("nan"), "previousClose": 98.0}
    assert safe_yfinance.safe_get_price("QNAN") == 98.0
    safe_yfinance.clear_cache()
    fake_provider.info = {"currentPrice": 12.0}
    assert safe_yfinance.safe_get_price("QOK") == 12.0
    real = type(market_service).get_current_price  # the autouse fixture patches the instance
    assert real(market_service, "QOK") == 12.0
    safe_yfinance.clear_cache()
    fake_provider.info_fail = True
    assert safe_yfinance.safe_get_price("QGONE") is None
    assert real(market_service, "QGONE") == 0.0


# --------------------------------------------------------------------------- portfolio valuation

@pytest.mark.parametrize("quote,status,as_of", [
    ({"price": 100.0, "source": "live", "as_of": "2024-06-13T20:00:00+00:00"}, "live", "2024-06-13T20:00:00+00:00"),
    ({"price": 100.0, "source": "live", "as_of": None}, "live", None),
    ({"price": 100.0, "source": "previous_close", "as_of": None}, "previous_close", None),
    ({"price": 100.0, "source": "last_close_5d", "as_of": "2024-06-13T00:00:00"}, "stale", "2024-06-13T00:00:00"),
    ({"price": 100.0, "source": "something_new", "as_of": None}, "stale", None),  # never mislabelled live
])
async def test_each_price_source_maps_to_the_right_price_status(client, new_user, prefix, monkeypatch,
                                                                 quote, status, as_of):
    _, hdr = await new_user()
    await _buy(client, prefix, hdr, "AAPL", 10, 80)
    monkeypatch.setattr(market_service, "get_price_quote", lambda symbol: dict(quote))
    pf = (await client.get(prefix + "/portfolio", headers=hdr)).json()
    h = pf["holdings"][0]
    assert h["price_status"] == status and h["price_as_of"] == as_of
    assert h["current_price"] == 100.0 and h["current_value"] == pytest.approx(1000)
    assert pf["valuation_complete"] is True and pf["total_value"] == pytest.approx(1000)


async def test_unavailable_unchanged_and_totals_use_available_prices(client, new_user, prefix, monkeypatch):
    _, hdr = await new_user()
    await _buy(client, prefix, hdr, "AAPL", 10, 80)
    await _buy(client, prefix, hdr, "MSFT", 5, 250)
    await _buy(client, prefix, hdr, "TSLA", 2, 40)
    quotes = {
        "AAPL": {"price": 100.0, "source": "live", "as_of": None},
        "MSFT": {"price": 200.0, "source": "previous_close", "as_of": None},
        "TSLA": {"price": None, "source": None, "as_of": None},
    }
    monkeypatch.setattr(market_service, "get_price_quote", lambda s: quotes[s])
    pf = (await client.get(prefix + "/portfolio", headers=hdr)).json()
    by = {h["symbol"]: h for h in pf["holdings"]}
    assert by["AAPL"]["price_status"] == "live"
    assert by["MSFT"]["price_status"] == "previous_close" and by["MSFT"]["current_value"] == pytest.approx(1000)
    tsla = by["TSLA"]
    assert tsla["price_status"] == "unavailable" and tsla["price_as_of"] is None
    assert tsla["current_price"] is None and tsla["current_value"] is None and tsla["pl"] is None
    # totals stay null while any holding is unpriced, and the priced rows keep their own values
    assert pf["valuation_complete"] is False and pf["unpriced_symbols"] == ["TSLA"]
    assert pf["total_value"] is None and pf["total_pl"] is None
    assert pf["total_invested"] == pytest.approx(800 + 1250 + 80)

    quotes["TSLA"] = {"price": 50.0, "source": "last_close_5d", "as_of": "2024-06-13T00:00:00"}
    pf = (await client.get(prefix + "/portfolio", headers=hdr)).json()
    assert pf["valuation_complete"] is True
    assert pf["total_value"] == pytest.approx(1000 + 1000 + 100)  # stale/previous-close prices count


async def test_price_lookup_exception_is_unavailable(client, new_user, prefix, monkeypatch):
    _, hdr = await new_user()
    await _buy(client, prefix, hdr, "AAPL", 1, 80)

    def boom(symbol):
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(market_service, "get_price_quote", boom)
    pf = (await client.get(prefix + "/portfolio", headers=hdr)).json()
    assert pf["holdings"][0]["price_status"] == "unavailable"
    assert pf["total_value"] is None


async def test_existing_response_keys_are_preserved(client, new_user, prefix):
    _, hdr = await new_user()
    await _buy(client, prefix, hdr, "AAPL", 1, 80)
    pf = (await client.get(prefix + "/portfolio", headers=hdr)).json()
    assert {"holdings", "total_invested", "total_value", "total_pl", "total_pl_pct",
            "valuation_complete", "unpriced_symbols", "valued_at"} <= set(pf)
    assert {"symbol", "quantity", "avg_price", "total_invested", "current_price", "current_value",
            "pl", "pl_pct", "price_status"} <= set(pf["holdings"][0])


# --------------------------------------------------------------------------- start/end candle path

def _frame_with_gaps():
    idx = pd.date_range("2024-01-01", periods=6, freq="D")
    df = pd.DataFrame({"Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.5,
                       "Volume": 500.0}, index=idx)
    df.iloc[1, df.columns.get_loc("Close")] = np.nan   # no real price: row dropped
    df.iloc[2, df.columns.get_loc("Volume")] = np.nan  # unknown volume: null, row kept
    return df


def test_fetch_candles_start_end_path_nulls_volume_and_drops_nan_price(monkeypatch):
    monkeypatch.setattr(market_service, "get_history", lambda *a, **k: _frame_with_gaps())
    candles = market_service.fetch_candles("XYZ", start="2024-01-01", end="2024-01-07")
    assert [c["date"] for c in candles] == ["2024-01-01", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"]
    assert candles[1]["volume"] is None
    assert all(c["volume"] == 500 for c in candles if c["volume"] is not None)
    assert candles[0]["close"] == 10.5  # not rounded/changed on this path


def test_fetch_candles_start_end_path_missing_volume_column(monkeypatch):
    monkeypatch.setattr(market_service, "get_history",
                        lambda *a, **k: _frame_with_gaps().drop(columns=["Volume"]))
    candles = market_service.fetch_candles("XYZ", start="2024-01-01")
    assert len(candles) == 5 and all(c["volume"] is None for c in candles)
