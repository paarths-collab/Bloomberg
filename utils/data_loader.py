import pandas as pd
import yfinance as yf
import ta
import logging
from typing import Dict, Any
from functools import lru_cache
from pathlib import Path

# --- Module Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Helper function for Indian Stocks ---
@lru_cache(maxsize=1)
def _get_indian_symbols_set():
    """Loads the set of Indian stock symbols from the EQUITY_L.csv file."""
    try:
        equity_file = Path("quant-company-insights-agent/data/EQUITY_L (1).csv")
        if equity_file.exists():
            df = pd.read_csv(equity_file)
            logger.info(f"Successfully loaded {len(df)} Indian stock symbols.")
            return set(df['SYMBOL'].str.upper())
        return set()
    except Exception as e:
        logger.error(f"Could not load Indian symbols file: {e}")
        return set()

def _format_ticker_for_yf(ticker: str) -> str:
    """Appends .NS to Indian stock tickers for Yahoo Finance compatibility."""
    ticker_upper = ticker.upper().replace(".NS", "")
    indian_symbols = _get_indian_symbols_set()
    if ticker_upper in indian_symbols:
        return f"{ticker_upper}.NS"
    return ticker_upper

# ===================================================================
#                       CORE DATA FETCHING
# ===================================================================

@lru_cache(maxsize=128)
def get_company_snapshot(ticker: str) -> Dict[str, Any]:
    """Returns a comprehensive snapshot of a company's key fundamentals."""
    yf_ticker = _format_ticker_for_yf(ticker)
    logger.info(f"Fetching snapshot for {yf_ticker}...")
    try:
        stock = yf.Ticker(yf_ticker)
        info = stock.info
        
        currency = info.get("currency", "USD")
        currency_symbol = "₹" if currency == "INR" else "$"
        
        return {
            "currencySymbol": currency_symbol,
            **info
        }
    except Exception as e:
        logger.error(f"Failed to retrieve snapshot for {yf_ticker}: {e}")
        return {"symbol": ticker, "error": str(e)}

def get_history(ticker: str, start: str, end: str, interval: str = "1d") -> pd.DataFrame:
    """Fetches historical market data for a given ticker."""
    yf_ticker = _format_ticker_for_yf(ticker)
    logger.info(f"Fetching history for {yf_ticker} from {start} to {end}.")
    try:
        df = yf.download(yf_ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True)
        if df.empty:
            logger.warning(f"No data found for {yf_ticker} from {start} to {end}.")
        return df
    except Exception as e:
        logger.error(f"An error occurred while fetching history for {yf_ticker}: {e}")
        return pd.DataFrame()

# ===================================================================
#                       DATA ENRICHMENT
# ===================================================================

def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Appends a curated set of key technical indicators to an OHLCV DataFrame.
    This is a more robust approach than `add_all_ta_features`.
    """
    if df.empty:
        return df
    
    logger.info(f"Adding technical indicators to DataFrame with {len(df)} rows...")
    try:
        # Volume Indicators
        df['volume_obv'] = ta.volume.on_balance_volume(df['Close'], df['Volume'], fillna=True)
        
        # Volatility Indicators
        df['volatility_bbh'] = ta.volatility.bollinger_hband(df['Close'], window=20, window_dev=2, fillna=True)
        df['volatility_bbl'] = ta.volatility.bollinger_lband(df['Close'], window=20, window_dev=2, fillna=True)
        
        # Trend Indicators
        df['trend_sma_fast'] = ta.trend.sma_indicator(df['Close'], window=50, fillna=True)
        df['trend_sma_slow'] = ta.trend.sma_indicator(df['Close'], window=200, fillna=True)
        df['trend_macd'] = ta.trend.macd(df['Close'], window_slow=26, window_fast=12, fillna=True)
        df['trend_macd_signal'] = ta.trend.macd_signal(df['Close'], window_slow=26, window_fast=12, window_sign=9, fillna=True)
        
        # Momentum Indicators
        df['momentum_rsi'] = ta.momentum.rsi(df['Close'], window=14, fillna=True)
        
        logger.info(f"Successfully added indicators. DataFrame now has {len(df.columns)} columns.")
        return df
    except Exception as e:
        logger.error(f"Error adding technical indicators: {e}")
        return df # Return original dataframe on failure

 



# import pandas as pd
# import yfinance as yf
# import ta
# import logging
# from typing import Dict, Any, Optional, List
# from functools import lru_cache

# # --- Module Configuration ---
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)

# # ===================================================================
# #                      CORE DATA FETCHING
# # ===================================================================

# @lru_cache(maxsize=128) # Cache up to 128 recent snapshot calls
# def get_company_snapshot(ticker: str) -> Dict[str, Any]:
#     """
#     Returns a comprehensive snapshot of a company's key fundamentals.
#     Uses caching to improve performance for repeated calls.
#     """
#     logger.info(f"Fetching snapshot for {ticker}...")
#     try:
#         stock = yf.Ticker(ticker)
#         info = stock.info
        
#         # A broker would want easy access to all key fields, even if some are None
#         return {
#             "symbol": info.get("symbol", ticker),
#             "longName": info.get("longName"),
#             "sector": info.get("sector"),
#             "industry": info.get("industry"),
#             "marketCap": info.get("marketCap"),
#             "trailingPE": info.get("trailingPE"),
#             "forwardPE": info.get("forwardPE"),
#             "dividendYield": info.get("dividendYield"),
#             "payoutRatio": info.get("payoutRatio"),
#             "returnOnEquity": info.get("returnOnEquity"),
#             "debtToEquity": info.get("debtToEquity"),
#             "priceToBook": info.get("priceToBook"),
#             "beta": info.get("beta"),
#             "averageVolume": info.get("averageVolume"),
#             "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh"),
#             "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow"),
#             "exchange": info.get("exchange"),
#             "currency": info.get("currency")
#         }
#     except Exception as e:
#         logger.error(f"Failed to retrieve snapshot for {ticker}: {e}")
#         return {"symbol": ticker, "error": str(e)}

# # In utils/data_loader.py

# # Inside Boomerang/utils/data_loader.py

# def get_history(ticker: str, start: str, end: str, interval: str = "1d") -> pd.DataFrame:
#     """Fetches historical market data for a given ticker."""
#     try:
#         # Add auto_adjust=True to the line below
#         df = yf.download(ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True)
#         if df.empty:
#             print(f"Warning: No data found for {ticker} from {start} to {end}.")
#             return pd.DataFrame()
#         return df
#     except Exception as e:
#         print(f"An error occurred while fetching history for {ticker}: {e}")
#         return pd.DataFrame()

# # ===================================================================
# #                      DATA ENRICHMENT
# # ===================================================================

# def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
#     """
#     Appends a comprehensive set of technical indicators to an OHLCV DataFrame.
#     """
#     if df.empty:
#         return df
    
#     logger.info(f"Adding technical indicators to DataFrame with {len(df)} rows...")
#     try:
#         # Uses the 'ta' library to add multiple indicators in one go
#         df = ta.add_all_ta_features(
#             df, open="Open", high="High", low="Low", close="Close", volume="Volume", fillna=True
#         )
#         # Standardize column names after 'ta' library adds them
#         df.columns = [col.replace(' ', '_').replace('-', '_') for col in df.columns]
#         logger.info(f"Successfully added indicators. DataFrame now has {len(df.columns)} columns.")
#         return df
#     except Exception as e:
#         logger.error(f"Error adding technical indicators: {e}")
#         return df # Return original dataframe on failure