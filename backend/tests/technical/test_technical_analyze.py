"""Regression tests for GET/POST /api/technical/analyze (offline, deterministic data)."""
import pandas as pd
import pytest

from backend.technical import main as technical_main

URL = "/api/technical/analyze"
SMA_PARAMS = {"fast_period": 5, "slow_period": 20}
STRATEGIES = ["sma_crossover", "rsi_momentum", "breakout"]


def _get(client, **q):
    q.setdefault("symbol", "TEST")
    q.setdefault("strategy", "sma_crossover")
    return client.get(URL, params=q)


def _expected_sma_signals(df, fast, slow, start):
    """Independent crossover computation straight from the fixture."""
    f = df["Close"].rolling(fast).mean()
    s = df["Close"].rolling(slow).mean()
    sig = pd.Series(0, index=df.index)
    sig[f > s] = 1
    sig[f < s] = -1
    prev = sig.shift(1).fillna(0)
    out = []
    for ts in df.index[(sig != prev) & (sig != 0)]:
        if ts >= start:
            out.append({
                "date": ts.strftime("%Y-%m-%d"),
                "type": "buy" if sig[ts] == 1 else "sell",
                "price": float(df.loc[ts, "Close"]),
            })
    return out


def test_fixture_is_used_not_network(tclient, fetch_calls):
    r = _get(tclient)
    assert r.status_code == 200
    assert len(fetch_calls) == 1
    assert fetch_calls[0]["ticker"] == "TEST"
    assert fetch_calls[0]["interval"] == "1d"
    assert fetch_calls[0]["market"] == "US"


def test_get_and_post_identical_and_range_alias(tclient):
    q = {"symbol": "TEST", "strategy": "sma_crossover", "period": "6mo"}
    g = tclient.get(URL, params={**q, "params": '{"fast_period": 5, "slow_period": 20}'})
    p = tclient.post(URL, json={**q, "params": SMA_PARAMS})
    assert g.status_code == 200 and p.status_code == 200
    assert g.json() == p.json()

    # `range` is an alias for `period` in both methods
    g2 = tclient.get(URL, params={"symbol": "TEST", "strategy": "sma_crossover", "range": "6mo",
                                  "params": '{"fast_period": 5, "slow_period": 20}'})
    p2 = tclient.post(URL, json={"symbol": "TEST", "strategy": "sma_crossover", "range": "6mo",
                                 "params": SMA_PARAMS})
    assert g2.json() == g.json() and p2.json() == g.json()


def test_response_shape_and_json_safety(tclient, ohlcv):
    r = _get(tclient, period="1y", params='{"fast_period": 5, "slow_period": 20}')
    body = r.json()
    assert "NaN" not in r.text and "Infinity" not in r.text
    assert body["symbol"] == "TEST"
    assert body["strategy"] == "sma_crossover"
    assert body["parameters"] == SMA_PARAMS
    assert body["period"] == "1y"
    assert body["interval"] == "1d"
    assert body["market"] == "US"
    assert body["end"] == ohlcv.index[-1].strftime("%Y-%m-%d")
    assert body["bars"] > 0
    assert set(body["indicators"]) == {"sma_fast", "sma_slow"}
    for series in body["indicators"].values():
        assert series and all(set(pt) == {"time", "value"} for pt in series)
        assert all(isinstance(pt["value"], float) for pt in series)
    assert "not trade recommendations" in body["assumptions"]
    latest = body["latest_signal"]
    assert latest["date"] == body["end"]
    assert latest["label"] == {1: "buy", 0: "neutral", -1: "sell"}[latest["signal"]]


def test_default_params_and_period(tclient):
    body = _get(tclient).json()
    assert body["period"] == "1y"
    assert body["parameters"] == {"fast_period": 20, "slow_period": 50}


def test_sma_signals_match_independent_computation(tclient, ohlcv):
    last = ohlcv.index[-1]
    for period, offset in [("1y", pd.DateOffset(years=1)), ("2y", pd.DateOffset(years=2)),
                           ("6mo", pd.DateOffset(months=6))]:
        body = tclient.post(URL, json={"symbol": "TEST", "strategy": "sma_crossover",
                                       "period": period, "params": SMA_PARAMS}).json()
        expected = _expected_sma_signals(ohlcv, 5, 20, last - offset)
        assert len(expected) >= 2, "fixture must contain crossovers"
        assert body["signals"] == expected
        types = {s["type"] for s in body["signals"]}
        assert types <= {"buy", "sell"}


def test_period_trimming_relative_to_last_bar(tclient, ohlcv, fetch_calls):
    last = ohlcv.index[-1]
    six = _get(tclient, period="6mo").json()
    one = _get(tclient, period="1y").json()
    allp = _get(tclient, period="max").json()

    assert pd.Timestamp(six["start"]) >= last - pd.DateOffset(months=6)
    assert pd.Timestamp(six["end"]) == last
    assert six["bars"] < one["bars"] < allp["bars"]
    assert allp["bars"] == len(ohlcv)

    # 1y window is about a year back from the last bar (not from wall-clock now)
    assert pd.Timestamp(one["start"]) >= last - pd.DateOffset(years=1)
    assert pd.Timestamp(one["start"]) - (last - pd.DateOffset(years=1)) <= pd.Timedelta(days=4)
    assert one["end"] == last.strftime("%Y-%m-%d")

    # indicators are trimmed to the same window
    for series in six["indicators"].values():
        assert series[0]["time"] >= six["start"]

    # a longer history than requested is fetched for warm-up
    by_period = {c["period"] for c in fetch_calls}
    assert by_period == {"2y", "max"}


def test_period_aliases_normalised(tclient):
    assert _get(tclient, period="6m").json() == _get(tclient, period="6mo").json()
    assert _get(tclient, period="ALL").json()["period"] == "max"


def test_unknown_strategy_400(tclient, fetch_calls):
    r = _get(tclient, strategy="nope")
    assert r.status_code == 400
    for name in STRATEGIES:
        assert name in r.json()["detail"]
    assert fetch_calls == []


def test_invalid_params_400(tclient):
    assert _get(tclient, params="{not json").status_code == 400
    assert _get(tclient, params="[1, 2]").status_code == 400
    assert tclient.post(URL, json={"symbol": "TEST", "strategy": "sma_crossover",
                                   "params": [1, 2]}).status_code == 400
    # rejected by the strategy constructor
    assert _get(tclient, params='{"bogus": 1}').status_code == 400
    assert _get(tclient, params='{"fast_period": "abc"}').status_code == 400


def test_unknown_period_400_lists_supported(tclient, fetch_calls):
    r = _get(tclient, period="7d")
    assert r.status_code == 400
    detail = r.json()["detail"]
    for value in ("1mo", "3mo", "6mo", "1y", "2y", "5y", "max"):
        assert value in detail
    assert fetch_calls == []


def test_empty_data_404(tclient, monkeypatch):
    monkeypatch.setattr(technical_main.market_service, "fetch_ohlcv",
                        lambda *a, **k: pd.DataFrame())
    r = _get(tclient)
    assert r.status_code == 404
    assert r.json()["detail"] == "No data"


def test_fetch_failure_is_generic_500(tclient, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("boom-secret")

    monkeypatch.setattr(technical_main.market_service, "fetch_ohlcv", boom)
    with caplog.at_level("ERROR"):
        r = _get(tclient)
    assert r.status_code == 500
    assert "boom-secret" not in r.text
    assert "boom-secret" in caplog.text  # logged server-side with traceback


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_every_strategy_returns_200(tclient, strategy):
    for r in (_get(tclient, strategy=strategy),
              tclient.post(URL, json={"symbol": "TEST", "strategy": strategy})):
        assert r.status_code == 200
        body = r.json()
        assert body["strategy"] == strategy
        assert body["indicators"]
        assert "signal" not in body["indicators"]
        assert body["bars"] > 0
        for s in body["signals"]:
            assert s["type"] in ("buy", "sell")


def test_intraday_uses_iso_datetimes(tclient, monkeypatch, ohlcv):
    idx = pd.date_range("2024-06-03 09:30", periods=400, freq="h")
    df = ohlcv.iloc[-400:].copy()
    df.index = idx
    monkeypatch.setattr(technical_main.market_service, "fetch_ohlcv", lambda *a, **k: df.copy())
    body = _get(tclient, interval="1h", period="1mo",
                params='{"fast_period": 5, "slow_period": 20}').json()
    assert "T" in body["start"] and "T" in body["end"]
    assert all("T" in s["date"] for s in body["signals"])


def test_strategies_endpoint_still_works(tclient):
    r = tclient.get("/api/technical/strategies")
    assert r.status_code == 200
    assert {s["id"] for s in r.json()["strategies"]} == set(STRATEGIES)


# --- param validation -------------------------------------------------------

@pytest.mark.parametrize("params", [
    '{"fast_period": -3}',
    '{"fast_period": 0}',
    '{"fast_period": 1e400}',
    '{"fast_period": true}',
    '{"fast_period": 5.7}',
    '{"slow_period": "20"}',
    '{"fast_period": null}',
])
def test_semantically_bad_window_params_400(tclient, fetch_calls, params):
    r = _get(tclient, params=params)
    assert r.status_code == 400, r.text
    assert fetch_calls == []


def test_bad_params_400_via_post(tclient):
    for bad in ({"fast_period": -3}, {"fast_period": True}, {"fast_period": 5.7}):
        r = tclient.post(URL, json={"symbol": "TEST", "strategy": "sma_crossover", "params": bad})
        assert r.status_code == 400, (bad, r.text)
    r = tclient.post(URL, json={"symbol": "TEST", "strategy": "breakout", "params": {"lookback": -1}})
    assert r.status_code == 400


def test_integral_float_window_accepted(tclient):
    r = _get(tclient, params='{"fast_period": 5.0, "slow_period": 20}')
    assert r.status_code == 200
    assert r.json()["parameters"] == SMA_PARAMS


def test_rsi_threshold_validation(tclient):
    ok = _get(tclient, strategy="rsi_momentum", params='{"oversold": 25.5, "overbought": 74.5}')
    assert ok.status_code == 200
    for bad in ('{"oversold": 80, "overbought": 20}', '{"oversold": 50, "overbought": 50}',
                '{"oversold": true}', '{"overbought": 1e400}', '{"oversold": "x"}',
                '{"period": 0}'):
        r = _get(tclient, strategy="rsi_momentum", params=bad)
        assert r.status_code == 400, (bad, r.text)


# --- intraday fetch limits ---------------------------------------------------

def _intraday_df(ohlcv, freq, n=400):
    df = ohlcv.iloc[-n:].copy()
    df.index = pd.date_range("2024-06-03 09:30", periods=n, freq=freq)
    return df


def test_intraday_fetch_period_capped(tclient, monkeypatch, ohlcv):
    calls = []

    def fake(ticker, interval="1d", period="1mo", market="us"):
        calls.append((interval, period))
        return _intraday_df(ohlcv, "15min")

    monkeypatch.setattr(technical_main.market_service, "fetch_ohlcv", fake)
    assert _get(tclient, interval="15m", period="1mo").status_code == 200
    assert calls == [("15m", "60d")]

    calls.clear()
    monkeypatch.setattr(technical_main.market_service, "fetch_ohlcv",
                        lambda t, interval="1d", period="1mo", market="us":
                        (calls.append((interval, period)), _intraday_df(ohlcv, "h"))[1])
    assert _get(tclient, interval="1h", period="1y").status_code == 200
    assert calls == [("1h", "730d")]


@pytest.mark.parametrize("interval,period", [("1m", "1y"), ("1m", "1mo"), ("15m", "3mo"),
                                              ("5m", "max"), ("1h", "5y")])
def test_intraday_window_beyond_limit_400(tclient, fetch_calls, interval, period):
    r = _get(tclient, interval=interval, period=period)
    assert r.status_code == 400
    assert "limit" in r.json()["detail"]
    assert fetch_calls == []


def test_daily_fetch_period_unchanged(tclient, fetch_calls):
    assert _get(tclient, interval="1d", period="6mo").status_code == 200
    assert fetch_calls[-1]["period"] == "2y"


# --- data edge cases ---------------------------------------------------------

def test_all_nan_close_is_404(tclient, monkeypatch, ohlcv):
    df = ohlcv.copy()
    df["Close"] = float("nan")
    monkeypatch.setattr(technical_main.market_service, "fetch_ohlcv", lambda *a, **k: df.copy())
    r = _get(tclient)
    assert r.status_code == 404
    assert r.json()["detail"] == "No data"


def test_truncated_history_flag(tclient, monkeypatch, ohlcv):
    full = _get(tclient, period="1y").json()
    assert full["truncated_history"] is False

    short = ohlcv.iloc[-100:].copy()  # ~5 months of bars, less than the 1y asked for
    monkeypatch.setattr(technical_main.market_service, "fetch_ohlcv", lambda *a, **k: short.copy())
    body = _get(tclient, period="1y").json()
    assert body["truncated_history"] is True
    assert body["bars"] == 100
    assert body["start"] == short.index[0].strftime("%Y-%m-%d")

    assert _get(tclient, period="max").json()["truncated_history"] is False


def test_tz_aware_index_matches_naive(tclient, monkeypatch, ohlcv):
    naive = _get(tclient, period="1y", params='{"fast_period": 5, "slow_period": 20}').json()
    aware = ohlcv.copy()
    aware.index = aware.index.tz_localize("America/New_York")
    monkeypatch.setattr(technical_main.market_service, "fetch_ohlcv", lambda *a, **k: aware.copy())
    body = _get(tclient, period="1y", params='{"fast_period": 5, "slow_period": 20}').json()
    assert body == naive


def test_signal_change_on_first_window_bar_uses_previous_bar(tclient, monkeypatch, ohlcv):
    """A crossover on the first in-window bar is detected against the out-of-window bar before it."""
    f = ohlcv["Close"].rolling(5).mean()
    s = ohlcv["Close"].rolling(20).mean()
    sig = pd.Series(0, index=ohlcv.index)
    sig[f > s] = 1
    sig[f < s] = -1
    change_bars = list(ohlcv.index[(sig != sig.shift(1).fillna(0)) & (sig != 0)])
    assert len(change_bars) > 3

    target = None
    for d in change_bars[2:]:
        pos = ohlcv.index.get_loc(d)
        prev = ohlcv.index[pos - 1]
        for last in ohlcv.index[pos:]:
            cutoff = last - pd.DateOffset(months=6)
            if prev < cutoff <= d:
                target = (d, last)
                break
        if target:
            break
    assert target, "fixture must allow a window starting exactly on a crossover bar"
    d, last = target

    df = ohlcv.loc[:last].copy()
    monkeypatch.setattr(technical_main.market_service, "fetch_ohlcv", lambda *a, **k: df.copy())
    body = _get(tclient, period="6mo", params='{"fast_period": 5, "slow_period": 20}').json()

    assert body["start"] == d.strftime("%Y-%m-%d")
    assert body["signals"][0]["date"] == d.strftime("%Y-%m-%d")
    assert body["signals"][0]["type"] == ("buy" if sig[d] == 1 else "sell")
    assert body["signals"] == _expected_sma_signals(df, 5, 20, d)
