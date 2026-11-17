"""Regression tests for the backtest execution engine (synthetic data only, no network)."""
import copy
import math
import warnings

import numpy as np
import pytest

from backend.backtest import service
from backend.backtest.core.strategy_adapter import get_strategy

INITIAL = 100000.0
SMA_PARAMS = {"fast_period": 2, "slow_period": 3}

STRATEGY_CASES = [
    ("sma_crossover", {"fast_period": 5, "slow_period": 20}),
    ("ema_crossover", {"fast_period": 8, "slow_period": 21}),
    ("macd", {}),
    ("breakout", {"lookback": 20}),
    ("rsi_momentum", {"period": 14, "oversold": 40, "overbought": 60}),
    ("fibonacci_pullback", {"lookback": 20}),
    ("mean_reversion", {"period": 20, "std_dev": 1.5}),
    ("momentum", {"period": 10}),
    ("rsi_reversal", {"window": 14, "lower": 40, "upper": 60}),
    ("support_resistance", {"lookback": 30, "tolerance_pct": 0.01}),
]
COST_CASES = [(0.0, 0.0), (10.0, 5.0)]


def run(candles, strategy, params=None, initial=INITIAL, commission=0.0, slippage=0.0, **kw):
    out = service.run_backtest_service(
        "TEST", strategy, initial_capital=initial, commission_bps=commission,
        slippage_bps=slippage, **{**(params or {}), **kw}
    )
    assert "error" not in out, out
    return out


@pytest.fixture
def run_small(small_candles, patch_candles):
    patch_candles(small_candles)
    return lambda **kw: run(small_candles, "sma_crossover", SMA_PARAMS, **kw)


# ---------------------------------------------------------------------------
# 1. Hand-computable fixture
# ---------------------------------------------------------------------------

def test_hand_computed_sma_2_3_reversals(small_candles, run_small):
    """
    sma_crossover(2, 3): sign(sma2 - sma3) == sign(c[t] + c[t-1] - 2*c[t-2]).
    closes = [10,10,11,12,13,12,10, 9, 8, 9,11,12,12,11,10, 9]
    idx      0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
    c[t]+c[t-1]-2c[t-2] -> idx2:+1 3:+3 4:+3 5:+1 | 6:-4 7:-5 8:-3 9:-1 | 10:+4 11:+5 12:+2 | 13:-1 14:-3 15:-3
    So target changes on the CLOSE of idx 2 (long), 6 (short), 10 (long), 13 (short); each is filled at
    the OPEN of the next bar (idx 3, 7, 11, 14). opens[3]=11.5, opens[7]=10.5, opens[11]=10.0, opens[14]=11.5.
    The last bar (idx 15) closes at 9 and forces the final short flat at that close.
    """
    dates = [c["date"] for c in small_candles]
    out = run_small()
    trades = out["trades"]
    assert len(trades) == 4

    # Trade 1: long 100000 @ 11.5 -> sold @ 10.5 (open of idx 7)
    shares1 = 100000 / 11.5                      # 8695.652173913043
    pnl1 = shares1 * (10.5 - 11.5)               # -8695.652173913043
    equity1 = 100000 + pnl1                      # 91304.34782608696
    # Trade 2: short equity1 @ 10.5 -> covered @ 10.0 (open of idx 11)
    shares2 = equity1 / 10.5                     # 8695.652173913043
    pnl2 = shares2 * (10.5 - 10.0)               # +4347.826086956522
    equity2 = equity1 + pnl2                     # 95652.17391304348
    # Trade 3: long equity2 @ 10.0 -> sold @ 11.5 (open of idx 14)
    shares3 = equity2 / 10.0                     # 9565.217391304348
    pnl3 = shares3 * (11.5 - 10.0)               # +14347.826086956522
    equity3 = equity2 + pnl3                     # 110000.0
    # Trade 4: short equity3 @ 11.5 -> closed at last close 9.0 (end_of_data)
    shares4 = equity3 / 11.5                     # 9565.217391304348
    pnl4 = shares4 * (11.5 - 9.0)                # +23913.04347826087
    final = equity3 + pnl4                       # 133913.04347826086

    expected = [
        # side, entry idx, entry px, exit idx, exit px, shares, pnl, equity at entry, signal idx
        ("long", 3, 11.5, 7, 10.5, shares1, pnl1, 100000.0, 2),
        ("short", 7, 10.5, 11, 10.0, shares2, pnl2, equity1, 6),
        ("long", 11, 10.0, 14, 11.5, shares3, pnl3, equity2, 10),
        ("short", 14, 11.5, 15, 9.0, shares4, pnl4, equity3, 13),
    ]
    for trade, (side, ei, ep, xi, xp, sh, pnl, eq_entry, sig) in zip(trades, expected):
        assert trade["side"] == side
        assert trade["entryDate"] == dates[ei]
        assert trade["entryPrice"] == pytest.approx(ep)
        assert trade["exitDate"] == dates[xi]
        assert trade["exitPrice"] == pytest.approx(xp)
        assert trade["shares"] == pytest.approx(sh)
        assert trade["pnl"] == pytest.approx(pnl)
        assert trade["pnlPct"] == pytest.approx(pnl / eq_entry * 100)
        assert trade["duration"] == xi - ei
        assert trade["entrySignalDate"] == dates[sig]
    assert trades[-1]["exitReason"] == "end_of_data"
    assert trades[-1]["openAtEnd"] is True
    assert all(t["openAtEnd"] is False for t in trades[:-1])

    assert out["metrics"]["finalEquity"] == pytest.approx(final)
    assert out["metrics"]["totalReturn"] == pytest.approx((final - 100000) / 100000 * 100, abs=0.01)
    assert out["metrics"]["totalTrades"] == 4
    assert out["metrics"]["winRate"] == 75.0

    # Mark-to-market equity at selected bar closes
    eq = [p["value"] for p in out["equity_curve"]]
    assert eq[0] == pytest.approx(100000)
    assert eq[2] == pytest.approx(100000)                                  # still flat on the signal bar
    assert eq[3] == pytest.approx(100000 + shares1 * (12 - 11.5))          # long marked at close 12
    assert eq[6] == pytest.approx(100000 + shares1 * (10 - 11.5))          # long marked at close 10
    assert eq[7] == pytest.approx(equity1 + shares2 * (10.5 - 9))          # short @10.5 marked at close 9
    assert eq[11] == pytest.approx(equity2 + shares3 * (12 - 10.0))        # long @10.0 marked at close 12
    assert eq[14] == pytest.approx(equity3 + shares4 * (11.5 - 10))        # short @11.5 marked at close 10
    assert eq[15] == pytest.approx(final)


def test_hand_computed_costs_on_first_trade(run_small):
    """
    20 bps slippage + 10 bps commission on every fill (zero-cost numbers are in the test above).

    Sizing spends 100% of cash INCLUDING the entry commission (deliberate change in engine 2.0.0: the
    account is never overdrawn by the fee), i.e. shares * fill * (1 + 0.001) == 100000.
    """
    out = run_small(commission=10.0, slippage=20.0)
    t1 = out["trades"][0]
    entry_fill = 11.5 * (1 + 0.002)                        # buy at open 11.5, slippage worsens it: 11.523
    unit_cost = entry_fill * (1 + 0.001)                   # price plus 10 bps commission per share: 11.534523
    shares = 100000 / unit_cost                            # 8669.625956790758 shares; cash left after buying: 0
    entry_notional = shares * entry_fill                   # 99900.0999...; commission = 99.9000999... (0.1%)
    entry_commission = entry_notional * 0.001
    assert entry_notional + entry_commission == pytest.approx(100000.0)   # whole account spent, none overdrawn
    exit_fill = 10.5 * (1 - 0.002)                         # sell at open 10.5, worse by 20 bps: 10.479
    proceeds = shares * exit_fill                          # 90850.4...
    exit_commission = proceeds * 0.001                     # 90.85...
    # account: 100000 -> 0 after the buy -> proceeds - exit commission after the sell
    pnl = (proceeds - exit_commission) - 100000            # = -9241.838609190861
    assert pnl == pytest.approx(-9241.838609190861)
    assert t1["entryPrice"] == pytest.approx(entry_fill)
    assert t1["exitPrice"] == pytest.approx(exit_fill)
    assert t1["shares"] == pytest.approx(8669.625956790758)
    assert t1["pnl"] == pytest.approx(pnl)
    assert t1["pnlPct"] == pytest.approx(pnl / 100000 * 100)
    # costs make the whole run strictly worse than the gross run
    gross_out = run_small()
    assert out["metrics"]["finalEquity"] < gross_out["metrics"]["finalEquity"]
    assert out["assumptions"]["commission_bps"] == 10.0
    assert out["assumptions"]["slippage_bps"] == 20.0


def test_signal_on_last_bar_is_never_executed(small_candles, patch_candles):
    """Bar idx 6 flips the target to short but it is the last bar, so the long just closes at end_of_data."""
    patch_candles(small_candles[:7])
    out = run(small_candles[:7], "sma_crossover", SMA_PARAMS)
    assert len(out["trades"]) == 1
    t = out["trades"][0]
    shares = 100000 / 11.5
    assert (t["side"], t["entryPrice"], t["exitPrice"]) == ("long", pytest.approx(11.5), pytest.approx(10.0))
    assert t["exitReason"] == "end_of_data" and t["openAtEnd"] is True
    assert t["pnl"] == pytest.approx(shares * (10.0 - 11.5))
    assert out["metrics"]["finalEquity"] == pytest.approx(100000 + shares * (10.0 - 11.5))


def test_missing_open_fills_at_close_with_note(small_candles, patch_candles):
    candles = copy.deepcopy(small_candles)
    candles[3]["open"] = float("nan")  # the bar the first long is filled on
    patch_candles(candles)
    out = run(candles, "sma_crossover", SMA_PARAMS)
    t1 = out["trades"][0]
    assert t1["entryPrice"] == pytest.approx(12.0)  # close of idx 3 instead of open 11.5
    assert any("Open unavailable" in n for n in t1["notes"])
    assert out["trades"][1]["notes"] == []


# ---------------------------------------------------------------------------
# 2. Invariants on a longer series
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("commission,slippage", COST_CASES)
@pytest.mark.parametrize("strategy,params", STRATEGY_CASES)
def test_invariants(long_candles, patch_candles, strategy, params, commission, slippage):
    patch_candles(long_candles)
    out = run(long_candles, strategy, params, commission=commission, slippage=slippage)
    trades = out["trades"]
    final = out["metrics"]["finalEquity"]
    assert out["metrics"]["initialCapital"] == INITIAL

    # sum of currency P&L reconciles with the equity change
    assert sum(t["pnl"] for t in trades) == pytest.approx(final - INITIAL, rel=1e-6, abs=1e-6)
    # compounding the per-trade returns reproduces the final equity
    compounded = INITIAL * math.prod(1 + t["pnlPct"] / 100 for t in trades)
    assert compounded == pytest.approx(final, rel=1e-6)

    # equity is flat whenever we are out of the market before and after the bar
    rows = out["chartData"]
    for prev, cur in zip(rows, rows[1:]):
        if prev["position"] == 0 and cur["position"] == 0:
            assert cur["equity"] == prev["equity"]
    assert rows[0]["equity"] == INITIAL

    # ledger sanity
    dates = [r["date"] for r in rows]
    for t in trades:
        assert dates.index(t["exitDate"]) >= dates.index(t["entryDate"])
        assert t["shares"] > 0 and t["duration"] >= 0
    for a, b in zip(trades, trades[1:]):
        assert dates.index(b["entryDate"]) >= dates.index(a["exitDate"])  # positions never overlap


def test_strategies_actually_trade_in_the_invariant_fixture(long_candles, patch_candles):
    """Guard against vacuous invariants: most strategies must produce several trades here."""
    patch_candles(long_candles)
    counts = {s: run(long_candles, s, p)["metrics"]["totalTrades"] for s, p in STRATEGY_CASES}
    assert sum(1 for c in counts.values() if c >= 3) >= 7, counts


# ---------------------------------------------------------------------------
# 3. No look-ahead
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("k", [150, 300])
@pytest.mark.parametrize("strategy,params", STRATEGY_CASES)
def test_no_lookahead(long_candles, strategy, params, k):
    base_df = service.prepare_candles_df(long_candles)
    perturbed = copy.deepcopy(long_candles)
    for c in perturbed[k + 1:]:
        for key in ("open", "high", "low", "close"):
            c[key] *= 3
    pert_df = service.prepare_candles_df(perturbed)

    res_a, trades_a = service.run_strategy_on_df(base_df, strategy, params, INITIAL)
    res_b, trades_b = service.run_strategy_on_df(pert_df, strategy, params, INITIAL)

    # the decided target position on every bar <= k is untouched by anything after bar k
    np.testing.assert_array_equal(res_a["target"].to_numpy()[: k + 1], res_b["target"].to_numpy()[: k + 1])
    np.testing.assert_array_equal(res_a["signal"].to_numpy()[: k + 1], res_b["signal"].to_numpy()[: k + 1])

    # equity (mark-to-market at each close) up to bar k is untouched by anything after bar k
    np.testing.assert_allclose(res_a["equity"].to_numpy()[: k + 1], res_b["equity"].to_numpy()[: k + 1], rtol=0, atol=1e-9)

    dates = [str(d) for d in res_a["Date"]]
    cutoff = dates[k]

    def entered(trades):
        return [
            (t["side"], t["entryDate"], t["entryPrice"], t["shares"], t["entrySignalDate"])
            for t in trades if t["entryDate"] <= cutoff
        ]

    def exited(trades):
        return [
            (t["entryDate"], t["exitDate"], t["exitPrice"], t["pnl"])
            for t in trades if t["exitDate"] <= cutoff and t["exitReason"] != "end_of_data"
        ]

    assert entered(trades_a) == entered(trades_b)
    assert exited(trades_a) == exited(trades_b)

    # an entry is never filled on the bar that generated its signal
    for t in trades_a:
        assert t["entryDate"] > t["entrySignalDate"]
        if t["exitSignalDate"] is not None:
            assert t["exitDate"] > t["exitSignalDate"]


@pytest.mark.parametrize("strategy,params", STRATEGY_CASES)
def test_signals_do_not_depend_on_future_bars(long_candles, strategy, params):
    """
    Truncation test: the target decided on bar k must be identical whether or not bars after k exist.
    This catches a signal that peeks one bar ahead (e.g. shift(-1)), which fills at k+1 and so is
    invisible to a perturbation test that only compares results up to bar k.
    """
    df = service.prepare_candles_df(long_candles)
    full, _ = service.run_strategy_on_df(df, strategy, params, INITIAL)
    full_signal = full["signal"].to_numpy()
    full_target = full["target"].to_numpy()
    for k in range(60, len(df) - 1, 7):
        part, _ = service.run_strategy_on_df(df.iloc[: k + 1].reset_index(drop=True), strategy, params, INITIAL)
        np.testing.assert_array_equal(part["signal"].to_numpy(), full_signal[: k + 1], err_msg=f"signal k={k}")
        np.testing.assert_array_equal(part["target"].to_numpy(), full_target[: k + 1], err_msg=f"target k={k}")


def test_entry_fills_use_next_bar_open(long_candles):
    df = service.prepare_candles_df(long_candles)
    _, trades = service.run_strategy_on_df(df, "sma_crossover", {"fast_period": 5, "slow_period": 20}, INITIAL)
    by_date = {c["date"]: c for c in long_candles}
    assert trades
    for t in trades:
        assert t["entryPrice"] == pytest.approx(by_date[t["entryDate"]]["open"])
        if t["exitReason"] != "end_of_data":
            assert t["exitPrice"] == pytest.approx(by_date[t["exitDate"]]["open"])
        else:
            assert t["exitPrice"] == pytest.approx(long_candles[-1]["close"])


# ---------------------------------------------------------------------------
# 4. Benchmark
# ---------------------------------------------------------------------------

def test_benchmark_is_normalized_buy_and_hold(long_candles, patch_candles):
    patch_candles(long_candles)
    out = run(long_candles, "ema_crossover", {"fast_period": 8, "slow_period": 21}, initial=50000)
    curve = out["equity_curve"]
    closes = [c["close"] for c in long_candles]
    assert len(curve) == len(long_candles)
    assert [p["date"] for p in curve] == [c["date"] for c in long_candles]
    assert curve[0]["benchmark"] == pytest.approx(50000)
    assert curve[0]["value"] == pytest.approx(50000)
    for point, close in zip(curve, closes):
        assert point["benchmark"] / 50000 == pytest.approx(close / closes[0], rel=1e-6)
    assert out["metrics"]["benchmarkReturn"] == pytest.approx((closes[-1] / closes[0] - 1) * 100, abs=0.01)


# ---------------------------------------------------------------------------
# 6. No trades
# ---------------------------------------------------------------------------

def test_constant_prices_produce_no_trades(patch_candles):
    candles = [
        {"date": f"2024-01-{d:02d}", "open": 50.0, "high": 50.0, "low": 50.0, "close": 50.0, "volume": 1}
        for d in range(1, 31)
    ]
    patch_candles(candles)
    out = run(candles, "sma_crossover", {"fast_period": 3, "slow_period": 5}, initial=12345)
    assert out["trades"] == []
    assert {p["value"] for p in out["equity_curve"]} == {12345}
    assert out["metrics"]["totalReturn"] == 0
    assert out["metrics"]["totalTrades"] == 0
    assert out["metrics"]["finalEquity"] == 12345
    assert out["metrics"]["benchmarkReturn"] == 0


def test_strategy_that_never_signals_produces_no_trades(long_candles, patch_candles):
    patch_candles(long_candles)
    out = run(long_candles, "breakout", {"lookback": 1000})  # window longer than the data: no signals
    assert out["trades"] == []
    assert {p["value"] for p in out["equity_curve"]} == {INITIAL}
    assert out["metrics"]["totalReturn"] == 0


# ---------------------------------------------------------------------------
# 7. fibonacci_pullback is long/flat
# ---------------------------------------------------------------------------

def test_fibonacci_pullback_never_shorts(long_candles, patch_candles):
    patch_candles(long_candles)
    # the raw strategy does emit -1 ("exit when reaching old high"), so this is not vacuous
    raw = get_strategy("fibonacci_pullback", lookback=20).generate_signals(service.prepare_candles_df(long_candles))
    assert (raw["signal"] == -1).any() and (raw["signal"] == 1).any()

    out = run(long_candles, "fibonacci_pullback", {"lookback": 20})
    assert out["trades"], "expected at least one pullback entry"
    assert all(t["side"] == "long" for t in out["trades"])
    assert all(row["position"] >= 0 for row in out["chartData"])
    assert any(t["exitReason"] == "Price reached prior high" for t in out["trades"])


def test_sma_crossover_still_goes_short(small_candles, patch_candles):
    patch_candles(small_candles)
    out = run(small_candles, "sma_crossover", SMA_PARAMS)
    assert any(t["side"] == "short" for t in out["trades"])


# ---------------------------------------------------------------------------
# 8. Monte Carlo seeding
# ---------------------------------------------------------------------------

def test_monte_carlo_same_seed_identical_different_seed_differs(long_candles, patch_candles):
    patch_candles(long_candles)
    params = {"fast_period": 5, "slow_period": 20}
    a = run(long_candles, "sma_crossover", params, seed=11)
    b = run(long_candles, "sma_crossover", params, seed=11)
    c = run(long_candles, "sma_crossover", params, seed=12)
    assert a["monteCarlo"] == b["monteCarlo"]
    assert a["monteCarlo"]["percentiles"] != c["monteCarlo"]["percentiles"]
    assert a["monteCarlo"]["seed"] == 11 and c["monteCarlo"]["seed"] == 12
    assert a["assumptions"]["monteCarloSeed"] == 11
    assert run(long_candles, "sma_crossover", params)["monteCarlo"]["seed"] == 42  # default


# ---------------------------------------------------------------------------
# (d) annualization by interval, (c)/(a) validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "interval,ppy",
    [("1d", 252), ("1wk", 52), ("1mo", 12), ("1h", 252 * 6.5), ("60m", 252 * 6.5),
     ("30m", 252 * 13), ("15m", 252 * 26), ("5m", 252 * 78)],
)
def test_periods_per_year_by_interval(long_candles, patch_candles, interval, ppy):
    patch_candles(long_candles)
    out = service.run_backtest_service(
        "TEST", "ema_crossover", interval=interval, fast_period=8, slow_period=21
    )
    assert "error" not in out
    assert out["assumptions"]["periodsPerYear"] == ppy
    # annualized volatility = std(bar returns) * sqrt(periods per year)
    eq = np.array([p["value"] for p in out["equity_curve"]])
    rets = np.diff(eq) / eq[:-1]
    rets = np.r_[0.0, rets]
    expected_vol = np.std(rets, ddof=1) * math.sqrt(ppy) * 100
    assert out["metrics"]["annualVolatility"] == pytest.approx(expected_vol, rel=5e-3)


def test_unsupported_interval_and_range_are_errors(long_candles, patch_candles):
    patch_candles(long_candles)
    bad_interval = service.run_backtest_service("TEST", "ema_crossover", interval="2h")
    assert "Unsupported interval" in bad_interval["error"]
    bad_range = service.run_backtest_service("TEST", "ema_crossover", range_period="7y")
    assert "Unsupported range" in bad_range["error"] and "1y" in bad_range["error"]
    # explicit start/end still bypasses the named range
    ok = service.run_backtest_service(
        "TEST", "ema_crossover", range_period="7y", start_date="2020-01-01", end_date="2021-01-01"
    )
    assert "error" not in ok


@pytest.mark.parametrize("bad", [0, -1, "abc", float("nan"), float("inf"), True])
def test_invalid_initial_capital_rejected_by_service(long_candles, patch_candles, bad):
    patch_candles(long_candles)
    out = service.run_backtest_service("TEST", "ema_crossover", initial_capital=bad)
    assert "initial_capital" in out["error"]


# ---------------------------------------------------------------------------
# Liquidation (short squeezed through zero equity)
# ---------------------------------------------------------------------------

def _squeeze_candles(opens, closes):
    return [
        {"date": f"2024-02-{i + 1:02d}", "open": float(o), "high": max(o, c) + 0.1,
         "low": min(o, c) - 0.1, "close": float(c), "volume": 1}
        for i, (o, c) in enumerate(zip(opens, closes))
    ]


def test_short_squeeze_liquidates_account_and_stays_flat(patch_candles):
    # Same first 8 bars as the hand-computed fixture: long 3->7 (equity 91304.35), short from open 10.5.
    # idx 8 closes at 30: short marked at 91304.35 + 8695.65 * (10.5 - 30) < 0 -> wiped out at that close.
    opens = [10, 10, 10.5, 11.5, 12.5, 13, 11, 10.5, 25, 30, 30, 31]
    closes = [10, 10, 11, 12, 13, 12, 10, 9, 30, 30, 31, 30]
    candles = _squeeze_candles(opens, closes)
    patch_candles(candles)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no divide-by-zero / invalid-value warnings in metrics or Monte Carlo
        out = run(candles, "sma_crossover", SMA_PARAMS)
    equity_after_long = 100000 + (100000 / 11.5) * (10.5 - 11.5)
    assert [t["side"] for t in out["trades"]] == ["long", "short"]
    squeezed = out["trades"][1]
    assert squeezed["exitReason"] == "liquidated"
    assert squeezed["exitDate"] == candles[8]["date"]
    assert squeezed["pnlPct"] == pytest.approx(-100.0)
    assert squeezed["pnl"] == pytest.approx(-equity_after_long)
    eq = [p["value"] for p in out["equity_curve"]]
    assert all(v == 0 for v in eq[8:])
    assert all(row["position"] == 0 for row in out["chartData"][9:])  # flat afterwards, no re-entry
    assert out["metrics"]["finalEquity"] == 0
    assert out["metrics"]["totalReturn"] == pytest.approx(-100.0)
    assert out["metrics"]["maxDrawdown"] == pytest.approx(-100.0)
    assert sum(t["pnl"] for t in out["trades"]) == pytest.approx(-100000)
    assert out["monteCarlo"]["riskMetrics"]["medianMaxDrawdown"] is not None


def test_short_wiped_out_by_gap_at_exit_open_is_liquidated(patch_candles):
    # Short from open 10.5 (idx 7). idx 8 closes at 15 (still alive, signal flips long) but idx 9
    # opens at 30: covering there costs more than the account holds.
    opens = [10, 10, 10.5, 11.5, 12.5, 13, 11, 10.5, 12, 30, 30]
    closes = [10, 10, 11, 12, 13, 12, 10, 9, 15, 30, 30]
    candles = _squeeze_candles(opens, closes)
    patch_candles(candles)
    out = run(candles, "sma_crossover", SMA_PARAMS)
    short = out["trades"][1]
    assert short["side"] == "short"
    assert short["exitDate"] == candles[9]["date"]
    assert short["exitSignalDate"] == candles[8]["date"]
    assert short["exitReason"] == "liquidated"
    assert short["pnlPct"] == pytest.approx(-100.0)
    assert len(out["trades"]) == 2  # nothing is re-opened with a zero balance
    eq = [p["value"] for p in out["equity_curve"]]
    assert eq[8] > 0 and all(v == 0 for v in eq[9:])
    assert sum(t["pnl"] for t in out["trades"]) == pytest.approx(out["metrics"]["finalEquity"] - 100000)


def test_monte_carlo_handles_paths_that_lose_everything():
    import pandas as pd

    returns = pd.Series([-1.0, -1.0, -1.0, -1.0])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        mc = service._run_monte_carlo(returns, simulations=20, seed=1)
    assert mc["riskMetrics"]["medianMaxDrawdown"] == -100.0  # measured from starting capital, including an immediate wipe-out
    assert mc["percentiles"]["p50"] == -100.0
