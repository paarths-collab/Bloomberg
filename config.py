"""
Centralized configuration for the QuantInsights platform.
This file contains all configurable settings, API keys, and constants.
"""

import os
from pathlib import Path

# Project root directory
PROJECT_ROOT = Path(__file__).parent

# --- API KEYS AND CREDENTIALS ---
# Add your API keys here - these should be set as environment variables for security
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
YFINANCE_TIMEOUT = int(os.getenv("YFINANCE_TIMEOUT", "30"))

# --- FILE PATHS ---
DATA_DIR = PROJECT_ROOT / "data"
NIFTY500_FILE = DATA_DIR / "nifty500.csv"
PORTFOLIO_REPORT_FILE = PROJECT_ROOT / "portfolio_report.html"

# --- STRATEGY DEFAULTS ---
DEFAULT_START_DATE = "2020-01-01"
DEFAULT_END_DATE = "today"
DEFAULT_INITIAL_CAPITAL = 100000

# --- BACKTESTING SETTINGS ---
COMMISSION_RATE = 0.002
DEFAULT_LOOKBACK_PERIOD = 20

# --- UI/UX SETTINGS ---
UI_THEME = "light"  # Options: "light", "dark"
UI_DECIMAL_PLACES = 2

# --- CURRENCY SETTINGS ---
CURRENCY_SYMBOLS = {
    "USD": "$",
    "INR": "₹",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥"
}

# --- METRICS EXPLANATIONS ---
METRIC_EXPLANATIONS = {
    "Total Return %": "Total percentage return of the strategy over the backtest period",
    "Sharpe Ratio": "Measures risk-adjusted return; higher values indicate better performance",
    "Max Drawdown %": "The largest peak-to-trough decline in portfolio value during the period",
    "CAGR %": "Compound Annual Growth Rate; represents the mean annual growth rate",
    "Annual Volatility %": "Standard deviation of annual returns; measures risk/uncertainty",
    "Number of Trades": "Total number of trades executed during the backtest period",
    "Sortino Ratio": "Measures risk-adjusted return focusing only on downside deviation",
    "Calmar Ratio": "Ratio of annual return to maximum drawdown; higher is better",
    "Beta (vs. Benchmark)": "Measures the strategy's sensitivity to market movements"
}

# --- STRATEGY DESCRIPTIONS ---
STRATEGY_DESCRIPTIONS = {
    "Breakout Strategy": "This strategy identifies breakouts above resistance levels or below support levels to enter trades.",
    "Channel Trading": "Uses Donchian Channels to identify price breakouts above or below established ranges.",
    "EMA Crossover": "Generates buy signals when a short-term EMA crosses above a long-term EMA, and sell signals on the reverse.",
    "MACD Strategy": "Uses Moving Average Convergence Divergence to identify trend changes and momentum shifts.",
    "Mean Reversion": "Assumes that prices tend to revert to their historical mean after deviating significantly.",
    "Momentum Strategy": "Buys securities that are rising and sells them when they show signs of weakening.",
    "Pairs Trading": "Exploits the relative price movements of two correlated securities to generate trading signals.",
    "Fibonacci Pullback": "Uses Fibonacci retracement levels to identify potential support and resistance levels.",
    "RSI Reversal": "Uses the Relative Strength Index to identify oversold/overbought conditions for reversal trades.",
    "RSI Momentum": "Uses the Relative Strength Index to confirm trend direction and momentum.",
    "SMA Crossover": "Generates buy signals when a short-term Simple Moving Average crosses above a long-term SMA, and sell signals on the reverse.",
    "Support/Resistance": "Identifies key support and resistance levels to enter trades when prices approach these levels."
}