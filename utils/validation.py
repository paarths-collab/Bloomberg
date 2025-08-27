# check if news is true (fact-checking layer)
'''
Here are 3 strategies you can add:

1.Source Reliability Scoring

Predefine “trusted sources” (Reuters, Bloomberg, Moneycontrol, WSJ, etc.)

Score them higher vs random blogs.

2.Cross-Verification

If the same news appears in multiple trusted outlets → higher reliability.

Example: If Reuters + Bloomberg both publish, assign confidence = 0.9.

3.AI Fact-Check

Use an NLP model (Hugging Face or LangChain’s fact-checking chains) to detect misinformation.

Example: Compare claim against knowledge base (Wikipedia API, DBpedia, or OpenBB news dataset).'''
# utils/validation.py
from __future__ import annotations
import pandas as pd

def sma_crossover_signal(df: pd.DataFrame) -> str:
    """
    Simple signal:
      - BUY if SMA50 crosses above SMA200 (golden cross)
      - SELL if SMA50 crosses below SMA200 (death cross)
      - HOLD otherwise
    """
    if df.empty or "SMA50" not in df.columns or "SMA200" not in df.columns:
        return "HOLD"
    s50 = df["SMA50"].dropna()
    s200 = df["SMA200"].dropna()
    if len(s50) < 2 or len(s200) < 2:
        return "HOLD"
    prev_cross = (s50.iloc[-2] - s200.iloc[-2])
    curr_cross = (s50.iloc[-1] - s200.iloc[-1])
    if prev_cross <= 0 and curr_cross > 0:
        return "BUY"
    if prev_cross >= 0 and curr_cross < 0:
        return "SELL"
    return "HOLD"

def rsi_filter(df: pd.DataFrame, lower=30, upper=70) -> str:
    """Return 'OK' if RSI is not overbought/oversold; 'OVERSOLD' or 'OVERBOUGHT' otherwise."""
    if "RSI14" not in df.columns or df["RSI14"].dropna().empty:
        return "UNKNOWN"
    r = df["RSI14"].dropna().iloc[-1]
    if r < lower:
        return "OVERSOLD"
    if r > upper:
        return "OVERBOUGHT"
    return "OK"

def atr_stop_levels(df: pd.DataFrame, atr_mult: float = 2.0) -> tuple[float | None, float | None]:
    """Return (stop_loss, take_profit) using last Close and ATR*mult. TP set symmetric (2R by default)."""
    if df.empty or "Close" not in df.columns:
        return None, None
    close = float(df["Close"].iloc[-1])
    # pandas_ta names ATR as 'ATR_14' by default
   # --- NEW, MORE ROBUST LINE ---
    atr_col = next((c for c in df.columns if "ATR" in c), None)
    if atr_col is None or df[atr_col].dropna().empty:
        return None, None
    atr = float(df[atr_col].dropna().iloc[-1])
    stop = close - atr_mult * atr
    take = close + 2 * atr_mult * atr  # 2R target
    return round(stop, 2), round(take, 2)
