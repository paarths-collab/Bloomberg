import inspect
import logging
import math
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from backend.core.safe_yfinance import safe_fetch_history
from .core.strategy_adapter import get_strategy, STRATEGY_REGISTRY
from .core.data_loader import format_ticker
from .ledger import LedgerBook, replay, round_trips

logger = logging.getLogger(__name__)

INTERNAL_ERROR_MESSAGE = "Backtest failed due to an internal error."

# Bump when the execution semantics or the result schema change (reported as assumptions.engineVersion).
ENGINE_VERSION = "2.1.0"


class BacktestInputError(ValueError):
    """A problem with the request itself (bad strategy name/params); safe to show to the client."""


class MarketDataError(Exception):
    """The market-data provider failed (as opposed to returning no data). Details are logged, never shown."""


def validate_strategy_params(strategy_name: Any, params: Optional[Dict[str, Any]]) -> None:
    """Reject unknown strategies and params the strategy constructor does not accept."""
    if not isinstance(strategy_name, str):
        raise BacktestInputError("strategy must be a string")
    name = strategy_name.lower().strip()
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        available = ", ".join(STRATEGY_REGISTRY.keys())
        raise BacktestInputError(f"Strategy '{name}' not found. Available: {available}")
    allowed = [p for p in inspect.signature(cls.__init__).parameters if p != "self"]
    unknown = sorted(str(k) for k in strip_run_options(params) if k not in allowed)
    if unknown:
        raise BacktestInputError(
            f"Unknown parameter(s) for strategy '{name}': {', '.join(unknown)}. "
            f"Supported: {', '.join(allowed) or 'none'}"
        )


DEFAULT_INITIAL_CAPITAL = 100000.0
DEFAULT_MONTE_CARLO_SEED = 42

# Lookback windows accepted by the `range` request field (explicit start+end overrides this).
_PERIOD_OFFSETS = {
    "1d": pd.DateOffset(days=1),
    "5d": pd.DateOffset(days=5),
    "1mo": pd.DateOffset(months=1),
    "3mo": pd.DateOffset(months=3),
    "6mo": pd.DateOffset(months=6),
    "1y": pd.DateOffset(years=1),
    "2y": pd.DateOffset(years=2),
    "5y": pd.DateOffset(years=5),
}
SUPPORTED_RANGES = tuple(_PERIOD_OFFSETS.keys())

# Bars per year by candle interval; used to annualize Sharpe / Sortino / volatility / CAGR.
PERIODS_PER_YEAR = {
    "1d": 252.0,
    "1wk": 52.0,
    "1mo": 12.0,
    "1h": 252.0 * 6.5,
    "60m": 252.0 * 6.5,
    "30m": 252.0 * 13,
    "15m": 252.0 * 26,
    "5m": 252.0 * 78,
}
_DAILY_OR_SLOWER = {"1d", "1wk", "1mo"}

# Strategies whose signal is already a target position (0 = flat). All the others emit
# sparse event signals where 0 means "hold the previous position".
STATEFUL_STRATEGIES = {
    "momentum",
    "mean_reversion",
    "rsi_reversal",
    "rsi_momentum",
}

# Keys that configure the run rather than the strategy; never forwarded to get_strategy().
RUN_OPTION_KEYS = (
    "initial_capital", "initialCapital", "commission_bps", "slippage_bps", "seed",
    "sizing", "fee_per_fill", "fill_timing",
)

SIZING_MODES = ("percent_equity", "fixed_quantity")
FILL_TIMINGS = ("next_open", "next_close")
DEFAULT_SIZING = {"mode": "percent_equity", "value": 1.0}
DEFAULT_FILL_TIMING = "next_open"
_ZERO_TOL = 1e-9  # currency tolerance for "the exit left the account at zero" versus "below zero"
SPEC_KEYS = (
    "strategy", "params", "initial_capital", "sizing", "commission_bps", "slippage_bps",
    "fee_per_fill", "fill_timing", "interval", "seed", "symbol",
)


def validate_range(range_period: Any) -> str:
    key = str(range_period).strip().lower() if range_period is not None else ""
    if key not in _PERIOD_OFFSETS:
        raise ValueError(
            f"Unsupported range '{range_period}'. Supported values: {', '.join(SUPPORTED_RANGES)} "
            "(or pass explicit start and end dates)."
        )
    return key


def get_periods_per_year(interval: Any) -> float:
    key = str(interval).strip().lower() if interval is not None else ""
    if key not in PERIODS_PER_YEAR:
        raise ValueError(
            f"Unsupported interval '{interval}'. Supported values: {', '.join(PERIODS_PER_YEAR.keys())}."
        )
    return PERIODS_PER_YEAR[key]


def _coerce_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def validate_initial_capital(value: Any) -> float:
    capital = _coerce_number(value, "initial_capital")
    if capital <= 0:
        raise ValueError("initial_capital must be greater than 0")
    return capital


def validate_bps(value: Any, name: str) -> float:
    bps = _coerce_number(value, name)
    if bps < 0:
        raise ValueError(f"{name} must be >= 0")
    return bps


def validate_seed(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError("seed must be an integer")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("seed must be an integer")
    if not math.isfinite(number) or number != int(number) or number < 0:
        raise ValueError("seed must be a non-negative integer")
    return int(number)


def validate_fee_per_fill(value: Any) -> float:
    fee = _coerce_number(value, "fee_per_fill")
    if fee < 0:
        raise ValueError("fee_per_fill must be >= 0")
    return fee


def validate_fill_timing(value: Any) -> str:
    if not isinstance(value, str) or value.strip().lower() not in FILL_TIMINGS:
        raise ValueError(f"Unsupported fill_timing '{value}'. Supported values: {', '.join(FILL_TIMINGS)}.")
    return value.strip().lower()


def validate_sizing(value: Any) -> Dict[str, Any]:
    """
    {"mode": "percent_equity", "value": 0 < v <= 1} (default 1.0 = 100% of equity, fractional shares) or
    {"mode": "fixed_quantity", "value": shares > 0}. None -> the default.
    """
    if value is None:
        return dict(DEFAULT_SIZING)
    if not isinstance(value, dict):
        raise ValueError('sizing must be an object like {"mode": "percent_equity", "value": 1.0}')
    unknown = sorted(str(k) for k in value if k not in ("mode", "value"))
    if unknown:
        raise ValueError(f"Unknown sizing field(s): {', '.join(unknown)}. Supported: mode, value")
    mode = value.get("mode", "percent_equity")
    if not isinstance(mode, str) or mode.strip().lower() not in SIZING_MODES:
        raise ValueError(f"Unsupported sizing mode '{mode}'. Supported values: {', '.join(SIZING_MODES)}.")
    mode = mode.strip().lower()
    if mode == "percent_equity":
        number = _coerce_number(1.0 if value.get("value") is None else value["value"], "sizing.value")
        if not 0 < number <= 1:
            raise ValueError("sizing.value must be in (0, 1] for percent_equity (1.0 = 100% of equity)")
    else:
        if value.get("value") is None:
            raise ValueError("sizing.value (shares) is required for fixed_quantity")
        number = _coerce_number(value["value"], "sizing.value")
        if number <= 0:
            raise ValueError("sizing.value must be greater than 0 for fixed_quantity")
    return {"mode": mode, "value": number}


def strip_run_options(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {k: v for k, v in (params or {}).items() if k not in RUN_OPTION_KEYS}


def _load_history(ticker: str, start: str, end: str, interval: str) -> Optional[pd.DataFrame]:
    """
    Provider history lookup that keeps "the provider failed" apart from "there is no data".
    (core.data_loader / MarketDataService collapse both into an empty frame, so go to the provider
    wrapper directly.) Raises MarketDataError on a provider failure, returns None/empty for no data.
    """
    res = safe_fetch_history(ticker, interval=interval, start=start, end=end)
    status = res.get("status") if isinstance(res, dict) else None
    if status == "ok":
        return res.get("data")
    if status == "no_data":
        return None
    raise MarketDataError(f"history lookup failed for {ticker}: {res.get('error') if isinstance(res, dict) else res!r}")


def fetch_candles(
    symbol: str,
    interval: str = "1d",
    period: str = "1mo",
    start: Optional[str] = None,
    end: Optional[str] = None,
    market: str = "us",
) -> List[Dict[str, Any]]:
    """
    Backtest-local candle fetcher to keep this module self-contained.

    Returns [] when the provider answered but has no data for the symbol. Raises MarketDataError when
    the provider/fetch itself failed, so callers never mistake an outage for "no data".
    """
    if not (start and end):
        period = validate_range(period)  # raises ValueError for unknown ranges

    ticker = format_ticker(symbol, market)
    if not (start and end):
        end_ts = pd.Timestamp.now(tz="UTC").normalize()
        start_ts = end_ts - _PERIOD_OFFSETS[period]
        start = start_ts.strftime("%Y-%m-%d")
        end = end_ts.strftime("%Y-%m-%d")

    # Only the provider call maps to MarketDataError; a bug in the candle building below is a
    # genuine internal error and must surface as one (generic 500), not as "market data unavailable".
    try:
        df = _load_history(ticker, start, end, interval)
    except MarketDataError:
        logger.exception("Market data fetch failed for %s (%s, %s)", symbol, market, interval)
        raise
    except Exception as e:
        logger.exception("Market data fetch failed for %s (%s, %s)", symbol, market, interval)
        raise MarketDataError(f"fetch failed for {symbol}") from e
    if df is None or df.empty:
        return []

    date_fmt = "%Y-%m-%d" if str(interval).lower() in _DAILY_OR_SLOWER else "%Y-%m-%d %H:%M"
    candles: List[Dict[str, Any]] = []
    for idx, row in df.iterrows():
        candles.append({
            "date": idx.strftime(date_fmt) if hasattr(idx, "strftime") else str(idx),
            "open": float(row.get("Open", 0)),
            "high": float(row.get("High", 0)),
            "low": float(row.get("Low", 0)),
            "close": float(row.get("Close", 0)),
            "volume": int(row.get("Volume", 0)),
        })
    return candles


def _safe_number(value: Any) -> Optional[float]:
    try:
        val = float(value)
    except Exception:
        return None
    return val if math.isfinite(val) else None


def _resolve_market(symbol: str, market: str) -> str:
    m = (market or "us").lower()
    s = (symbol or "").upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        return "india"
    return m


def _fetch_candles_with_fallback(
    symbol: str,
    interval: str,
    range_period: str,
    start_date: Optional[str],
    end_date: Optional[str],
    market: str,
) -> List[Dict[str, Any]]:
    effective_market = _resolve_market(symbol, market)
    candles = fetch_candles(
        symbol,
        interval,
        range_period,
        start=start_date,
        end=end_date,
        market=effective_market,
    )
    if candles:
        return candles

    # If market was likely wrong, retry once with the alternate market. The first lookup succeeded
    # (it simply had no data), so a failure of this guess is treated as "no data", not an outage.
    alternate = "india" if effective_market == "us" else "us"
    try:
        return fetch_candles(
            symbol,
            interval,
            range_period,
            start=start_date,
            end=end_date,
            market=alternate,
        )
    except MarketDataError:
        logger.warning("Alternate-market lookup for %s (%s) failed; reporting no data", symbol, alternate)
        return []


def prepare_candles_df(candles: List[Dict]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    df.rename(columns={
        "date": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume"
    }, inplace=True)
    if "Close" in df.columns:
        # Bars without a usable close cannot be marked to market.
        close = pd.to_numeric(df["Close"], errors="coerce")
        df = df[np.isfinite(close)].reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Execution engine
#
# Convention (single source of truth for single, multi, heatmap, quantstats and WS runs):
#   * the target position for bar t is derived from the strategy signal on bar t's close
#     (stateful strategies: signal as-is; others: 0 = hold previous; long/flat strategies:
#     -1 = go flat);
#   * it is executed on bar t+1, never on the signal bar (no look-ahead): at that bar's OPEN
#     (fill_timing "next_open", default; if the bar has no usable Open the fill is at its Close and
#     the order is annotated) or at its CLOSE (fill_timing "next_close");
#   * sizing "percent_equity" (default 100% of current equity, fractional shares, sized so that
#     shares * price + commission + fee_per_fill equals that share of cash: cash never goes negative) or
#     "fixed_quantity" (N shares; a long buy that cash cannot cover is REJECTED, never resized, and not
#     retried while the same target persists; shorts have no margin check);
#     a reversal closes and re-opens on the same bar;
#   * costs: slippage worsens the fill price, commission is a fraction of traded notional, plus an
#     optional fixed fee per fill;
#   * a position still open on the last bar is closed at that bar's Close ("end of data"); a short
#     whose equity reaches zero is liquidated and the account stays flat.
#
# The simulation loop below only DECIDES orders and posts them to a ledger. Equity, drawdown,
# round-trip trades, metrics and Monte Carlo input are all derived by replaying that ledger
# (see ledger.py); there is no other equity formula.
# ---------------------------------------------------------------------------

def _target_positions(signal: pd.Series, stateful: bool, long_only: bool) -> pd.Series:
    sig = pd.to_numeric(signal, errors="coerce").fillna(0)
    if stateful:
        target = sig
    else:
        target = sig.replace(0, np.nan).ffill().fillna(0)
    if long_only:
        target = target.clip(lower=0)
    return np.sign(target).astype(float)


def _simulate_execution(
    df: pd.DataFrame,
    target: pd.Series,
    initial_capital: float,
    strategy_name: str,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
    fee_per_fill: float = 0.0,
    fill_timing: str = DEFAULT_FILL_TIMING,
    sizing: Optional[Dict[str, Any]] = None,
    symbol: str = "",
) -> List[Any]:
    """
    Decide orders from the target series and post them to a ledger. Returns the list of LedgerEvents.
    An order is placed on bar i when the target decided on bar i-1 differs from the target decided
    on bar i-2 and from the position held; a rejected order is not retried while the target persists.
    """
    n = len(df)
    close = pd.to_numeric(df["Close"], errors="coerce").to_numpy(dtype=float)
    if "Open" in df.columns:
        open_ = pd.to_numeric(df["Open"], errors="coerce").to_numpy(dtype=float)
    else:
        open_ = np.full(n, np.nan)
    dates = [str(d) for d in df["Date"]]
    tgt = target.to_numpy(dtype=float)
    comm = commission_bps / 10000.0
    slip = slippage_bps / 10000.0
    sizing = sizing or DEFAULT_SIZING
    fixed_qty = sizing["mode"] == "fixed_quantity"
    sizing_value = float(sizing["value"])

    book = LedgerBook(initial_capital, instrument=symbol or "UNKNOWN", dates=dates)
    dead = False  # account wiped out: nothing trades afterwards
    next_trade_id = 1
    open_trade_id: Optional[int] = None

    def _fee(qty: float, price: float) -> float:
        return abs(qty) * price * comm + fee_per_fill

    def _slipped(raw: float, qty: float) -> float:
        # Buying worsens the price upwards, selling downwards.
        return raw * (1 + slip) if qty > 0 else raw * (1 - slip)

    def _wipe_note(natural_cash_after: float) -> str:
        shortfall = max(0.0, -natural_cash_after)
        return f"account wiped out; loss beyond the account balance is not charged (shortfall {shortfall:.2f})"

    def _close_position(i: int, raw: float, reason: str, kind: str, signal_idx: Optional[int],
                        notes: List[str]) -> None:
        nonlocal dead, open_trade_id
        qty = -book.position
        price = _slipped(raw, qty)
        fee = _fee(qty, price)
        natural_after = book.cash + (-(qty * price) - fee)
        # Genuinely negative (beyond float noise) = the account cannot cover the exit. Landing exactly
        # on zero is an ordinary exit that happens to leave nothing, not a liquidation.
        wiped = natural_after < -_ZERO_TOL
        if wiped:
            dead = True
            notes = list(notes) + [_wipe_note(natural_after)]
            if kind == "fill":
                kind, reason = "liquidation", "liquidated (account equity exhausted)"
        book.post(
            bar_index=i, date=dates[i], kind=kind, quantity=qty, price=price, fee=fee, reason=reason,
            signal_bar_index=signal_idx, trade_id=open_trade_id, notes=notes, sweep_account=wiped,
        )
        open_trade_id = None

    for i in range(n):
        if i > 0 and not dead:
            desired = int(tgt[i - 1])
            previous = int(tgt[i - 2]) if i >= 2 else 0
            held_side = int(np.sign(book.position))
            if desired != held_side and desired != previous:
                notes: List[str] = []
                if fill_timing == "next_close":
                    raw = close[i]
                else:
                    raw = open_[i]
                    if not (math.isfinite(raw) and raw > 0):
                        raw = close[i]
                        notes.append(f"Open unavailable on {dates[i]}; filled at Close")
                reversing = held_side != 0
                if reversing:
                    _close_position(i, raw, "exit long" if held_side > 0 else "exit short", "fill", i - 1, notes)
                if desired != 0 and not dead:
                    price = _slipped(raw, float(desired))
                    if price <= 0 or not math.isfinite(price):
                        qty = 0.0
                    elif fixed_qty:
                        qty = sizing_value
                    else:
                        # Spend value * cash INCLUDING fees: qty*price*(1+commission) + fee_per_fill == value*cash,
                        # so a 100% entry leaves cash at zero instead of overdrawing it by the fee.
                        qty = (book.cash * sizing_value - fee_per_fill) / (price * (1 + comm))
                    if math.isfinite(qty):
                        word = "long" if desired > 0 else "short"
                        reason = ("reverse to " if reversing else "enter ") + word
                        fee = _fee(max(qty, 0.0), price)
                        unaffordable = (
                            qty <= 0
                            or (fixed_qty and desired > 0 and qty * price + fee > book.cash)
                        )
                        if unaffordable:
                            # Never silently resized; not retried while the same target persists.
                            book.post(
                                bar_index=i, date=dates[i], kind="rejected", quantity=0.0, price=price,
                                fee=0.0, reason="insufficient cash", signal_bar_index=i - 1, trade_id=None,
                                side="buy" if desired > 0 else "sell",
                                notes=notes + [
                                    f"requested {max(qty, 0.0):g} shares at {price:.6g}: needs "
                                    f"{max(qty, 0.0) * price + fee:.2f}, cash {book.cash:.2f}"
                                ],
                            )
                        else:
                            open_trade_id = next_trade_id
                            next_trade_id += 1
                            book.post(
                                bar_index=i, date=dates[i], kind="fill", quantity=desired * qty, price=price,
                                fee=fee, reason=reason, signal_bar_index=i - 1, trade_id=open_trade_id,
                                notes=notes,
                            )

        if book.position != 0:
            if book.equity(close[i]) <= 0:
                # Equity reached zero at this close (a squeezed short): the account is wiped out.
                dead = True
                qty = -book.position
                price = _slipped(close[i], qty)
                fee = _fee(qty, price)
                book.post(
                    bar_index=i, date=dates[i], kind="liquidation", quantity=qty, price=price,
                    fee=fee, reason="liquidated (equity <= 0)", signal_bar_index=None,
                    trade_id=open_trade_id, sweep_account=True,
                    notes=[_wipe_note(book.cash + (-(qty * price) - fee))],
                )
                open_trade_id = None
            elif i == n - 1:
                _close_position(i, close[i], "end of data", "close_at_end", None, [])

    return book.events


def _buy_and_hold_equity(res_df: pd.DataFrame, initial_capital: float, symbol: str = "") -> np.ndarray:
    """Benchmark curve: a one-event ledger (buy at the first close, fractional shares, no costs) replayed
    with the same replay() as the strategy, so every curve in a result comes from a ledger."""
    first_close = float(res_df["Close"].iloc[0])
    if not first_close > 0:
        return np.full(len(res_df), np.nan)
    book = LedgerBook(initial_capital, instrument=symbol or "UNKNOWN", dates=[str(d) for d in res_df["Date"]])
    book.post(
        bar_index=0, date=str(res_df["Date"].iloc[0]), kind="fill", quantity=initial_capital / first_close,
        price=first_close, fee=0.0, reason="buy and hold", trade_id=1,
    )
    return replay(book.events, res_df, initial_cash=initial_capital).equity


class SpecResult(dict):
    """run_spec's result: a plain JSON-ready dict plus the per-bar frame as an attribute."""
    frame: pd.DataFrame = None


def run_spec(df: pd.DataFrame, spec: Dict[str, Any], *, full: bool = True) -> SpecResult:
    """
    THE engine entry point (pure and deterministic for a given df + spec: no I/O, seeded randomness).

    spec keys (all but `strategy` optional):
        strategy        registry id, e.g. "sma_crossover"
        params          strategy constructor params (run options are stripped)
        initial_capital default 100000
        sizing          {"mode": "percent_equity", "value": 1.0} | {"mode": "fixed_quantity", "value": shares}
        commission_bps, slippage_bps, fee_per_fill   default 0
        fill_timing     "next_open" (default) | "next_close"
        interval        candle interval used to annualise metrics, default "1d"
        seed            Monte Carlo seed, default 42
        symbol          label for the ledger / result

    Returns a SpecResult: a JSON-ready dict (symbol, strategy, initialCapital, metrics, chartData, trades,
    equity_curve, monteCarlo, assumptions, ledger, spec) whose `.frame` attribute is the per-bar frame.
    With full=False the chart/Monte Carlo parts are skipped (used by the heatmap and QuantStats paths).
    Raises BacktestInputError for a bad strategy/params and ValueError for invalid settings.
    """
    s = normalize_spec(spec)
    ppy = get_periods_per_year(s["interval"])
    validate_strategy_params(s["strategy"], s["params"])
    name = s["strategy"]
    try:
        strategy = get_strategy(name, **s["params"])
    except (ValueError, TypeError) as e:
        raise BacktestInputError(f"Invalid parameters for strategy '{name}': {e}")
    if df is None or len(df) == 0:
        raise ValueError("No price data to backtest")

    initial_capital = s["initial_capital"]
    res_df = strategy.generate_signals(df.copy()).reset_index(drop=True)
    long_only = bool(getattr(strategy, "long_only", False))
    target = _target_positions(res_df["signal"], name in STATEFUL_STRATEGIES, long_only)

    # 1) the loop decides orders and emits ledger events ...
    events = _simulate_execution(
        res_df, target, initial_capital, name, s["commission_bps"], s["slippage_bps"],
        s["fee_per_fill"], s["fill_timing"], s["sizing"], s["symbol"],
    )
    # 2) ... and everything below is derived by replaying them.
    rp = replay(events, res_df, initial_cash=initial_capital)
    trades = round_trips(events, lambda side: _trade_reason(name, side))

    res_df["target"] = target.to_numpy()
    res_df["position"] = np.sign(rp.held)
    res_df["equity"] = rp.equity
    res_df["strategy_returns"] = pd.Series(rp.equity).pct_change().replace([np.inf, -np.inf], np.nan).fillna(0).to_numpy()
    res_df["pct_change"] = res_df["Close"].pct_change().fillna(0)
    res_df["peak"] = res_df["equity"].cummax()
    res_df["drawdown"] = ((res_df["equity"] - res_df["peak"]) / res_df["peak"]).fillna(0)
    res_df["benchmark"] = _buy_and_hold_equity(res_df, initial_capital, s["symbol"])

    metrics = _compute_metrics(res_df, trades, initial_capital, ppy)
    # A run whose only activity was rejected orders looks like a zero-return run; say so explicitly.
    metrics["rejectedOrders"] = sum(1 for e in events if e.kind == "rejected")
    result = SpecResult({
        "symbol": s["symbol"],
        "strategy": name,
        "initialCapital": initial_capital,
        "metrics": metrics,
        "trades": trades,
        "assumptions": _build_assumptions(
            s["commission_bps"], s["slippage_bps"], ppy, s["seed"],
            sizing=s["sizing"], fee_per_fill=s["fee_per_fill"], fill_timing=s["fill_timing"],
        ),
        "ledger": [e.to_dict() for e in events],
        "spec": s,
    })
    if full:
        chart_data = _build_chart_data(res_df)
        result["chartData"] = chart_data
        # value = strategy equity, benchmark = buy-and-hold, both in account currency
        result["equity_curve"] = [{**d, "value": d["equity"], "benchmark": d["benchmark"]} for d in chart_data]
        result["monteCarlo"] = _run_monte_carlo(
            res_df["strategy_returns"], initial_capital=initial_capital, seed=s["seed"]
        )
    # Set last: DataFrame.attrs are deep-copied on every column access, which would slow all the above.
    res_df.attrs["trades"] = trades
    res_df.attrs["ledger"] = events
    result.frame = res_df
    return result


def normalize_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a spec and fill in defaults. Idempotent. Raises ValueError (BacktestInputError for the strategy)."""
    if not isinstance(spec, dict):
        raise BacktestInputError("spec must be an object")
    unknown = sorted(str(k) for k in spec if k not in SPEC_KEYS)
    if unknown:
        raise ValueError(f"Unknown spec field(s): {', '.join(unknown)}. Supported: {', '.join(SPEC_KEYS)}")
    strategy = spec.get("strategy")
    if not isinstance(strategy, str):
        raise BacktestInputError("strategy must be a string")
    params = spec.get("params") or {}
    if not isinstance(params, dict):
        raise BacktestInputError("params must be an object")

    def opt(key, default):
        return default if spec.get(key) is None else spec[key]

    interval = str(opt("interval", "1d")).strip().lower()
    get_periods_per_year(interval)
    return {
        "strategy": strategy.lower().strip(),
        "params": dict(strip_run_options(params)),
        "initial_capital": validate_initial_capital(opt("initial_capital", DEFAULT_INITIAL_CAPITAL)),
        "sizing": validate_sizing(spec.get("sizing")),
        "commission_bps": validate_bps(opt("commission_bps", 0.0), "commission_bps"),
        "slippage_bps": validate_bps(opt("slippage_bps", 0.0), "slippage_bps"),
        "fee_per_fill": validate_fee_per_fill(opt("fee_per_fill", 0.0)),
        "fill_timing": validate_fill_timing(opt("fill_timing", DEFAULT_FILL_TIMING)),
        "interval": interval,
        "seed": validate_seed(opt("seed", DEFAULT_MONTE_CARLO_SEED)),
        "symbol": str(opt("symbol", "")).strip(),
    }


def run_strategy_on_df(
    df: pd.DataFrame,
    strategy_name: str,
    params: Optional[Dict[str, Any]] = None,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
    fee_per_fill: float = 0.0,
    fill_timing: str = DEFAULT_FILL_TIMING,
    sizing: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """Thin wrapper over run_spec: returns (result frame, round-trip trades)."""
    result = run_spec(df, {
        "strategy": strategy_name, "params": params, "initial_capital": initial_capital,
        "commission_bps": commission_bps, "slippage_bps": slippage_bps,
        "fee_per_fill": fee_per_fill, "fill_timing": fill_timing, "sizing": sizing,
    }, full=False)
    return result.frame, result["trades"]


def run_backtest_on_df(
    df: pd.DataFrame,
    strategy_name: str,
    initial_capital: float = 100000,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
    fee_per_fill: float = 0.0,
    fill_timing: str = DEFAULT_FILL_TIMING,
    sizing: Optional[Dict[str, Any]] = None,
    **params
) -> pd.DataFrame:
    res_df, _ = run_strategy_on_df(
        df, strategy_name, params, initial_capital, commission_bps, slippage_bps,
        fee_per_fill, fill_timing, sizing,
    )
    return res_df



def _compute_drawdown_duration(drawdown_series: pd.Series) -> int:
    max_duration = 0
    current = 0
    for val in drawdown_series.fillna(0).tolist():
        if val < 0:
            current += 1
            max_duration = max(max_duration, current)
        else:
            current = 0
    return int(max_duration)


def _trade_reason(strategy_name: str, side: str) -> str:
    reasons = {
        "ema_crossover": {
            "entry_long": "Fast EMA crossed above slow EMA",
            "entry_short": "Fast EMA crossed below slow EMA",
            "exit_long": "Fast EMA crossed below slow EMA",
            "exit_short": "Fast EMA crossed above slow EMA",
        },
        "macd": {
            "entry_long": "MACD crossed above signal line",
            "entry_short": "MACD crossed below signal line",
            "exit_long": "MACD crossed below signal line",
            "exit_short": "MACD crossed above signal line",
        },
        "mean_reversion": {
            "entry_long": "Price fell below lower band",
            "exit_long": "Price reverted back above mean",
            "entry_short": "Price rose above upper band",
            "exit_short": "Price reverted back below mean",
        },
        "fibonacci_pullback": {
            "entry_long": "Pullback to 61.8% Fibonacci retracement",
            "exit_long": "Price reached prior high",
        },
        "momentum": {
            "entry_long": "Momentum turned positive",
            "exit_long": "Momentum turned negative",
        },
        "rsi_reversal": {
            "entry_long": "RSI crossed above lower threshold",
            "exit_long": "RSI crossed below upper threshold",
        },
        "rsi_momentum": {
            "entry_long": "RSI crossed above lower threshold with trend filter",
            "exit_long": "RSI crossed below upper threshold",
        },
    }
    return reasons.get(strategy_name, {}).get(side, "Signal triggered")



def _compute_advanced_trade_metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute advanced trade-level metrics."""
    if not trades:
        return {
            "profitFactor": None, "expectancy": None, "sqn": None,
            "avgWin": None, "avgLoss": None,
            "maxConsecutiveWins": 0, "maxConsecutiveLosses": 0,
            "bestTrade": None, "worstTrade": None,
        }

    pnls = [t.get('pnlPct', 0) or 0 for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = _safe_number(gross_profit / gross_loss) if gross_loss > 0 else None

    avg_win = _safe_number(np.mean(wins)) if wins else 0
    avg_loss = _safe_number(np.mean(losses)) if losses else 0
    n = len(pnls)
    win_rate = len(wins) / n if n > 0 else 0
    loss_rate = 1 - win_rate
    expectancy = _safe_number(win_rate * avg_win + loss_rate * avg_loss)

    std_pnl = float(np.std(pnls)) if len(pnls) > 1 else 0
    sqn = _safe_number((np.mean(pnls) / std_pnl) * np.sqrt(n)) if std_pnl > 0 else None

    # Max consecutive wins / losses
    max_con_w, max_con_l, cur_w, cur_l = 0, 0, 0, 0
    for p in pnls:
        if p > 0:
            cur_w += 1; cur_l = 0
            max_con_w = max(max_con_w, cur_w)
        elif p < 0:
            cur_l += 1; cur_w = 0
            max_con_l = max(max_con_l, cur_l)
        else:
            cur_w = 0; cur_l = 0

    return {
        "profitFactor": round(profit_factor, 2) if profit_factor is not None else None,
        "expectancy": round(expectancy, 2) if expectancy is not None else None,
        "sqn": round(sqn, 2) if sqn is not None else None,
        "avgWin": round(avg_win, 2) if avg_win else None,
        "avgLoss": round(avg_loss, 2) if avg_loss else None,
        "maxConsecutiveWins": max_con_w,
        "maxConsecutiveLosses": max_con_l,
        "bestTrade": round(max(pnls), 2) if pnls else None,
        "worstTrade": round(min(pnls), 2) if pnls else None,
    }



def _run_monte_carlo(
    returns: pd.Series,
    simulations: int = 1000,
    initial_capital: float = 100000,
    seed: int = DEFAULT_MONTE_CARLO_SEED,
) -> Dict[str, Any]:
    """Run a seeded Monte Carlo simulation with VaR, CVaR, and full simulation paths."""
    if returns.empty:
        return {"simulations": 0, "histogram": [], "percentiles": {}, "riskMetrics": {}, "simulationPaths": [], "percentilePaths": {}, "seed": seed}

    clean = returns.dropna().values
    if len(clean) == 0:
        return {"simulations": 0, "histogram": [], "percentiles": {}, "riskMetrics": {}, "simulationPaths": [], "percentilePaths": {}, "seed": seed}

    n_steps = len(clean)
    # Downsample to max 50 points for charting
    max_points = 50
    step_size = max(1, n_steps // max_points)
    sample_indices = list(range(0, n_steps, step_size))
    if sample_indices[-1] != n_steps - 1:
        sample_indices.append(n_steps - 1)

    rng = np.random.default_rng(seed)
    sim_returns = []
    sim_max_drawdowns = []
    all_equity_curves = []  # Store all simulation paths

    for _ in range(simulations):
        sample = rng.choice(clean, size=n_steps, replace=True)
        total = (1 + sample).prod() - 1
        sim_returns.append(total * 100)

        # Full equity curve for this simulation
        equity = np.cumprod(1 + sample)
        peak = np.maximum.accumulate(equity)
        # peak is 0 only on a path that lost everything on its first draw; treat that as no drawdown
        dd = np.divide(equity - peak, peak, out=np.zeros_like(equity), where=peak > 0).min() * 100
        sim_max_drawdowns.append(dd)

        # Downsample the equity curve
        sampled = equity[sample_indices]
        all_equity_curves.append(sampled)

    sim_arr = np.array(sim_returns)
    equity_matrix = np.array(all_equity_curves)  # shape: (simulations, n_sample_points)

    # Build simulation paths for charting (all paths) — in dollar values
    simulation_paths = []
    for i in range(simulations):
        path = [round(float(equity_matrix[i, j]) * initial_capital, 2) for j in range(len(sample_indices))]
        simulation_paths.append(path)

    # Compute percentile paths across all simulations at each time step — in dollar values
    percentile_paths = {}
    for pct_name, pct_val in [("p5", 5), ("p25", 25), ("p50", 50), ("p75", 75), ("p95", 95)]:
        pct_curve = np.percentile(equity_matrix, pct_val, axis=0)
        percentile_paths[pct_name] = [round(float(v) * initial_capital, 2) for v in pct_curve]

    bins = 30
    counts, edges = np.histogram(sim_arr, bins=bins)
    histogram = []
    for i in range(len(counts)):
        mid = (edges[i] + edges[i + 1]) / 2
        histogram.append({
            "return": _safe_number(mid),
            "count": int(counts[i])
        })

    percentiles = {
        "p5": _safe_number(np.percentile(sim_arr, 5)),
        "p10": _safe_number(np.percentile(sim_arr, 10)),
        "p25": _safe_number(np.percentile(sim_arr, 25)),
        "p50": _safe_number(np.percentile(sim_arr, 50)),
        "p75": _safe_number(np.percentile(sim_arr, 75)),
        "p90": _safe_number(np.percentile(sim_arr, 90)),
        "p95": _safe_number(np.percentile(sim_arr, 95)),
    }

    # VaR and CVaR at 95% confidence
    var_95 = float(np.percentile(sim_arr, 5))  # 5th percentile = 95% VaR
    cvar_95 = float(sim_arr[sim_arr <= var_95].mean()) if (sim_arr <= var_95).any() else var_95
    ruin_count = int((sim_arr < -50).sum())  # Ruin = losing > 50%
    median_dd = float(np.median(sim_max_drawdowns))

    return {
        "simulations": simulations,
        "histogram": histogram,
        "percentiles": percentiles,
        "riskMetrics": {
            "var95": _safe_number(round(var_95, 2)),
            "cvar95": _safe_number(round(cvar_95, 2)),
            "ruinProbability": round((ruin_count / simulations) * 100, 2),
            "medianMaxDrawdown": _safe_number(round(median_dd, 2)),
            "worstCase": _safe_number(round(float(sim_arr.min()), 2)),
            "bestCase": _safe_number(round(float(sim_arr.max()), 2)),
            "meanReturn": _safe_number(round(float(sim_arr.mean()), 2)),
        },
        "simulationPaths": simulation_paths,
        "percentilePaths": percentile_paths,
        "pathSteps": len(sample_indices),
        "seed": seed,
    }



def _describe_sizing(sizing: Dict[str, Any]) -> str:
    if sizing["mode"] == "fixed_quantity":
        return (
            f"fixed quantity of {sizing['value']:g} shares (a long buy that cash cannot cover is rejected, not "
            "resized, and not retried while the target persists; shorts have no margin check)"
        )
    return f"{sizing['value'] * 100:g}% of equity, fractional shares"


def _build_assumptions(
    commission_bps: float,
    slippage_bps: float,
    periods_per_year: float,
    seed: int,
    sizing: Optional[Dict[str, Any]] = None,
    fee_per_fill: float = 0.0,
    fill_timing: str = DEFAULT_FILL_TIMING,
) -> Dict[str, Any]:
    sizing = sizing or DEFAULT_SIZING
    return {
        "execution": f"signal on bar close, filled at next bar {'close' if fill_timing == 'next_close' else 'open'}",
        # human-readable (unchanged wording for the default); the structured control is `sizingSpec`
        "sizing": _describe_sizing(sizing),
        "sizingSpec": dict(sizing),
        "commission_bps": commission_bps,
        "slippage_bps": slippage_bps,
        "fee_per_fill": fee_per_fill,
        "fill_timing": fill_timing,
        "benchmark": "buy-and-hold from first close, normalized to initial capital",
        "periodsPerYear": periods_per_year,
        "monteCarloSeed": seed,
        "engineVersion": ENGINE_VERSION,
    }


def _compute_metrics(
    res_df: pd.DataFrame,
    trades: List[Dict[str, Any]],
    initial_capital: float,
    periods_per_year: float,
) -> Dict[str, Any]:
    equity = res_df['equity']
    final_equity = float(equity.iloc[-1])
    total_return = ((final_equity - initial_capital) / initial_capital) * 100
    min_drawdown = float(res_df['drawdown'].min())
    max_drawdown = min_drawdown * 100

    returns = res_df['strategy_returns']
    ann = np.sqrt(periods_per_year)
    std = returns.std()
    has_std = bool(np.isfinite(std) and std > 0)
    sharpe_ratio = (returns.mean() / std) * ann if has_std else 0
    downside = returns[returns < 0]
    down_std = downside.std()
    sortino_ratio = (returns.mean() / down_std) * ann if (np.isfinite(down_std) and down_std > 0) else 0
    annual_volatility = float(std * ann * 100) if has_std else 0

    n_returns = len(res_df) - 1
    if n_returns > 0 and final_equity > 0:
        annual_return = (final_equity / initial_capital) ** (periods_per_year / n_returns) - 1
    elif final_equity <= 0:
        annual_return = -1.0
    else:
        annual_return = 0.0
    calmar_ratio = annual_return / abs(min_drawdown) if min_drawdown != 0 else 0
    max_dd_duration = _compute_drawdown_duration(res_df['drawdown'])

    positions = res_df['position'].fillna(0)
    time_in_market = round((positions != 0).sum() / len(positions) * 100, 1) if len(positions) > 0 else 0

    total_trades = len(trades)
    win_rate = 0.0
    if total_trades > 0:
        wins = len([t for t in trades if (t.get('pnl') or 0) > 0])
        win_rate = (wins / total_trades) * 100

    adv = _compute_advanced_trade_metrics(trades)
    first_close = float(res_df['Close'].iloc[0])
    benchmark_return = (float(res_df['Close'].iloc[-1]) / first_close - 1) * 100 if first_close else 0

    return {
        "totalReturn": round(total_return, 2),
        "maxDrawdown": round(max_drawdown, 2),
        "sharpeRatio": round(float(sharpe_ratio), 2),
        "sortinoRatio": round(float(sortino_ratio), 2),
        "calmarRatio": round(float(calmar_ratio), 2),
        "maxDrawdownDuration": max_dd_duration,
        "winRate": round(win_rate, 1),
        "totalTrades": total_trades,
        "initialCapital": initial_capital,
        "finalEquity": round(final_equity, 6),
        "annualReturn": round(float(annual_return) * 100, 2),
        "annualVolatility": round(annual_volatility, 2),
        "timeInMarket": time_in_market,
        "benchmarkReturn": round(benchmark_return, 2),
        "profitFactor": adv["profitFactor"],
        "expectancy": adv["expectancy"],
        "sqn": adv["sqn"],
        "avgWin": adv["avgWin"],
        "avgLoss": adv["avgLoss"],
        "maxConsecutiveWins": adv["maxConsecutiveWins"],
        "maxConsecutiveLosses": adv["maxConsecutiveLosses"],
        "bestTrade": adv["bestTrade"],
        "worstTrade": adv["worstTrade"],
    }


def _build_chart_data(res_df: pd.DataFrame) -> List[Dict[str, Any]]:
    # Columns that are bookkeeping rather than indicators.
    exclude_cols = {
        'Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'equity', 'drawdown',
        'strategy_returns', 'peak', 'pct_change', 'position', 'target', 'signal', 'benchmark',
    }
    chart_data = []
    for _, row in res_df.iterrows():
        data_point = {
            "date": str(row['Date']),
            "equity": round(row['equity'], 2),
            "drawdown": round(row['drawdown'] * 100, 2),  # Percentage
            "close": row['Close'],
            "benchmark": round(row['benchmark'], 2),
            "position": int(row['position']),
        }
        # Add all other numeric columns (indicators) to data_point
        for col in res_df.columns:
            if col not in exclude_cols:
                val = row[col]
                if isinstance(val, (int, float, np.number)):
                    if not math.isnan(val) and not math.isinf(val):
                        data_point[col] = val
                    else:
                        data_point[col] = None
        chart_data.append(data_point)
    return chart_data


def _validate_run_settings(
    range_period: str,
    interval: str,
    initial_capital: Any,
    commission_bps: Any,
    slippage_bps: Any,
    seed: Any,
    start_date: Optional[str],
    end_date: Optional[str],
    fee_per_fill: Any = 0.0,
    fill_timing: Any = DEFAULT_FILL_TIMING,
    sizing: Any = None,
) -> Dict[str, Any]:
    """Validate the run-level settings before any data is fetched. Returns the normalised settings
    (spec-shaped, plus `periods_per_year`). Raises ValueError."""
    ppy = get_periods_per_year(interval)
    if not (start_date and end_date):
        validate_range(range_period)
    return {
        "initial_capital": validate_initial_capital(initial_capital),
        "commission_bps": validate_bps(commission_bps, "commission_bps"),
        "slippage_bps": validate_bps(slippage_bps, "slippage_bps"),
        "seed": validate_seed(seed),
        "fee_per_fill": validate_fee_per_fill(0.0 if fee_per_fill is None else fee_per_fill),
        "fill_timing": validate_fill_timing(DEFAULT_FILL_TIMING if fill_timing is None else fill_timing),
        "sizing": validate_sizing(sizing),
        "interval": interval,
        "periods_per_year": ppy,
    }


def _spec_for(symbol: str, strategy_name: str, params: Optional[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    spec = {k: v for k, v in settings.items() if k != "periods_per_year"}
    spec.update({"strategy": strategy_name, "params": params, "symbol": symbol})
    return spec


def run_backtest_service(
    symbol: str,
    strategy_name: str,
    range_period: str = "1y",
    interval: str = "1d",
    market: str = "us",
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
    seed: int = DEFAULT_MONTE_CARLO_SEED,
    sizing: Optional[Dict[str, Any]] = None,
    fee_per_fill: float = 0.0,
    fill_timing: str = DEFAULT_FILL_TIMING,
    **params
) -> Dict[str, Any]:
    """
    Runs a backtest for a given strategy and symbol.
    Returns D3-ready equity curve, drawdown, signals and the trade ledger.
    Raises MarketDataError if the market-data provider fails (an empty result is an error dict instead).
    """
    interval = str(interval or "1d").strip().lower()
    try:
        settings = _validate_run_settings(
            range_period, interval, initial_capital, commission_bps, slippage_bps, seed,
            start_date, end_date, fee_per_fill, fill_timing, sizing,
        )
    except ValueError as e:
        return {"error": str(e)}

    # 1. Fetch Data
    # fetch_candles returns list of dictionaries. Convert to DataFrame.
    candles = _fetch_candles_with_fallback(
        symbol=symbol,
        interval=interval,
        range_period=range_period,
        start_date=start_date,
        end_date=end_date,
        market=market,
    )
    if not candles:
        return {"error": f"No data found for symbol '{symbol}' in market '{market}'. Try a valid ticker or switch market."}

    df = prepare_candles_df(candles)

    # 2. Run the strategy through the single engine entry point
    try:
        result = dict(run_spec(df, _spec_for(symbol, strategy_name, params, settings)))
        result["symbol"] = symbol
        result["strategy"] = strategy_name
        return result
    except BacktestInputError as e:
        return {"error": str(e)}
    except Exception:
        logger.exception("Backtest failed for %s / %s", symbol, strategy_name)
        return {"error": INTERNAL_ERROR_MESSAGE, "internal": True}


def run_multi_strategy_backtest(
    symbol: str,
    strategy_names: List[str],
    range_period: str = "1y",
    interval: str = "1d",
    market: str = "us",
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    params_dict: Dict[str, Dict] = None,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
    seed: int = DEFAULT_MONTE_CARLO_SEED,
    sizing: Optional[Dict[str, Any]] = None,
    fee_per_fill: float = 0.0,
    fill_timing: str = DEFAULT_FILL_TIMING,
) -> Dict[str, Any]:
    """
    Runs backtest for multiple strategies and compares them.
    Returns combined equity curves and per-strategy metrics.
    Raises MarketDataError if the market-data provider fails.
    """
    if params_dict is None:
        params_dict = {}

    interval = str(interval or "1d").strip().lower()
    try:
        settings = _validate_run_settings(
            range_period, interval, initial_capital, commission_bps, slippage_bps, seed,
            start_date, end_date, fee_per_fill, fill_timing, sizing,
        )
    except ValueError as e:
        return {"error": str(e)}

    # Fetch data once
    candles = _fetch_candles_with_fallback(
        symbol=symbol,
        interval=interval,
        range_period=range_period,
        start_date=start_date,
        end_date=end_date,
        market=market,
    )
    if not candles:
        return {"error": f"No data found for symbol '{symbol}' in market '{market}'. Try a valid ticker or switch market."}

    df = prepare_candles_df(candles)

    strategy_results = {}
    combined_chart_data = []
    benchmark_curve: List[Dict[str, Any]] = []

    # Generate color palette for strategies
    colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899']

    for idx, strategy_name in enumerate(strategy_names):
        params = params_dict.get(strategy_name, {})

        try:
            evaluated = run_spec(df, _spec_for(symbol, strategy_name, params, settings))
            res_df = evaluated.frame
            if not benchmark_curve:
                benchmark_curve = [
                    {"date": str(row['Date']), "value": round(row['benchmark'], 2)}
                    for _, row in res_df.iterrows()
                ]

            strategy_results[strategy_name] = {
                "name": strategy_name,
                "color": colors[idx % len(colors)],
                "metrics": evaluated["metrics"],
                "trades": evaluated["trades"],
                "monteCarlo": evaluated["monteCarlo"],
                "equityCurve": [
                    {"date": str(row['Date']), "value": round(row['equity'], 2)}
                    for _, row in res_df.iterrows()
                ],
                "ledger": evaluated["ledger"],
            }

        except BacktestInputError as e:
            strategy_results[strategy_name] = {
                "name": strategy_name,
                "error": str(e),
                "metrics": None
            }
        except Exception:
            logger.exception("Backtest failed for %s / %s", symbol, strategy_name)
            strategy_results[strategy_name] = {
                "name": strategy_name,
                "error": INTERNAL_ERROR_MESSAGE,
                "metrics": None
            }

    # Build combined chart data (merge all equity curves)
    # Use first strategy's dates as reference
    first_valid = None
    for name, result in strategy_results.items():
        if "equityCurve" in result:
            first_valid = result
            break

    if first_valid:
        for i, point in enumerate(first_valid["equityCurve"]):
            data_point = {"date": point["date"]}
            for name, result in strategy_results.items():
                if "equityCurve" in result and i < len(result["equityCurve"]):
                    data_point[name] = result["equityCurve"][i]["value"]
            combined_chart_data.append(data_point)

    # Rank strategies by total return
    ranked = sorted(
        [(name, res["metrics"]["totalReturn"])
         for name, res in strategy_results.items()
         if res.get("metrics")],
        key=lambda x: x[1],
        reverse=True
    )

    return {
        "symbol": symbol,
        "mode": "multi_strategy",
        "strategies": strategy_results,
        "combinedChartData": combined_chart_data,
        "benchmarkCurve": benchmark_curve,
        "ranking": [{"strategy": name, "return": ret} for name, ret in ranked],
        "initialCapital": settings["initial_capital"],
        "assumptions": _build_assumptions(
            settings["commission_bps"], settings["slippage_bps"], settings["periods_per_year"],
            settings["seed"], sizing=settings["sizing"], fee_per_fill=settings["fee_per_fill"],
            fill_timing=settings["fill_timing"],
        ),
    }


def generate_backtest_report(
    symbol: str,
    strategies: List[str],
    results: Dict[str, Any],
    report_format: str = "html"
) -> Dict[str, Any]:
    """
    Generates a downloadable backtest report.
    Returns HTML or CSV content.
    """
    from datetime import datetime
    from pathlib import Path
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    reports_dir = Path(__file__).parent.parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    
    if report_format == "csv":
        return generate_csv_report(symbol, strategies, results, reports_dir, timestamp)
    if report_format == "pdf":
        html_result = generate_html_report(symbol, strategies, results, reports_dir, timestamp)
        if html_result.get("error"):
            return html_result

        html_filename = html_result.get("filename")
        if not html_filename:
            return {"error": "HTML report generation failed."}

        html_path = reports_dir / html_filename
        pdf_filename = html_filename.replace(".html", ".pdf")
        pdf_path = reports_dir / pdf_filename

        from backend.utils.pdf_generator import convert_html_to_pdf

        conversion = convert_html_to_pdf(str(html_path), str(pdf_path))
        if not conversion.get("success"):
            logger.error("PDF conversion failed: %s", conversion.get("error"))
            return {"error": "PDF conversion failed."}

        return {
            "success": True,
            "filename": pdf_filename,
            "downloadUrl": f"/api/backtest/report/download/{pdf_filename}"
        }

    return generate_html_report(symbol, strategies, results, reports_dir, timestamp)


def generate_csv_report(
    symbol: str,
    strategies: List[str],
    results: Dict[str, Any],
    reports_dir,
    timestamp: str
) -> Dict[str, Any]:
    """Generate CSV format backtest report."""
    import csv
    import io
    
    filename = f"backtest_{symbol}_{timestamp}.csv"
    filepath = reports_dir / filename
    
    try:
        with open(filepath, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            
            # Header
            writer.writerow(['Backtest Report'])
            writer.writerow(['Symbol', symbol])
            writer.writerow(['Generated', timestamp])
            writer.writerow(['Strategies', ', '.join(strategies)])
            writer.writerow([])
            
            # Check if multi-strategy or single
            if results.get('mode') == 'multi_strategy':
                # Multi-strategy results
                writer.writerow(['Strategy Comparison'])
                writer.writerow(['Strategy', 'Total Return %', 'Max Drawdown %', 'Sharpe Ratio', 'Trades', 'Final Equity'])
                
                for strat_id, strat_data in results.get('strategies', {}).items():
                    if strat_data.get('metrics'):
                        m = strat_data['metrics']
                        writer.writerow([
                            strat_id,
                            m.get('totalReturn', 0),
                            m.get('maxDrawdown', 0),
                            m.get('sharpeRatio', 0),
                            m.get('totalTrades', 0),
                            m.get('finalEquity', 0)
                        ])
                
                # Ranking
                writer.writerow([])
                writer.writerow(['Ranking'])
                for i, rank in enumerate(results.get('ranking', []), 1):
                    writer.writerow([f"#{i}", rank['strategy'], f"{rank['return']}%"])
            else:
                # Single strategy
                metrics = results.get('metrics', {})
                writer.writerow(['Metrics'])
                writer.writerow(['Total Return', f"{metrics.get('totalReturn', 0)}%"])
                writer.writerow(['Sharpe Ratio', metrics.get('sharpeRatio', 0)])
                writer.writerow(['Max Drawdown', f"{metrics.get('maxDrawdown', 0)}%"])
                writer.writerow(['Win Rate', f"{metrics.get('winRate', 0)}%"])
                writer.writerow(['Total Trades', metrics.get('totalTrades', 0)])
                writer.writerow(['Final Equity', metrics.get('finalEquity', 0)])
        
        return {
            "success": True,
            "filename": filename,
            "downloadUrl": f"/api/backtest/report/download/{filename}"
        }
    except Exception:
        logger.exception("Report generation failed")
        return {"error": "Report generation failed."}


def generate_html_report(
    symbol: str,
    strategies: List[str],
    results: Dict[str, Any],
    reports_dir,
    timestamp: str
) -> Dict[str, Any]:
    """Generate HTML format backtest report."""
    from datetime import datetime
    
    filename = f"backtest_{symbol}_{timestamp}.html"
    filepath = reports_dir / filename
    
    try:
        is_multi = results.get('mode') == 'multi_strategy'
        
        # Build metrics table
        if is_multi:
            metrics_html = "<h2>Strategy Comparison</h2><table><tr><th>Strategy</th><th>Return</th><th>Max DD</th><th>Sharpe</th><th>Trades</th><th>Final Value</th></tr>"
            for strat_id, strat_data in results.get('strategies', {}).items():
                if strat_data.get('metrics'):
                    m = strat_data['metrics']
                    ret_class = 'positive' if m.get('totalReturn', 0) >= 0 else 'negative'
                    metrics_html += f"""
                    <tr>
                        <td><strong>{strat_id}</strong></td>
                        <td class="{ret_class}">{m.get('totalReturn', 0):+.2f}%</td>
                        <td class="negative">{m.get('maxDrawdown', 0):.2f}%</td>
                        <td>{m.get('sharpeRatio', 0):.2f}</td>
                        <td>{m.get('totalTrades', 0)}</td>
                        <td>${m.get('finalEquity', 0):,.2f}</td>
                    </tr>
                    """
            metrics_html += "</table>"
            
            # Ranking
            ranking_html = "<h2>🏆 Strategy Ranking</h2><ol>"
            for rank in results.get('ranking', []):
                ret_class = 'positive' if rank['return'] >= 0 else 'negative'
                ranking_html += f"<li><strong>{rank['strategy']}</strong>: <span class='{ret_class}'>{rank['return']:+.2f}%</span></li>"
            ranking_html += "</ol>"
        else:
            metrics = results.get('metrics', {})
            ret_class = 'positive' if float(metrics.get('totalReturn', 0)) >= 0 else 'negative'
            metrics_html = f"""
            <h2>Performance Metrics</h2>
            <div class="metrics-grid">
                <div class="metric"><span class="label">Total Return</span><span class="value {ret_class}">{metrics.get('totalReturn', 0)}%</span></div>
                <div class="metric"><span class="label">Sharpe Ratio</span><span class="value">{metrics.get('sharpeRatio', 0)}</span></div>
                <div class="metric"><span class="label">Max Drawdown</span><span class="value negative">{metrics.get('maxDrawdown', 0)}%</span></div>
                <div class="metric"><span class="label">Win Rate</span><span class="value">{metrics.get('winRate', 0)}%</span></div>
                <div class="metric"><span class="label">Total Trades</span><span class="value">{metrics.get('totalTrades', 0)}</span></div>
                <div class="metric"><span class="label">Final Value</span><span class="value">${metrics.get('finalEquity', metrics.get('finalValue', 0)):,.2f}</span></div>
            </div>
            """
            ranking_html = ""
        
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Backtest Report - {symbol}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0b; 
            color: #fff; 
            padding: 40px; 
            line-height: 1.6;
        }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        h1 {{ font-size: 32px; margin-bottom: 8px; }}
        .subtitle {{ color: #71717a; margin-bottom: 32px; }}
        h2 {{ font-size: 20px; margin: 32px 0 16px; color: #a1a1aa; }}
        .meta {{ display: flex; gap: 24px; margin-bottom: 32px; padding: 20px; background: #18181b; border-radius: 12px; }}
        .meta-item {{ display: flex; flex-direction: column; gap: 4px; }}
        .meta-label {{ font-size: 12px; color: #71717a; text-transform: uppercase; }}
        .meta-value {{ font-size: 16px; font-weight: 600; }}
        table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
        th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #27272a; }}
        th {{ background: #18181b; font-weight: 600; color: #a1a1aa; }}
        tr:hover {{ background: #18181b; }}
        .positive {{ color: #22c55e; }}
        .negative {{ color: #ef4444; }}
        .metrics-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
        .metric {{ padding: 20px; background: #18181b; border-radius: 12px; border: 1px solid #27272a; }}
        .metric .label {{ display: block; font-size: 12px; color: #71717a; margin-bottom: 8px; text-transform: uppercase; }}
        .metric .value {{ font-size: 24px; font-weight: 700; }}
        ol {{ padding-left: 24px; }}
        ol li {{ padding: 8px 0; font-size: 16px; }}
        .footer {{ margin-top: 48px; padding-top: 24px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Backtest Report</h1>
        <p class="subtitle">Automated strategy performance analysis</p>
        
        <div class="meta">
            <div class="meta-item">
                <span class="meta-label">Symbol</span>
                <span class="meta-value">{symbol}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Strategies</span>
                <span class="meta-value">{', '.join(strategies)}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Generated</span>
                <span class="meta-value">{datetime.now().strftime('%B %d, %Y %H:%M')}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Initial Capital</span>
                <span class="meta-value">${results.get('initialCapital', 100000):,.2f}</span>
            </div>
        </div>
        
        {ranking_html}
        {metrics_html}
        
        <div class="footer">
            <p>Generated by Arbiter Trading Platform • {datetime.now().year}</p>
        </div>
    </div>
</body>
</html>
        """
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return {
            "success": True,
            "filename": filename,
            "downloadUrl": f"/api/backtest/report/download/{filename}"
        }
    except Exception:
        logger.exception("Report generation failed")
        return {"error": "Report generation failed."}
