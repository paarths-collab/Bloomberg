"""
Ledger accounting acceptance tests (offline, deterministic, synthetic data only).

Equity is computed ONLY from the trade ledger: cash(t) + position(t) * close(t). These tests pin the
hand-computed deep-dive fixture, the no-same-close-fill guarantee, fill timing, rejected orders,
replay invariants for every strategy, determinism and the market-data error contract.
"""
import json
import math

import numpy as np
import pandas as pd
import pytest

from backend.backtest import ledger as ledger_mod
from backend.backtest import service
from backend.backtest.core.strategy_adapter import STRATEGY_REGISTRY, BaseStrategy

from test_backtest_engine import SMA_PARAMS, STRATEGY_CASES, _squeeze_candles

INITIAL = 1000.0
FIXED_5 = {"mode": "fixed_quantity", "value": 5}

# idx            0    1    2    3    4    5    6
OPENS = [100.0, 100.0, 120.0, 118.0, 125.0, 115.0, 110.0]
CLOSES = [100.0, 100.0, 118.0, 125.0, 120.0, 110.0, 112.0]
# long signal on the CLOSE of idx 1 (close 100); exit signal on the CLOSE of idx 4.
SIGNALS = [0, 1, 0, 0, -1, 0, 0]
LONG_SIGNAL_BAR, EXIT_SIGNAL_BAR = 1, 4


def make_candles(dates, opens, highs, lows, closes):
    return [
        {"date": str(d), "open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": 1000}
        for d, o, h, l, c in zip(dates, opens, highs, lows, closes)
    ]


def hand_candles():
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-03-04", periods=len(CLOSES))]
    highs = [max(o, c) + 1 for o, c in zip(OPENS, CLOSES)]
    lows = [min(o, c) - 1 for o, c in zip(OPENS, CLOSES)]
    return make_candles(dates, OPENS, highs, lows, CLOSES)


class ScriptedStrategy(BaseStrategy):
    """Test-only strategy whose signal column is predetermined. Long/flat: -1 means exit."""
    name = "Scripted"
    long_only = True
    SCRIPT = SIGNALS

    def __init__(self):
        self.parameters = {}

    def generate_signals(self, df):
        df = df.copy()
        df["signal"] = list(self.SCRIPT)[: len(df)] + [0] * max(0, len(df) - len(self.SCRIPT))
        return df


@pytest.fixture
def scripted(monkeypatch):
    """scripted(script) registers a long/flat strategy named 'scripted' emitting that signal column."""
    def _register(script=SIGNALS):
        cls = type("Scripted", (ScriptedStrategy,), {"SCRIPT": list(script)})
        monkeypatch.setitem(STRATEGY_REGISTRY, "scripted", cls)
    _register()
    return _register


@pytest.fixture
def hand_df():
    return service.prepare_candles_df(hand_candles())


def spec_for(**kw):
    base = {"strategy": "scripted", "initial_capital": INITIAL, "sizing": FIXED_5, "fee_per_fill": 1.0, "symbol": "HAND"}
    base.update(kw)
    return base


def independent_equity(events, closes, initial):
    """Reference reconstruction straight from the raw events, written without the engine's helpers."""
    cash, pos, out_cash, out_pos, out_eq = initial, 0.0, [], [], []
    for i, close in enumerate(closes):
        for e in events:
            if e["bar_index"] == i:
                cash += e["cash_delta"]
                pos += e["quantity"]
        out_cash.append(cash)
        out_pos.append(pos)
        out_eq.append(cash + pos * close)
    return out_cash, out_pos, out_eq


# ---------------------------------------------------------------------------
# A. the hand fixture: 1,000 -> buy 5 @ 120 (fee 1) -> sell 5 @ 115 (fee 1) -> 973
# ---------------------------------------------------------------------------

def test_a_hand_fixture_final_equity_is_973(scripted, hand_df):
    out = service.run_spec(hand_df, spec_for())
    ledger = out["ledger"]
    fills = [e for e in ledger if e["kind"] == "fill"]
    assert len(ledger) == 2 and len(fills) == 2

    buy, sell = fills
    assert (buy["side"], buy["quantity"], buy["price"], buy["fee"]) == ("buy", 5.0, 120.0, 1.0)
    assert buy["cash_delta"] == pytest.approx(-601.0, abs=1e-9)
    assert buy["cash_after"] == pytest.approx(399.0, abs=1e-9)
    assert buy["position_after"] == 5.0
    assert (buy["reason"], buy["bar_index"], buy["signal_bar_index"]) == ("enter long", 2, LONG_SIGNAL_BAR)
    assert (sell["side"], sell["quantity"], sell["price"], sell["fee"]) == ("sell", -5.0, 115.0, 1.0)
    assert sell["cash_delta"] == pytest.approx(574.0, abs=1e-9)
    assert sell["cash_after"] == pytest.approx(973.0, abs=1e-9)
    assert sell["position_after"] == 0.0
    assert (sell["reason"], sell["bar_index"], sell["signal_bar_index"]) == ("exit long", 5, EXIT_SIGNAL_BAR)
    assert buy["date"] == "2024-03-06" and buy["signal_date"] == "2024-03-05"
    assert buy["trade_id"] == sell["trade_id"] == 1
    assert buy["instrument"] == "HAND"
    assert [e["seq"] for e in ledger] == [0, 1]

    frame = out.frame
    assert float(frame["equity"].iloc[-1]) == pytest.approx(973.0, abs=1e-9)
    assert out["metrics"]["finalEquity"] == pytest.approx(973.0, abs=1e-9)
    assert out["metrics"]["totalReturn"] == pytest.approx(-2.7, abs=1e-9)

    # cash path 1000 -> 399 -> 973
    rp = ledger_mod.replay(ledger, hand_df, initial_cash=INITIAL)
    assert rp.cash.tolist() == pytest.approx([1000, 1000, 399, 399, 399, 973, 973], abs=1e-9)
    assert rp.position.tolist() == [0, 0, 5, 5, 5, 0, 0]

    # the single round trip: pnl == -27 == final - initial
    assert len(out["trades"]) == 1
    trade = out["trades"][0]
    assert trade["pnl"] == pytest.approx(-27.0, abs=1e-9)
    assert trade["pnl"] == pytest.approx(973.0 - INITIAL, abs=1e-9)
    assert trade["pnlPct"] == pytest.approx(-2.7, abs=1e-9)
    assert (trade["entryPrice"], trade["exitPrice"], trade["shares"]) == (120.0, 115.0, 5.0)
    assert trade["openAtEnd"] is False and trade["exitReason"] == "Signal triggered"


def test_a_equity_on_every_bar_is_cash_plus_position_times_close(scripted, hand_df):
    out = service.run_spec(hand_df, spec_for())
    closes = hand_df["Close"].tolist()
    cash, pos, eq = independent_equity(out["ledger"], closes, INITIAL)
    # hand-computed: bar 2 marks 5 sh at 118 with 399 cash, bar 3 at 125, bar 4 at 120
    assert eq == pytest.approx([1000, 1000, 399 + 5 * 118, 399 + 5 * 125, 399 + 5 * 120, 973, 973], abs=1e-9)
    np.testing.assert_allclose(out.frame["equity"].to_numpy(), eq, rtol=0, atol=1e-9)
    rp = ledger_mod.replay(out["ledger"], hand_df, initial_cash=INITIAL)
    np.testing.assert_allclose(rp.cash, cash, rtol=0, atol=1e-9)
    np.testing.assert_allclose(rp.position, pos, rtol=0, atol=1e-12)
    np.testing.assert_allclose(rp.equity, eq, rtol=0, atol=1e-9)
    # the published curves are the same series, rounded to 2 dp
    assert [p["value"] for p in out["equity_curve"]] == pytest.approx(eq, abs=0.005)
    # the position column is the held direction (+1 while the 5 shares are held)
    assert out.frame["position"].tolist() == [0, 0, 1, 1, 1, 0, 0]


def test_a_replay_accepts_events_as_dicts_or_objects_and_infers_the_opening_balance(scripted, hand_df):
    out = service.run_spec(hand_df, spec_for())
    from_dicts = ledger_mod.replay(out["ledger"], hand_df)  # opening balance inferred from the first event
    from_objects = ledger_mod.replay(out.frame.attrs["ledger"], hand_df)
    from_candles = ledger_mod.replay(out["ledger"], hand_candles())
    for other in (from_objects, from_candles):
        np.testing.assert_array_equal(from_dicts.equity, other.equity)
    np.testing.assert_allclose(from_dicts.equity, out.frame["equity"].to_numpy(), rtol=0, atol=1e-9)
    with pytest.raises(ValueError):
        ledger_mod.replay([], hand_df)  # nothing to infer the balance from
    flat = ledger_mod.replay([], hand_df, initial_cash=INITIAL)
    assert flat.equity.tolist() == [INITIAL] * len(hand_df)


# ---------------------------------------------------------------------------
# B. a same-close favourable entry would have given 1,073; next-bar execution gives 973
# ---------------------------------------------------------------------------

def test_b_same_close_fill_is_not_what_the_engine_does(scripted, hand_df):
    signal_close = CLOSES[LONG_SIGNAL_BAR]
    assert signal_close == 100.0
    # explicit arithmetic for the (look-ahead) same-close fill: buy 5 @ 100, sell 5 @ 115, 1 fee each way
    same_close_final = 1000 + 5 * (115 - signal_close) - 2
    assert same_close_final == 1073

    out = service.run_spec(hand_df, spec_for())
    final = float(out.frame["equity"].iloc[-1])
    assert final == pytest.approx(973.0, abs=1e-9)
    assert final != pytest.approx(same_close_final)
    assert same_close_final - final == pytest.approx(100.0)  # the favourable fill was worth 5 * (120 - 100)

    fills = [e for e in out["ledger"] if e["kind"] == "fill"]
    assert all(e["price"] != signal_close for e in fills)
    assert all(e["bar_index"] > e["signal_bar_index"] for e in fills)
    assert all(e["date"] > e["signal_date"] for e in fills)


# ---------------------------------------------------------------------------
# C. fill_timing next_close fills at the NEXT bar's close
# ---------------------------------------------------------------------------

def test_c_next_close_fills_at_the_next_bars_close(scripted, hand_df):
    out = service.run_spec(hand_df, spec_for(fill_timing="next_close"))
    buy, sell = [e for e in out["ledger"] if e["kind"] == "fill"]
    # buy 5 @ close[2]=118 (+1 fee): 1000 - 590 - 1 = 409; sell 5 @ close[5]=110 (-1 fee): 409 + 550 - 1 = 958
    assert (buy["bar_index"], buy["price"], buy["cash_after"]) == (2, 118.0, pytest.approx(409.0, abs=1e-9))
    assert (sell["bar_index"], sell["price"], sell["cash_after"]) == (5, 110.0, pytest.approx(958.0, abs=1e-9))
    assert buy["signal_bar_index"] == LONG_SIGNAL_BAR and sell["signal_bar_index"] == EXIT_SIGNAL_BAR
    assert buy["bar_index"] > buy["signal_bar_index"]
    assert float(out.frame["equity"].iloc[-1]) == pytest.approx(958.0, abs=1e-9)
    assert out["trades"][0]["pnl"] == pytest.approx(-42.0, abs=1e-9)
    # mark-to-market on the fill bar equals the fill (no unrealised P&L yet) less the entry fee
    eq = out.frame["equity"].tolist()
    assert eq[2] == pytest.approx(409 + 5 * 118, abs=1e-9) == pytest.approx(1000 - 1, abs=1e-9)
    assert out["assumptions"]["fill_timing"] == "next_close"
    assert out["assumptions"]["execution"] == "signal on bar close, filled at next bar close"


def test_c_next_close_with_a_signal_on_the_last_bar_never_fills(scripted, hand_df):
    scripted([0, 0, 0, 0, 0, 0, 1])  # the only signal is on the last bar
    out = service.run_spec(hand_df, spec_for(fill_timing="next_close"))
    assert out["ledger"] == [] and out["trades"] == []


def test_unsupported_fill_timing_is_rejected(scripted, hand_df):
    for bad in ("same_close", "open", 3, True):
        with pytest.raises(ValueError, match="fill_timing"):
            service.run_spec(hand_df, spec_for(fill_timing=bad))


# ---------------------------------------------------------------------------
# D. rejected order: visible in the ledger, nothing else changes
# ---------------------------------------------------------------------------

def test_d_unaffordable_fixed_quantity_is_rejected_not_resized(scripted, hand_df):
    out = service.run_spec(hand_df, spec_for(sizing={"mode": "fixed_quantity", "value": 100}))  # needs 12,001
    rejected = [e for e in out["ledger"] if e["kind"] == "rejected"]
    assert len(out["ledger"]) == 1 and len(rejected) == 1
    ev = rejected[0]
    assert (ev["side"], ev["quantity"], ev["fee"], ev["cash_delta"]) == ("buy", 0.0, 0.0, 0.0)
    assert (ev["cash_after"], ev["position_after"]) == (INITIAL, 0.0)
    assert ev["reason"] == "insufficient cash" and ev["trade_id"] is None
    assert (ev["bar_index"], ev["signal_bar_index"], ev["price"]) == (2, LONG_SIGNAL_BAR, 120.0)
    assert "12001.00" in " ".join(ev["notes"])

    assert out["trades"] == []
    assert out["metrics"]["totalTrades"] == 0 and out["metrics"]["totalReturn"] == 0
    assert out["metrics"]["finalEquity"] == INITIAL
    assert out["metrics"]["rejectedOrders"] == 1
    assert {p["value"] for p in out["equity_curve"]} == {INITIAL}
    assert out.frame["position"].tolist() == [0] * len(hand_df)

    # A completed zero-return run has no events at all; the rejected event is what tells them apart.
    scripted([0] * len(CLOSES))
    quiet = service.run_spec(hand_df, spec_for())
    assert quiet["ledger"] == [] and quiet["metrics"]["rejectedOrders"] == 0
    assert quiet["metrics"]["finalEquity"] == out["metrics"]["finalEquity"]


def test_d_rejection_is_not_retried_while_the_target_persists_and_boundary_is_affordable(scripted, hand_df):
    # exactly affordable: 5 * 120 + 1 == 601 -> fills, leaving zero cash and a live position
    out = service.run_spec(hand_df, spec_for(initial_capital=601.0))
    assert [e["kind"] for e in out["ledger"]] == ["fill", "fill"]
    assert out["ledger"][0]["cash_after"] == pytest.approx(0.0, abs=1e-9)
    assert out["ledger"][1]["cash_after"] == pytest.approx(574.0, abs=1e-9)
    # one cent short -> a single rejection, even though the long target persists for 3 bars
    out = service.run_spec(hand_df, spec_for(initial_capital=600.99))
    assert [e["kind"] for e in out["ledger"]] == ["rejected"]


def test_d_fixed_quantity_shorts_are_allowed_and_credit_proceeds(hand_df, monkeypatch):
    class ShortScript(ScriptedStrategy):
        long_only = False
        SCRIPT = [0, -1, 0, 0, 1, 0, 0]

    monkeypatch.setitem(STRATEGY_REGISTRY, "scripted", ShortScript)
    out = service.run_spec(hand_df, spec_for(initial_capital=100.0))  # far too little cash to BUY 5 @ 120
    fills = list(out["ledger"])
    # short, cover on the reversal bar, then the reversal's long leg cannot be afforded (123 cash < 576)
    assert [e["kind"] for e in fills] == ["fill", "fill", "rejected"]
    short, cover = fills[0], fills[1]
    assert fills[2]["bar_index"] == cover["bar_index"] and fills[2]["position_after"] == 0.0
    assert fills[2]["reason"] == "insufficient cash"
    assert (short["quantity"], short["price"], short["reason"]) == (-5.0, 120.0, "enter short")
    assert short["cash_delta"] == pytest.approx(5 * 120 - 1)  # proceeds credited, fee debited
    assert short["cash_after"] == pytest.approx(100 + 599)
    assert short["position_after"] == -5.0
    assert (cover["quantity"], cover["price"]) == (5.0, 115.0)
    assert cover["cash_after"] == pytest.approx(100 + 599 - 5 * 115 - 1)
    assert out["trades"][0]["side"] == "short"
    assert out["trades"][0]["pnl"] == pytest.approx(5 * (120 - 115) - 2)


def test_d_percent_equity_is_never_rejected_and_matches_legacy_sizing(scripted, hand_df):
    out = service.run_spec(hand_df, {"strategy": "scripted", "initial_capital": INITIAL, "symbol": "HAND"})
    buy, sell = [e for e in out["ledger"] if e["kind"] == "fill"]
    assert buy["quantity"] == pytest.approx(1000 / 120)  # 100% of equity, fractional shares
    assert sell["cash_after"] == pytest.approx(1000 * 115 / 120)
    assert out["assumptions"]["sizing"] == "100% of equity, fractional shares"
    assert out["assumptions"]["sizingSpec"] == {"mode": "percent_equity", "value": 1.0}
    half = service.run_spec(hand_df, {"strategy": "scripted", "initial_capital": INITIAL,
                                      "sizing": {"mode": "percent_equity", "value": 0.5}})
    assert [e["quantity"] for e in half["ledger"]][0] == pytest.approx(500 / 120)
    assert half["trades"][0]["pnl"] == pytest.approx(500 / 120 * (115 - 120))


@pytest.mark.parametrize("bad", [
    5, "fixed_quantity", {"mode": "kelly"}, {"mode": "fixed_quantity"}, {"mode": "fixed_quantity", "value": 0},
    {"mode": "fixed_quantity", "value": -3}, {"mode": "fixed_quantity", "value": "x"},
    {"mode": "fixed_quantity", "value": float("nan")}, {"mode": "fixed_quantity", "value": True},
    {"mode": "percent_equity", "value": 0}, {"mode": "percent_equity", "value": 1.5},
    {"mode": "fixed_quantity", "value": 5, "leverage": 2},
])
def test_invalid_sizing_is_rejected(scripted, hand_df, bad):
    with pytest.raises(ValueError):
        service.run_spec(hand_df, spec_for(sizing=bad))


@pytest.mark.parametrize("bad", [-1, "abc", float("inf"), True])
def test_invalid_fee_per_fill_is_rejected(scripted, hand_df, bad):
    with pytest.raises(ValueError, match="fee_per_fill"):
        service.run_spec(hand_df, spec_for(fee_per_fill=bad))


# ---------------------------------------------------------------------------
# E. benchmark and strategy share a base
# ---------------------------------------------------------------------------

def test_e_benchmark_and_strategy_start_on_the_same_base(scripted, hand_df):
    out = service.run_spec(hand_df, spec_for())
    chart = out["chartData"]
    closes = hand_df["Close"].tolist()
    assert chart[0]["benchmark"] == chart[0]["equity"] == INITIAL
    assert out["equity_curve"][0]["benchmark"] == out["equity_curve"][0]["value"] == INITIAL
    for point, close in zip(chart, closes):
        assert point["benchmark"] / INITIAL == pytest.approx(close / closes[0], rel=1e-6)


def test_e_benchmark_on_a_long_series_with_a_real_strategy(long_candles):
    candles = long_candles
    df = service.prepare_candles_df(candles)
    out = service.run_spec(df, {"strategy": "ema_crossover", "params": {"fast_period": 8, "slow_period": 21},
                                "initial_capital": 50000})
    bench = [p["benchmark"] for p in out["chartData"]]
    closes = [c["close"] for c in candles]
    assert bench[0] == out["chartData"][0]["equity"] == 50000
    for b, c in zip(bench, closes):
        assert b / 50000 == pytest.approx(c / closes[0], rel=1e-6)


# ---------------------------------------------------------------------------
# F. replay invariants for all 10 strategies
# ---------------------------------------------------------------------------

F_CASES = [
    ("pct", INITIAL * 100, None, 0.0, 0.0, 0.0),
    ("pct_costs", INITIAL * 100, None, 10.0, 5.0, 2.0),
    ("fixed", 100000.0, {"mode": "fixed_quantity", "value": 50}, 0.0, 0.0, 0.0),
    ("fixed_costs", 100000.0, {"mode": "fixed_quantity", "value": 50}, 10.0, 5.0, 2.0),
    ("fixed_tight_cash", 5000.0, {"mode": "fixed_quantity", "value": 60}, 10.0, 5.0, 1.0),
]


@pytest.mark.parametrize("label,capital,sizing,commission,slippage,fee", F_CASES, ids=[c[0] for c in F_CASES])
@pytest.mark.parametrize("strategy,params", STRATEGY_CASES)
def test_f_replay_invariants(long_candles, strategy, params, label, capital, sizing, commission, slippage, fee):
    df = service.prepare_candles_df(long_candles)
    # one full (chart + Monte Carlo) case; the rest skip the slow parts
    full = (strategy, label) == ("sma_crossover", "pct_costs")
    out = service.run_spec(df, {
        "strategy": strategy, "params": params, "initial_capital": capital, "sizing": sizing,
        "commission_bps": commission, "slippage_bps": slippage, "fee_per_fill": fee, "symbol": "SYN",
    }, full=full)
    ledger = out["ledger"]
    frame = out.frame

    # replaying the ledger reproduces the reported equity curve exactly (unrounded internal series)
    rp = ledger_mod.replay(ledger, df, initial_cash=capital)
    np.testing.assert_array_equal(rp.equity, frame["equity"].to_numpy())
    if full:
        assert [p["value"] for p in out["equity_curve"]] == pytest.approx(rp.equity.tolist(), abs=0.005)
    # ... and so does a from-scratch reconstruction from the raw events
    _, _, ref_eq = independent_equity(ledger, df["Close"].tolist(), capital)
    np.testing.assert_allclose(rp.equity, ref_eq, rtol=0, atol=1e-9)

    # round trips: sum(pnl) == final - initial; every trade is derived from ledger events
    final = float(rp.equity[-1])
    assert sum(t["pnl"] for t in out["trades"]) == pytest.approx(final - capital, rel=1e-9, abs=1e-6)
    assert out["metrics"]["finalEquity"] == pytest.approx(final, abs=1e-6)
    assert rp.position[-1] == 0  # a position is never carried past the last bar
    fills = [e for e in ledger if e["kind"] != "rejected"]
    assert len(out["trades"]) == len({e["trade_id"] for e in fills})

    # cash is always a real number and each event is consistent with standard cash accounting
    assert np.isfinite(rp.cash).all() and np.isfinite(rp.equity).all()
    cash, pos = capital, 0.0
    for e in ledger:
        assert math.isfinite(e["cash_after"]) and math.isfinite(e["price"]) and math.isfinite(e["fee"])
        if e["kind"] in ("fill", "close_at_end"):
            assert e["cash_delta"] == pytest.approx(-e["quantity"] * e["price"] - e["fee"], rel=1e-12, abs=1e-9)
        elif e["kind"] == "rejected":
            assert (e["quantity"], e["fee"], e["cash_delta"]) == (0.0, 0.0, 0.0)
        else:  # liquidation: the account is swept to zero and the uncharged loss is noted
            assert e["cash_after"] == 0.0
            assert any("not charged" in n for n in e["notes"])
        cash += e["cash_delta"]
        pos += e["quantity"]
        assert e["cash_after"] == pytest.approx(cash, abs=1e-9) and e["position_after"] == pytest.approx(pos, abs=1e-9)
        assert e["side"] == ("buy" if e["quantity"] > 0 else "sell") or e["kind"] == "rejected"
        # decisions are never filled on the bar that produced them
        if e["signal_bar_index"] is not None:
            assert e["bar_index"] > e["signal_bar_index"]
    assert [e["seq"] for e in ledger] == list(range(len(ledger)))
    if sizing is None:
        # percent_equity at 100% never overdraws the account (the entry fee comes out of the sized amount)
        assert (rp.cash >= -1e-9).all() and all(e["cash_after"] >= -1e-9 for e in ledger)
    if sizing and sizing["mode"] == "fixed_quantity":
        assert all(abs(e["quantity"]) in (0.0, sizing["value"]) for e in ledger)
        assert (rp.cash >= -1e-9).all()  # fixed-quantity buys are rejected rather than financed


def test_f_the_invariants_are_not_vacuous(long_candles):
    df = service.prepare_candles_df(long_candles)
    kinds = {}
    for strategy, params in STRATEGY_CASES:
        out = service.run_spec(df, {"strategy": strategy, "params": params, "initial_capital": 5000.0,
                                    "sizing": {"mode": "fixed_quantity", "value": 60}}, full=False)
        kinds[strategy] = {e["kind"] for e in out["ledger"]}
    assert sum("fill" in k for k in kinds.values()) >= 8, kinds
    assert any("rejected" in k for k in kinds.values()), kinds  # tight cash really does reject buys
    assert any("close_at_end" in k for k in kinds.values()), kinds


def test_f_liquidation_is_a_ledger_event_that_sweeps_the_account(patch_candles):
    opens = [10, 10, 10.5, 11.5, 12.5, 13, 11, 10.5, 25, 30, 30, 31]
    closes = [10, 10, 11, 12, 13, 12, 10, 9, 30, 30, 31, 30]
    candles = _squeeze_candles(opens, closes)
    df = service.prepare_candles_df(candles)
    out = service.run_spec(df, {"strategy": "sma_crossover", "params": SMA_PARAMS, "initial_capital": 100000})
    liq = [e for e in out["ledger"] if e["kind"] == "liquidation"]
    assert len(liq) == 1
    ev = liq[0]
    assert ev["bar_index"] == 8 and ev["cash_after"] == 0.0 and ev["position_after"] == 0.0
    assert ev["quantity"] > 0 and ev["signal_bar_index"] is None and ev["cash_delta"] < 0
    assert out["ledger"][-1] is ev or out["ledger"][-1] == ev  # nothing trades afterwards
    rp = ledger_mod.replay(out["ledger"], df, initial_cash=100000)
    assert rp.equity[8:].tolist() == [0.0] * (len(df) - 8)
    assert rp.held[8] == -ev["quantity"]  # still short into the squeezed close, then flat
    assert out["trades"][-1]["exitReason"] == "liquidated"
    assert sum(t["pnl"] for t in out["trades"]) == pytest.approx(-100000)


# ---------------------------------------------------------------------------
# G. determinism and purity
# ---------------------------------------------------------------------------

def test_g_run_spec_is_deterministic(long_candles):
    df = service.prepare_candles_df(long_candles)
    spec = {"strategy": "macd", "params": {}, "initial_capital": 25000, "commission_bps": 5, "slippage_bps": 2,
            "fee_per_fill": 0.5, "sizing": {"mode": "percent_equity", "value": 0.8}, "seed": 123, "symbol": "SYN"}
    before = df.copy()
    a = service.run_spec(df, dict(spec))
    b = service.run_spec(df, dict(spec))
    assert a["ledger"] == b["ledger"] and a["ledger"]
    assert a["monteCarlo"] == b["monteCarlo"] and a["monteCarlo"]["seed"] == 123
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    pd.testing.assert_frame_equal(df, before)  # the input frame is never mutated
    c = service.run_spec(df, {**spec, "seed": 124})
    assert c["ledger"] == a["ledger"] and c["monteCarlo"] != a["monteCarlo"]  # seed only drives Monte Carlo


def test_g_spec_is_not_mutated_and_is_echoed_normalised(long_candles):
    df = service.prepare_candles_df(long_candles)
    spec = {"strategy": " SMA_Crossover ", "params": {"fast_period": 5, "slow_period": 20, "initial_capital": 1},
            "initial_capital": 2000}
    frozen = json.dumps(spec, sort_keys=True)
    out = service.run_spec(df, spec)
    assert json.dumps(spec, sort_keys=True) == frozen
    assert out["spec"]["strategy"] == "sma_crossover"
    assert out["spec"]["params"] == {"fast_period": 5, "slow_period": 20}  # run options never reach the strategy
    assert out["spec"]["sizing"] == {"mode": "percent_equity", "value": 1.0}
    assert (out["spec"]["fill_timing"], out["spec"]["fee_per_fill"], out["spec"]["seed"]) == ("next_open", 0.0, 42)
    assert service.run_spec(df, out["spec"])["ledger"] == out["ledger"]  # the echoed spec re-runs identically


def test_run_spec_rejects_unknown_spec_fields_and_bad_strategies(long_candles):
    df = service.prepare_candles_df(long_candles)
    with pytest.raises(ValueError, match="Unknown spec field"):
        service.run_spec(df, {"strategy": "macd", "colour": "red"})
    with pytest.raises(service.BacktestInputError):
        service.run_spec(df, {"strategy": "nope"})
    with pytest.raises(service.BacktestInputError):
        service.run_spec(df, {"strategy": "macd", "params": {"bogus": 1}})
    with pytest.raises(ValueError, match="No price data"):
        service.run_spec(df.iloc[0:0], {"strategy": "macd"})


def test_engine_version_is_reported(long_candles):
    assert service.ENGINE_VERSION == "2.2.0"
    out = service.run_spec(service.prepare_candles_df(long_candles), {"strategy": "macd"})
    a = out["assumptions"]
    assert a["engineVersion"] == "2.2.0" and a["fee_per_fill"] == 0 and a["fill_timing"] == "next_open"
    assert a["sizing"] == "100% of equity, fractional shares"


# ---------------------------------------------------------------------------
# Trades are derived from the ledger (no parallel bookkeeping)
# ---------------------------------------------------------------------------

def test_trades_are_derived_from_the_ledger(long_candles):
    df = service.prepare_candles_df(long_candles)
    out = service.run_spec(df, {"strategy": "sma_crossover", "params": {"fast_period": 5, "slow_period": 20},
                                "commission_bps": 10, "slippage_bps": 5, "fee_per_fill": 1.5})
    again = ledger_mod.round_trips(out["ledger"], lambda side: service._trade_reason("sma_crossover", side))
    assert again == out["trades"] and out["trades"]
    by_id = {}
    for e in out["ledger"]:
        by_id.setdefault(e["trade_id"], []).append(e)
    for t in out["trades"]:
        entry, exit_ = by_id[t["tradeId"]][0], by_id[t["tradeId"]][-1]
        assert (t["entryDate"], t["exitDate"], t["entryPrice"], t["exitPrice"]) == (
            entry["date"], exit_["date"], entry["price"], exit_["price"])
        assert t["pnl"] == pytest.approx(exit_["cash_after"] - (entry["cash_after"] - entry["cash_delta"]), abs=1e-9)
        assert t["shares"] == abs(entry["quantity"])


def test_missing_open_note_travels_with_the_ledger_events(scripted, hand_df):
    candles = hand_candles()
    candles[2]["open"] = float("nan")  # the bar the long is filled on
    out = service.run_spec(service.prepare_candles_df(candles), spec_for())
    buy = out["ledger"][0]
    assert buy["price"] == 118.0 and any("Open unavailable" in n for n in buy["notes"])
    assert any("Open unavailable" in n for n in out["trades"][0]["notes"])


# ---------------------------------------------------------------------------
# H. market-data errors are not "no data"
# ---------------------------------------------------------------------------

SINGLE = {"symbol": "TEST", "strategy": "sma_crossover", "range": "1y", "params": {"fast": 5, "slow": 20}}
MULTI = {"symbol": "TEST", "strategies": ["sma_crossover", "ema_crossover"], "range": "1y"}


def _boom_fallback(monkeypatch):
    def boom(**kwargs):
        raise service.MarketDataError("provider exploded: secret-host.internal:8443")

    monkeypatch.setattr(service, "_fetch_candles_with_fallback", boom)


def test_h_market_data_error_is_a_generic_502_on_run(api, monkeypatch):
    _boom_fallback(monkeypatch)
    for payload in (SINGLE, MULTI):
        r = api.post("/api/backtest/run", json=payload)
        assert r.status_code == 502, r.text
        assert r.json()["detail"] == "Market data unavailable"
        assert "secret" not in r.text and "exploded" not in r.text


def test_h_market_data_error_on_websocket(api, monkeypatch):
    _boom_fallback(monkeypatch)
    with api.websocket_connect("/api/backtest/ws") as ws:
        ws.send_json(SINGLE)
        msgs = []
        while True:
            msg = ws.receive_json()
            msgs.append(msg)
            if msg.get("status") in {"complete", "error"} or "error" in msg:
                break
    assert msgs[-1] == {"status": "error", "error": "Market data unavailable"}
    assert "secret" not in json.dumps(msgs)


def test_h_market_data_error_on_heatmap_and_quantstats(api, monkeypatch):
    from backend.backtest import main as backtest_main

    def boom(*a, **k):
        raise service.MarketDataError("provider exploded: secret-host.internal")

    monkeypatch.setattr(backtest_main, "fetch_candles", boom)
    r = api.post("/api/backtest/heatmap", json={"symbol": "TEST", "strategy": "sma_crossover"})
    assert r.status_code == 502 and r.json()["detail"] == "Market data unavailable"
    r = api.post("/api/backtest/quantstats-report", json={"symbol": "TEST", "strategy": "sma_crossover"})
    assert r.status_code == 502 and r.json()["detail"] == "Market data unavailable"
    assert "secret" not in r.text


def test_h_empty_data_keeps_the_existing_no_data_response(api, patch_candles, monkeypatch):
    from backend.backtest import main as backtest_main

    patch_candles([])
    r = api.post("/api/backtest/run", json=SINGLE)
    assert r.status_code == 400 and r.json()["detail"].startswith("No data found for symbol 'TEST'")
    r = api.post("/api/backtest/run", json=MULTI)
    assert r.status_code == 400 and r.json()["detail"].startswith("No data found")
    monkeypatch.setattr(backtest_main, "fetch_candles", lambda *a, **k: [])
    r = api.post("/api/backtest/heatmap", json={"symbol": "TEST", "strategy": "sma_crossover"})
    assert r.status_code == 400 and r.json()["detail"] == "No data found for heatmap"
    r = api.post("/api/backtest/quantstats-report", json={"symbol": "TEST", "strategy": "sma_crossover"})
    assert r.status_code == 400 and r.json()["detail"] == "No market data found"


def test_h_provider_status_decides_between_502_and_no_data(api, monkeypatch):
    """End to end through fetch_candles: provider 'error' -> 502; provider 'no_data' -> the 400 no-data reply."""
    monkeypatch.setattr(service, "safe_fetch_history", lambda *a, **k: {"status": "error", "error": "rate limited", "data": None})
    r = api.post("/api/backtest/run", json=SINGLE)
    assert r.status_code == 502 and r.json()["detail"] == "Market data unavailable"

    monkeypatch.setattr(service, "safe_fetch_history", lambda *a, **k: {"status": "no_data", "data": None})
    r = api.post("/api/backtest/run", json=SINGLE)
    assert r.status_code == 400 and "No data found" in r.json()["detail"]

    def raising(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(service, "safe_fetch_history", raising)
    r = api.post("/api/backtest/run", json=SINGLE)
    assert r.status_code == 502 and "reset" not in r.text


def test_h_fetch_candles_contract(monkeypatch):
    frame = pd.DataFrame(
        {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [10]},
        index=pd.to_datetime(["2024-01-02"]),
    )
    monkeypatch.setattr(service, "safe_fetch_history", lambda *a, **k: {"status": "ok", "data": frame})
    assert service.fetch_candles("TEST", "1d", "1mo") == [
        {"date": "2024-01-02", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10}
    ]
    monkeypatch.setattr(service, "safe_fetch_history", lambda *a, **k: {"status": "no_data", "data": None})
    assert service.fetch_candles("TEST", "1d", "1mo") == []
    monkeypatch.setattr(service, "safe_fetch_history", lambda *a, **k: {"status": "ok", "data": pd.DataFrame()})
    assert service.fetch_candles("TEST", "1d", "1mo") == []
    monkeypatch.setattr(service, "safe_fetch_history", lambda *a, **k: {"status": "error", "error": "x"})
    with pytest.raises(service.MarketDataError):
        service.fetch_candles("TEST", "1d", "1mo")
    with pytest.raises(ValueError, match="Unsupported range"):  # request errors are still ValueErrors
        service.fetch_candles("TEST", "1d", "7y")


def test_h_alternate_market_failure_after_an_empty_first_lookup_is_no_data(monkeypatch):
    calls = []

    def fake_fetch(symbol, interval, period, start=None, end=None, market="us"):
        calls.append(market)
        if market == "us":
            return []
        raise service.MarketDataError("india lookup failed")

    monkeypatch.setattr(service, "fetch_candles", fake_fetch)
    assert service._fetch_candles_with_fallback("ZZZZ", "1d", "1y", None, None, "us") == []
    assert calls == ["us", "india"]
    calls.clear()

    def first_fails(symbol, interval, period, start=None, end=None, market="us"):
        calls.append(market)
        raise service.MarketDataError("down")

    monkeypatch.setattr(service, "fetch_candles", first_fails)
    with pytest.raises(service.MarketDataError):
        service._fetch_candles_with_fallback("ZZZZ", "1d", "1y", None, None, "us")
    assert calls == ["us"]  # an outage is not retried as if the market were wrong


# ---------------------------------------------------------------------------
# Sizing never overdraws; zero-cash exits; liquidation notes
# ---------------------------------------------------------------------------

def test_percent_equity_sizing_spends_cash_including_fees(scripted, hand_df):
    # 100% sizing with 10 bps commission and a 5.0 fixed fee: shares * 120 * 1.001 + 5 == 1000
    out = service.run_spec(hand_df, {"strategy": "scripted", "initial_capital": INITIAL, "commission_bps": 10,
                                     "fee_per_fill": 5.0})
    buy, sell = out["ledger"]
    assert buy["quantity"] == pytest.approx((1000 - 5.0) / (120 * 1.001))  # 8.2858...
    assert buy["fee"] == pytest.approx(buy["quantity"] * 120 * 0.001 + 5.0)
    assert buy["cash_after"] == pytest.approx(0.0, abs=1e-9)
    assert sell["cash_after"] == pytest.approx(buy["quantity"] * 115 * (1 - 0.001) - 5.0)
    # a fee that eats the whole account is a visible rejection, not a silent skip or an overdraft
    tiny = service.run_spec(hand_df, {"strategy": "scripted", "initial_capital": 4.0, "fee_per_fill": 5.0})
    assert [e["kind"] for e in tiny["ledger"]] == ["rejected"] and tiny["ledger"][0]["reason"] == "insufficient cash"
    assert tiny["metrics"]["finalEquity"] == 4.0


def test_exit_that_leaves_exactly_zero_is_not_a_liquidation(monkeypatch):
    class ShortScript(ScriptedStrategy):
        long_only = False
        SCRIPT = [0, -1, -1, 1, 0, 0, 0]

    monkeypatch.setitem(STRATEGY_REGISTRY, "scripted", ShortScript)
    opens = [100.0, 100.0, 120.0, 125.0, 130.0, 130.0, 130.0]
    closes = [100.0, 100.0, 125.0, 126.0, 130.0, 130.0, 130.0]
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-03-04", periods=7)]
    candles = make_candles(dates, opens, [max(o, c) + 1 for o, c in zip(opens, closes)],
                           [min(o, c) - 1 for o, c in zip(opens, closes)], closes)
    df = service.prepare_candles_df(candles)
    # short 5 @ 120 with 50 cash -> 650; marks 25, 20 (alive); the long signal on bar 3 covers 5 @ 130 on bar 4: 650 - 650 = 0
    out = service.run_spec(df, {"strategy": "scripted", "initial_capital": 50.0, "sizing": {"mode": "fixed_quantity", "value": 5}})
    kinds = [(e["kind"], e["reason"]) for e in out["ledger"][:2]]
    assert kinds == [("fill", "enter short"), ("fill", "exit short")]
    cover = out["ledger"][1]
    assert cover["cash_after"] == 0.0 and cover["cash_delta"] == pytest.approx(-650.0)
    assert not any("not charged" in n for n in cover["notes"])
    assert out["trades"][0]["exitReason"] != "liquidated" and out["trades"][0]["pnl"] == pytest.approx(-50.0)
    assert out["trades"][0]["pnlPct"] == pytest.approx(-100.0)


def test_liquidation_event_notes_the_uncharged_loss(patch_candles):
    candles = _squeeze_candles(
        [10, 10, 10.5, 11.5, 12.5, 13, 11, 10.5, 25, 30, 30, 31], [10, 10, 11, 12, 13, 12, 10, 9, 30, 30, 31, 30])
    out = service.run_spec(service.prepare_candles_df(candles), {"strategy": "sma_crossover", "params": SMA_PARAMS})
    ev = [e for e in out["ledger"] if e["kind"] == "liquidation"][0]
    note = " ".join(ev["notes"])
    assert "loss beyond the account balance is not charged" in note and "shortfall" in note
    assert any("not charged" in n for n in out["trades"][-1]["notes"])
    # a gap through zero at the exit open (signal-driven liquidation) is noted too
    gap = _squeeze_candles([10, 10, 10.5, 11.5, 12.5, 13, 11, 10.5, 12, 30, 30], [10, 10, 11, 12, 13, 12, 10, 9, 15, 30, 30])
    out = service.run_spec(service.prepare_candles_df(gap), {"strategy": "sma_crossover", "params": SMA_PARAMS})
    ev = [e for e in out["ledger"] if e["kind"] == "liquidation"][0]
    assert ev["signal_bar_index"] == 8 and ev["bar_index"] == 9 and any("not charged" in n for n in ev["notes"])


def test_sizing_description_documents_the_rules(scripted, hand_df):
    text = service.run_spec(hand_df, spec_for())["assumptions"]["sizing"]
    assert "not retried" in text and "no margin check" in text and "rejected" in text


# ---------------------------------------------------------------------------
# Benchmark comes from a ledger; attrs are set last (performance)
# ---------------------------------------------------------------------------

def test_benchmark_is_a_replayed_buy_and_hold_ledger(monkeypatch, long_candles):
    df = service.prepare_candles_df(long_candles)
    replays = []
    real = service.replay

    def spy(events, bars, initial_cash=None):
        replays.append(list(events))
        return real(events, bars, initial_cash=initial_cash)

    monkeypatch.setattr(service, "replay", spy)
    out = service.run_spec(df, {"strategy": "macd", "initial_capital": 12345.0}, full=False)
    assert len(replays) == 2  # strategy ledger + one-event benchmark ledger
    bench = replays[1]
    assert len(bench) == 1 and bench[0].kind == "fill" and bench[0].bar_index == 0 and bench[0].fee == 0
    assert bench[0].price == float(df["Close"].iloc[0])
    closes = df["Close"].to_numpy()
    np.testing.assert_allclose(out.frame["benchmark"].to_numpy(), 12345.0 * closes / closes[0], rtol=1e-12, atol=0)
    assert out.frame["benchmark"].iloc[0] == 12345.0


def test_frame_attrs_are_empty_while_results_are_derived(monkeypatch, long_candles):
    """DataFrame.attrs are deep-copied on every column access (~8x slowdown with a ledger in them), so they
    must only be attached once all the derived work is done."""
    df = service.prepare_candles_df(long_candles)
    seen = {}
    for name in ("_compute_metrics", "_build_chart_data", "_run_monte_carlo"):
        real = getattr(service, name)

        def spy(*args, __real=real, __name=name, **kw):
            frame = next((a for a in args if isinstance(a, pd.DataFrame)), None)
            if frame is not None:
                seen[__name] = dict(frame.attrs)
            return __real(*args, **kw)

        monkeypatch.setattr(service, name, spy)
    out = service.run_spec(df, {"strategy": "sma_crossover", "params": {"fast_period": 5, "slow_period": 20}})
    assert seen["_compute_metrics"] == {} and seen["_build_chart_data"] == {}
    assert set(out.frame.attrs) == {"trades", "ledger"} and out.frame.attrs["ledger"]


# ---------------------------------------------------------------------------
# fetch_candles: only the provider call maps to MarketDataError
# ---------------------------------------------------------------------------

def _frame_with_nan_volume():
    return pd.DataFrame(
        {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [float("nan")]},
        index=pd.to_datetime(["2024-01-02"]),
    )


def test_candle_building_bugs_are_not_market_data_errors(api, monkeypatch):
    monkeypatch.setattr(service, "safe_fetch_history", lambda *a, **k: {"status": "ok", "data": _frame_with_nan_volume()})
    with pytest.raises(ValueError) as exc:  # int(NaN): a local bug, not a provider outage
        service.fetch_candles("TEST", "1d", "1mo")
    assert not isinstance(exc.value, service.MarketDataError)
    r = api.post("/api/backtest/run", json=SINGLE)
    assert r.status_code == 500 and "internal error" in r.json()["detail"].lower()
    assert "NaN" not in r.text and "nan" not in r.json()["detail"].lower()
    r = api.post("/api/backtest/heatmap", json={"symbol": "TEST", "strategy": "sma_crossover"})
    assert r.status_code == 500 and "nan" not in r.text.lower()
    r = api.post("/api/backtest/heatmap", json={"symbol": "TEST", "strategy": "sma_crossover", "range": "7y"})
    assert r.status_code == 400 and "Unsupported range" in r.json()["detail"]  # bad requests are still 400
