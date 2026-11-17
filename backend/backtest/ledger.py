"""
Trade ledger for the backtest engine.

The engine's simulation loop only DECIDES orders and posts events to a `LedgerBook`. Everything
else (per-bar cash / position / equity, drawdown, round-trip trades, metrics and the Monte Carlo
input) is derived by replaying the ledger. There is exactly one place where cash, position and
equity are computed: `LedgerBook.post` / `replay` share `apply_to_state` and `mark_to_market`.

Cash accounting (standard):
    buy  qty > 0:  cash_delta = -(qty * price) - fee
    sell qty < 0:  cash_delta = -(qty * price) - fee   (= |qty| * price - fee; short sales credit cash)
    equity(t)      = cash(t) + position(t) * close(t)

Event kinds:
    fill         an ordinary order fill (entry, exit or the legs of a reversal)
    rejected     a fixed-quantity buy that cash cannot cover; nothing changes (quantity 0, no fee)
    liquidation  the account is wiped out (equity <= 0 on a short, or the cover cost exceeds the account).
                 The position is closed and the account is swept to zero: cash_delta = -cash_before,
                 i.e. losses beyond the account balance are not charged (no negative equity).
    close_at_end a position still open on the last bar is closed at that bar's close

Pure module: no I/O, no randomness.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

LEDGER_KINDS = ("fill", "rejected", "liquidation", "close_at_end")
# Kinds that move the book. A liquidation or close_at_end with no signal is engine-initiated at the close.
_ENGINE_CLOSE_KINDS = ("liquidation", "close_at_end")


@dataclass
class LedgerEvent:
    seq: int                        # 0-based order of the event in the ledger
    date: str                       # bar timestamp of the event (same format as chart dates)
    bar_index: int                  # index of that bar
    instrument: str                 # symbol
    kind: str                       # fill | rejected | liquidation | close_at_end
    side: str                       # buy | sell
    quantity: float                 # signed share delta (0 for rejected)
    price: float                    # fill price after slippage (reference price for rejected)
    fee: float                      # fee in currency (commission_bps notional fee + fee_per_fill)
    cash_delta: float
    cash_after: float
    position_after: float           # signed shares held after the event
    reason: str                     # e.g. "enter long", "exit long", "reverse to short", "end of data"
    signal_date: Optional[str]      # bar whose close produced the decision (None if engine-initiated)
    signal_bar_index: Optional[int]
    trade_id: Optional[int]         # round trip this event belongs to (None for rejected)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d["notes"] = list(self.notes)
        return d


def event_from_dict(d: Mapping[str, Any]) -> LedgerEvent:
    names = {f.name for f in fields(LedgerEvent)}
    return LedgerEvent(**{k: v for k, v in d.items() if k in names})


def _as_events(events: Iterable[Any]) -> List[LedgerEvent]:
    return [e if isinstance(e, LedgerEvent) else event_from_dict(e) for e in events]


# ---------------------------------------------------------------------------
# The single accounting formulas
# ---------------------------------------------------------------------------

def mark_to_market(cash: float, position: float, price: float) -> float:
    """equity = cash + position * price. The only equity formula in the engine."""
    return cash + position * price


def apply_to_state(cash: float, position: float, cash_delta: float, quantity: float):
    return cash + cash_delta, position + quantity


def is_engine_initiated(ev: LedgerEvent) -> bool:
    """Forced closes at a bar's close (end of data, mark-to-market liquidation): no decision produced them."""
    return ev.kind in _ENGINE_CLOSE_KINDS and ev.signal_bar_index is None


class LedgerBook:
    """Running cash/position used by the simulation to decide orders; every change is a posted event."""

    def __init__(self, initial_cash: float, instrument: str = "", dates: Optional[Sequence[str]] = None):
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.position = 0.0
        self.instrument = instrument
        self.dates = list(dates) if dates is not None else None
        self.events: List[LedgerEvent] = []

    def equity(self, price: float) -> float:
        return mark_to_market(self.cash, self.position, price)

    def post(
        self,
        *,
        bar_index: int,
        date: str,
        kind: str,
        quantity: float,
        price: float,
        fee: float,
        reason: str,
        signal_bar_index: Optional[int] = None,
        trade_id: Optional[int] = None,
        notes: Optional[Sequence[str]] = None,
        side: Optional[str] = None,
        sweep_account: bool = False,
    ) -> LedgerEvent:
        if kind not in LEDGER_KINDS:
            raise ValueError(f"unknown ledger kind '{kind}'")
        if kind == "rejected":
            quantity, fee, cash_delta = 0.0, 0.0, 0.0
            side = side or "buy"
        else:
            cash_delta = -(quantity * price) - fee
            if sweep_account:
                cash_delta = -self.cash  # wipe-out: the account is emptied, never driven negative
            side = "buy" if quantity > 0 else "sell"
        self.cash, self.position = apply_to_state(self.cash, self.position, cash_delta, quantity)
        signal_date = None
        if signal_bar_index is not None and self.dates is not None:
            signal_date = self.dates[signal_bar_index]
        ev = LedgerEvent(
            seq=len(self.events),
            date=date,
            bar_index=int(bar_index),
            instrument=self.instrument,
            kind=kind,
            side=side,
            quantity=float(quantity),
            price=float(price),
            fee=float(fee),
            cash_delta=float(cash_delta),
            cash_after=float(self.cash),
            position_after=float(self.position),
            reason=reason,
            signal_date=signal_date,
            signal_bar_index=None if signal_bar_index is None else int(signal_bar_index),
            trade_id=trade_id,
            notes=list(notes or []),
        )
        self.events.append(ev)
        return ev


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

@dataclass
class Replay:
    cash: np.ndarray        # cash after the last event of each bar
    position: np.ndarray    # signed shares after the last event of each bar
    equity: np.ndarray      # cash + position * close, per bar
    held: np.ndarray        # shares held into the bar's close, before engine-initiated forced closes

    def as_dict(self) -> Dict[str, List[float]]:
        return {k: getattr(self, k).tolist() for k in ("cash", "position", "equity", "held")}


def _closes(bars: Any) -> np.ndarray:
    if isinstance(bars, pd.DataFrame):
        col = "Close" if "Close" in bars.columns else "close"
        return pd.to_numeric(bars[col], errors="coerce").to_numpy(dtype=float)
    if isinstance(bars, (pd.Series, np.ndarray)):
        return np.asarray(bars, dtype=float)
    out = []
    for b in bars:
        if isinstance(b, Mapping):
            out.append(float(b["Close"] if "Close" in b else b["close"]))
        else:
            out.append(float(b))
    return np.asarray(out, dtype=float)


def replay(events: Iterable[Any], bars: Any, initial_cash: Optional[float] = None) -> Replay:
    """
    Replay a ledger against the bars and return per-bar cash, position and equity.

    `events` are LedgerEvents or their dicts; `bars` is a DataFrame with a Close column (or a list of
    candle dicts / a close array). `initial_cash` defaults to the opening balance implied by the first
    event (cash_after - cash_delta); pass it explicitly for a ledger with no events.
    """
    evs = sorted(_as_events(events), key=lambda e: e.seq)
    close = _closes(bars)
    n = len(close)
    if initial_cash is None:
        if not evs:
            raise ValueError("initial_cash is required to replay an empty ledger")
        initial_cash = evs[0].cash_after - evs[0].cash_delta
    cash = float(initial_cash)
    position = 0.0

    cash_s = np.zeros(n)
    pos_s = np.zeros(n)
    held_s = np.zeros(n)
    k = 0
    for i in range(n):
        held = None
        while k < len(evs) and evs[k].bar_index <= i:
            ev = evs[k]
            if ev.bar_index < i:
                raise ValueError(f"event {ev.seq} is out of order (bar {ev.bar_index} < {i})")
            if held is None and is_engine_initiated(ev):
                held = position
            cash, position = apply_to_state(cash, position, ev.cash_delta, ev.quantity)
            k += 1
        cash_s[i] = cash
        pos_s[i] = position
        held_s[i] = position if held is None else held
    if k != len(evs):
        raise ValueError(f"event {evs[k].seq} is on bar {evs[k].bar_index}, beyond the {n} bars supplied")
    equity = np.array([mark_to_market(cash_s[i], pos_s[i], close[i]) for i in range(n)])
    return Replay(cash=cash_s, position=pos_s, equity=equity, held=held_s)


# ---------------------------------------------------------------------------
# Round trips (derived from the ledger)
# ---------------------------------------------------------------------------

def _num(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except Exception:
        return None
    return v if math.isfinite(v) else None


def round_trips(
    events: Iterable[Any],
    reason_fn: Callable[[str], str],
    open_reason: str = "end_of_data",
) -> List[Dict[str, Any]]:
    """
    One dict per completed round trip, grouped by trade_id. pnl is the cash change between the
    account just before the entry and just after the exit (the account is flat in between), so
    sum(pnl) == final cash - initial cash. `reason_fn("entry_long"|"exit_short"|...)` supplies the
    strategy-specific wording for ordinary entries/exits.
    """
    by_trade: Dict[int, List[LedgerEvent]] = {}
    for ev in sorted(_as_events(events), key=lambda e: e.seq):
        if ev.kind == "rejected" or ev.trade_id is None:
            continue
        by_trade.setdefault(ev.trade_id, []).append(ev)

    trades: List[Dict[str, Any]] = []
    for tid in sorted(by_trade):
        evs = by_trade[tid]
        if len(evs) < 2:
            continue  # never happens: an open position is always closed at the end of data
        entry, exit_ = evs[0], evs[-1]
        side = "long" if entry.quantity > 0 else "short"
        cash_before_entry = entry.cash_after - entry.cash_delta
        pnl = exit_.cash_after - cash_before_entry
        if exit_.kind == "liquidation":
            exit_reason = "liquidated"
        elif exit_.kind == "close_at_end":
            exit_reason = open_reason
        else:
            exit_reason = reason_fn("exit_" + side)
        trades.append({
            "side": side,
            "entryDate": entry.date,
            "entryPrice": _num(entry.price),
            "entryReason": reason_fn("entry_" + side),
            "exitDate": exit_.date,
            "exitPrice": _num(exit_.price),
            "exitReason": exit_reason,
            "pnl": _num(pnl),
            "pnlPct": _num(pnl / cash_before_entry * 100) if cash_before_entry else None,
            "duration": int(exit_.bar_index - entry.bar_index),
            "shares": _num(abs(entry.quantity)),
            "entrySignalDate": entry.signal_date,
            "exitSignalDate": exit_.signal_date,
            "openAtEnd": exit_.kind == "close_at_end",
            "notes": list(entry.notes) + list(exit_.notes),
            "tradeId": tid,
        })
    return trades
