# File: utils/data_loader.py
# This is the final, master data utility for your entire application.

import pandas as pd
import yfinance as yf
import ta
import logging
from functools import lru_cache
from pathlib import Path
import streamlit as st
from typing import Dict, Any

# --- Module Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===================================================================
#                      TICKER FORMATTING
# ===================================================================

@lru_cache(maxsize=1)
def _get_indian_symbols_set():
    """Internal function to load Indian stock symbols for formatting."""
    try:
        project_root = Path(__file__).parent.parent
        equity_file = project_root / "data" / "nifty500.csv"
        if equity_file.exists():
            df = pd.read_csv(equity_file)
            return set(df['Symbol'].str.upper())
    except Exception as e:
        logger.error(f"Could not load Indian symbols file: {e}")
    return set()

def format_ticker(ticker: str, market: str) -> str:
    """
    Public function to format a ticker symbol according to its market.
    This is the function your agents are looking for.
    """
    try:
        ticker_upper = ticker.upper().replace(".NS", "")
        if market.upper() in ['NSE', 'INDIA']:
            return f"{ticker_upper}.NS"
        # For US market or others, return as is.
        return ticker_upper
    except Exception as e:
        logger.error(f"Could not format ticker: {e}")
        return ticker

# ===================================================================
#                       CORE DATA FUNCTIONS
# ===================================================================

# File: utils/data_loader.py

@st.cache_data
def get_data(ticker: str, start: str, end: str) -> pd.DataFrame:
    """
    Fetches and formats data specifically for the backtesting.py library.
    This is the main function for all single-ticker strategy backtests.
    """
    logger.info(f"Fetching backtesting data for {ticker} from {start} to {end}.")
    try:
        yf_ticker = format_ticker(ticker, "US" if ".NS" not in ticker else "NSE")
        df = yf.download(yf_ticker, start=start, end=end, progress=False, auto_adjust=False)

        if df.empty:
            return pd.DataFrame()

        # FIXED: Properly handle MultiIndex columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # FIXED: Handle both string and non-string column names
        df.columns = [str(col).title() for col in df.columns]

        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(col in df.columns for col in required_cols):
            st.error(f"Data for {ticker} is missing required OHLCV columns.")
            return pd.DataFrame()

        return df[required_cols]
    except Exception as e:
        st.error(f"An error occurred while fetching data for {ticker}: {e}")
        return pd.DataFrame()

def get_history(ticker: str, start: str, end: str, interval: str = "1d") -> pd.DataFrame:
    """Fetches general historical market data for agents."""
    yf_ticker = format_ticker(ticker, "US" if ".NS" not in ticker else "NSE")
    try:
        df = yf.download(yf_ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True)
        return df
    except Exception:
        return pd.DataFrame()


def get_company_snapshot(ticker: str) -> Dict[str, Any]:
    """Returns a snapshot of a company's key fundamentals for agents."""
    yf_ticker = format_ticker(ticker, "US" if ".NS" not in ticker else "NSE")
    try:
        stock = yf.Ticker(yf_ticker)
        info = stock.info
        currency = info.get("currency", "USD")
        currency_symbol = "₹" if currency == "INR" else "$"
        return {"currencySymbol": currency_symbol, **info}
    except Exception as e:
        return {"symbol": ticker, "error": str(e)}

# ===================================================================
#                       DATA ENRICHMENT
# ===================================================================

def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Appends a curated set of key technical indicators to an OHLCV DataFrame."""
    if df.empty or 'Close' not in df.columns or 'Volume' not in df.columns:
        return df
    
    try:
        df['volume_obv'] = ta.volume.on_balance_volume(close=df['Close'], volume=df['Volume'], fillna=True)
        df['volatility_bbh'] = ta.volatility.bollinger_hband(close=df['Close'], window=20, window_dev=2, fillna=True)
        df['volatility_bbl'] = ta.volatility.bollinger_lband(close=df['Close'], window=20, window_dev=2, fillna=True)
        df['trend_sma_fast'] = ta.trend.sma_indicator(close=df['Close'], window=50, fillna=True)
        df['trend_sma_slow'] = ta.trend.sma_indicator(close=df['Close'], window=200, fillna=True)
        df['trend_macd'] = ta.trend.macd(close=df['Close'], window_slow=26, window_fast=12, fillna=True)
        df['trend_macd_signal'] = ta.trend.macd_signal(close=df['Close'], window_slow=26, window_fast=12, window_sign=9, fillna=True)
        df['momentum_rsi'] = ta.momentum.rsi(close=df['Close'], window=14, fillna=True)
        return df
    except Exception as e:
        logger.error(f"Error adding technical indicators: {e}")
        return df
        
# import pandas as pd
# import yfinance as yf
# import ta
# import logging
# from typing import Dict, Any
# from functools import lru_cache
# from pathlib import Path
# import streamlit as st # Streamlit is used for caching

# # --- Module Configuration ---
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)

# # ===================================================================
# #                      TICKER FORMATTING
# # ===================================================================

# @lru_cache(maxsize=1)
# def _get_indian_symbols_set():
#     """Internal function to load the set of Indian stock symbols for formatting."""
#     try:
#         # Assumes the script is run from a location where this relative path is valid
#         project_root = Path(__file__).parent.parent
#         equity_file = project_root / "data" / "nifty500.csv"
        
#         if equity_file.exists():
#             df = pd.read_csv(equity_file)
#             logger.info(f"Successfully loaded {len(df)} Indian stock symbols")
#             return set(df['Symbol'].str.upper())
#         else:
#             logger.warning(f"Indian symbols file not found at '{equity_file}'")
#             return set()
#     except Exception as e:
#         logger.error(f"Could not load Indian symbols file: {e}")
#         return set()

# def _format_ticker_for_yf(ticker: str) -> str:
#     """Formats a ticker for Yahoo Finance, appending .NS for known Indian stocks."""
#     ticker_upper = ticker.upper().replace(".NS", "")
#     if ticker_upper in _get_indian_symbols_set():
#         return f"{ticker_upper}.NS"
#     return ticker_upper

# # ===================================================================
# #                       CORE DATA FETCHING
# # ===================================================================

# # --- CRITICAL FIX: RENAMED FUNCTION FOR COMPATIBILITY ---
# # File: utils/data_loader.py
# # This is your new, central utility for all data loading.

# import streamlit as st
# import yfinance as yf
# import pandas as pd

# @st.cache_data
# def get_data(ticker: str, start: str, end: str) -> pd.DataFrame:
#     """
#     Final, robust data fetching function for single-ticker backtests.
#     Correctly flattens any MultiIndex from yfinance and ensures OHLCV columns.
#     """
#     # Download data. auto_adjust=True handles splits and dividends.
#     df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
#     if df.empty:
#         return pd.DataFrame()

#     # If yfinance returns a MultiIndex, flatten it to simple column names.
#     if isinstance(df.columns, pd.MultiIndex):
#         df.columns = df.columns.droplevel(0)

#     # Standardize all column names to Title Case for backtesting.py compatibility.
#     df.columns = [col.title() for col in df.columns]

#     # Ensure the essential columns exist, otherwise backtesting will fail.
#     required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
#     if not all(col in df.columns for col in required_cols):
#         st.error(f"Data for {ticker} is missing required OHLCV columns.")
#         return pd.DataFrame()

#     return df[required_cols]

# # (You can keep the other functions like get_history, get_company_snapshot, etc.,
# # if other parts of your larger application need them. They will not interfere.)

# def get_history(ticker: str, start: str, end: str, interval: str = "1d") -> pd.DataFrame:
#     """Fetches historical market data for a given ticker."""
#     yf_ticker = _format_ticker_for_yf(ticker)
#     logger.info(f"Fetching history for {yf_ticker} from {start} to {end}.")
#     try:
#         df = yf.download(yf_ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True)
#         if df.empty:
#             logger.warning(f"No data found for {yf_ticker} from {start} to {end}.")
#         return df
#     except Exception as e:
#         logger.error(f"An error occurred while fetching history for {yf_ticker}: {e}")
#         return pd.DataFrame()

# import pandas as pd
# import yfinance as yf
# import ta
# import logging
# from typing import Dict, Any
# from functools import lru_cache
# from pathlib import Path

# # --- Module Configuration ---
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)

# # ===================================================================
# #                      TICKER FORMATTING
# # ===================================================================

# def format_ticker(ticker: str, market: str) -> str:
#     """Format ticker symbol according to market."""
#     try:
#         ticker = ticker.upper()
#         if market.upper() == 'NSE':
#             return f"{ticker}.NS"
#         return ticker
#     except Exception as e:
#         logger.error(f"Could not format ticker: {e}")
#         return ticker

# @lru_cache(maxsize=1)
# def _get_indian_symbols_set():
#     """Loads the set of Indian stock symbols."""
#     try:
#         project_root = Path(__file__).parent.parent
#         equity_file = project_root / "data" / "nifty500.csv"
        
#         if equity_file.exists():
#             df = pd.read_csv(equity_file)
#             logger.info(f"Successfully loaded {len(df)} Indian stock symbols")
#             return set(df['Symbol'].str.upper())
#         else:
#             logger.warning(f"Indian symbols file not found at '{equity_file}'")
#             return set()
#     except Exception as e:
#         logger.error(f"Could not load Indian symbols file: {e}")
#         return set()

# def _format_ticker_for_yf_auto(ticker: str) -> str:
#     ticker_upper = ticker.upper().replace(".NS", "")
#     if ticker_upper in _get_indian_symbols_set():
#         return f"{ticker_upper}.NS"
#     return ticker_upper

# # ===================================================================
# #                       CORE DATA FETCHING
# # ===================================================================

# @lru_cache(maxsize=128)
# def get_company_snapshot(ticker: str) -> Dict[str, Any]:
#     """Returns a comprehensive snapshot of a company's key fundamentals."""
#     yf_ticker = _format_ticker_for_yf_auto(ticker)
#     logger.info(f"Fetching snapshot for {yf_ticker}...")
#     try:
#         stock = yf.Ticker(yf_ticker)
#         info = stock.info
#         currency = info.get("currency", "USD")
#         currency_symbol = "₹" if currency == "INR" else "$"
#         return {"currencySymbol": currency_symbol, **info}
#     except Exception as e:
#         logger.error(f"Failed to retrieve snapshot for {yf_ticker}: {e}")
#         return {"symbol": ticker, "error": str(e)}

# def get_history(ticker: str, start: str, end: str, interval: str = "1d") -> pd.DataFrame:
#     """Fetches historical market data for a given ticker."""
#     yf_ticker = _format_ticker_for_yf_auto(ticker)
#     logger.info(f"Fetching history for {yf_ticker} from {start} to {end}.")
#     try:
#         df = yf.download(yf_ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True)
#         if df.empty:
#             logger.warning(f"No data found for {yf_ticker} from {start} to {end}.")
#         return df
#     except Exception as e:
#         logger.error(f"An error occurred while fetching history for {yf_ticker}: {e}")
#         return pd.DataFrame()

# # --- NEW FUNCTION FOR ROBUST BACKTESTING DATA ---
# def get_data_for_backtesting(ticker: str, start: str, end: str) -> pd.DataFrame:
#     """
#     Fetches and correctly formats data specifically for the backtesting.py library.
#     It handles MultiIndex columns and ensures column names are in TitleCase.
#     """
#     logger.info(f"Fetching backtesting data for {ticker} from {start} to {end}.")
#     try:
#         yf_ticker = _format_ticker_for_yf_auto(ticker)
#         df = yf.download(yf_ticker, start=start, end=end, progress=False, auto_adjust=False)

#         if df.empty:
#             logger.warning(f"No data found for {yf_ticker}.")
#             return pd.DataFrame()

#         # CRITICAL FIX: Flatten MultiIndex columns if they exist
#         if isinstance(df.columns, pd.MultiIndex):
#             df.columns = df.columns.get_level_values(0)
        
#         # CRITICAL FIX: Ensure column names are in Title Case for backtesting.py
#         df.columns = [col.title() for col in df.columns]

#         # Ensure all required columns are present
#         required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
#         if not all(col in df.columns for col in required_cols):
#             logger.error(f"DataFrame for {yf_ticker} is missing required backtesting columns.")
#             return pd.DataFrame()

#         return df[required_cols] # Return in a consistent order

#     except Exception as e:
#         logger.error(f"An error occurred while fetching backtesting data for {ticker}: {e}")
#         return pd.DataFrame()

# # ===================================================================
# #                       DATA ENRICHMENT
# # ===================================================================

# def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
# # ... existing code ...

#     """Appends a curated set of key technical indicators to an OHLCV DataFrame."""
#     if df.empty or 'Close' not in df.columns or 'Volume' not in df.columns:
#         logger.warning("DataFrame is empty or missing 'Close'/'Volume' columns. Skipping TA.")
#         return df
    
#     logger.info(f"Adding technical indicators to DataFrame with {len(df)} rows...")
#     try:
#         df['volume_obv'] = ta.volume.on_balance_volume(close=df['Close'], volume=df['Volume'], fillna=True)
#         df['volatility_bbh'] = ta.volatility.bollinger_hband(close=df['Close'], window=20, window_dev=2, fillna=True)
#         df['volatility_bbl'] = ta.volatility.bollinger_lband(close=df['Close'], window=20, window_dev=2, fillna=True)
#         df['trend_sma_fast'] = ta.trend.sma_indicator(close=df['Close'], window=50, fillna=True)
#         df['trend_sma_slow'] = ta.trend.sma_indicator(close=df['Close'], window=200, fillna=True)
#         df['trend_macd'] = ta.trend.macd(close=df['Close'], window_slow=26, window_fast=12, fillna=True)
#         df['trend_macd_signal'] = ta.trend.macd_signal(close=df['Close'], window_slow=26, window_fast=12, window_sign=9, fillna=True)
#         df['momentum_rsi'] = ta.momentum.rsi(close=df['Close'], window=14, fillna=True)
        
#         logger.info(f"Successfully added indicators.")
#         return df
#     except Exception as e:
#         logger.error(f"Error adding technical indicators: {e}")
#         return df
#  import pandas as pd
# import yfinance as yf
# import ta
# import logging
# from typing import Dict, Any
# from functools import lru_cache
# from pathlib import Path

# # --- Module Configuration (This defines the 'logger' object) ---
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)


# # --- Helper function for Indian Stocks (This defines '_format_ticker_for_yf') ---
# # In utils/data_loader.py

# @lru_cache(maxsize=1)
# def _get_indian_symbols_set():
#     """
#     Loads the set of Indian stock symbols using a robust, absolute path.
#     """
#     try:
#         # --- THIS IS THE FIX ---
#         # Get the directory of the current script (utils/)
#         current_script_dir = Path(__file__).parent
#         # Go up one level to the project root (Boomerang/)
#         project_root = current_script_dir.parent
#         # Construct the full, absolute path to the CSV file
#         equity_file = project_root / "data" / "nifty500.csv"
        
#         if equity_file.exists():
#             df = pd.read_csv(equity_file)
#             logger.info(f"Successfully loaded {len(df)} Indian stock symbols from {equity_file}")
#             return set(df['Symbol'].str.upper())
#         else:
#             logger.warning(f"Indian symbols file not found at '{equity_file}'.")
#             return set()
#     except Exception as e:
#         logger.error(f"Could not load Indian symbols file: {e}")
#         return set()
# def _format_ticker_for_yf(ticker: str) -> str:
#     """Appends .NS to Indian stock tickers for Yahoo Finance compatibility."""
#     ticker_upper = ticker.upper().replace(".NS", "")
#     indian_symbols = _get_indian_symbols_set()
#     if ticker_upper in indian_symbols:
#         return f"{ticker_upper}.NS"
#     return ticker_upper


# # ===================================================================
# #                       CORE DATA FETCHING
# # ===================================================================

# @lru_cache(maxsize=128)
# def get_company_snapshot(ticker: str) -> Dict[str, Any]:
#     """Returns a comprehensive snapshot of a company's key fundamentals."""
#     yf_ticker = _format_ticker_for_yf(ticker)
#     logger.info(f"Fetching snapshot for {yf_ticker}...")
#     try:
#         stock = yf.Ticker(yf_ticker)
#         info = stock.info
#         currency = info.get("currency", "USD")
#         currency_symbol = "₹" if currency == "INR" else "$"
#         return {"currencySymbol": currency_symbol, **info}
#     except Exception as e:
#         logger.error(f"Failed to retrieve snapshot for {yf_ticker}: {e}")
#         return {"symbol": ticker, "error": str(e)}

# def get_history(ticker: str, start: str, end: str, interval: str = "1d") -> pd.DataFrame:
#     """Fetches historical market data for a given ticker."""
#     yf_ticker = _format_ticker_for_yf(ticker)
#     logger.info(f"Fetching history for {yf_ticker} from {start} to {end}.")
#     try:
#         df = yf.download(yf_ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True)
#         if df.empty:
#             logger.warning(f"No data found for {yf_ticker} from {start} to {end}.")
#         return df
#     except Exception as e:
#         logger.error(f"An error occurred while fetching history for {yf_ticker}: {e}")
#         return pd.DataFrame()


# # ===================================================================
# #                       DATA ENRICHMENT
# # ===================================================================

# def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
#     """Appends a curated set of key technical indicators to an OHLCV DataFrame."""
#     if df.empty or 'Close' not in df.columns or 'Volume' not in df.columns:
#         logger.warning("DataFrame is empty or missing 'Close'/'Volume' columns. Skipping TA.")
#         return df
    
#     logger.info(f"Adding technical indicators to DataFrame with {len(df)} rows...")
#     try:
#         df['volume_obv'] = ta.volume.on_balance_volume(close=df['Close'], volume=df['Volume'], fillna=True)
#         df['volatility_bbh'] = ta.volatility.bollinger_hband(close=df['Close'], window=20, window_dev=2, fillna=True)
#         df['volatility_bbl'] = ta.volatility.bollinger_lband(close=df['Close'], window=20, window_dev=2, fillna=True)
#         df['trend_sma_fast'] = ta.trend.sma_indicator(close=df['Close'], window=50, fillna=True)
#         df['trend_sma_slow'] = ta.trend.sma_indicator(close=df['Close'], window=200, fillna=True)
#         df['trend_macd'] = ta.trend.macd(close=df['Close'], window_slow=26, window_fast=12, fillna=True)
#         df['trend_macd_signal'] = ta.trend.macd_signal(close=df['Close'], window_slow=26, window_fast=12, window_sign=9, fillna=True)
#         df['momentum_rsi'] = ta.momentum.rsi(close=df['Close'], window=14, fillna=True)
        
#         logger.info(f"Successfully added indicators.")
#         return df
#     except Exception as e:
#         logger.error(f"Error adding technical indicators: {e}")
#         return df

# import pandas as pd
# import yfinance as yf
# import ta
# import logging
# from typing import Dict, Any
# from functools import lru_cache
# from pathlib import Path

# # --- Module Configuration ---
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)

# # --- Helper function for Indian Stocks ---
# @lru_cache(maxsize=1)
# def _get_indian_symbols_set():
#     """Loads the set of Indian stock symbols from the EQUITY_L.csv file."""
#     try:
#         # Assumes the script is run from the project root where the 'data' folder exists.
#         # This path is more robust: it starts from this file's location and goes up two levels to the project root.
#         project_root = Path(__file__).parent.parent
#         equity_file = project_root / "data" / "EQUITY_L (1).csv"
        
#         if equity_file.exists():
#             df = pd.read_csv(equity_file)
#             logger.info(f"Successfully loaded {len(df)} Indian stock symbols from {equity_file}")
#             return set(df['SYMBOL'].str.upper())
#         else:
#             logger.warning(f"Indian symbols file not found at '{equity_file}'. Indian tickers may not be formatted correctly.")
#             return set()
#     except Exception as e:
#         logger.error(f"Could not load Indian symbols file: {e}")
#         return set()

# def _format_ticker_for_yf(ticker: str) -> str:
#     """Appends .NS to Indian stock tickers for Yahoo Finance compatibility."""
#     ticker_upper = ticker.upper().replace(".NS", "")
#     indian_symbols = _get_indian_symbols_set()
#     if ticker_upper in indian_symbols:
#         return f"{ticker_upper}.NS"
#     return ticker_upper

# # ===================================================================
# #                       CORE DATA FETCHING
# # ===================================================================

# @lru_cache(maxsize=128)
# def get_company_snapshot(ticker: str) -> Dict[str, Any]:
#     """Returns a comprehensive snapshot of a company's key fundamentals."""
#     yf_ticker = _format_ticker_for_yf(ticker)
#     logger.info(f"Fetching snapshot for {yf_ticker}...")
#     try:
#         stock = yf.Ticker(yf_ticker)
#         info = stock.info
        
#         currency = info.get("currency", "USD")
#         currency_symbol = "₹" if currency == "INR" else "$"
        
#         return {
#             "currencySymbol": currency_symbol,
#             **info
#         }
#     except Exception as e:
#         logger.error(f"Failed to retrieve snapshot for {yf_ticker}: {e}")
#         return {"symbol": ticker, "error": str(e)}

# def get_history(ticker: str, start: str, end: str, interval: str = "1d") -> pd.DataFrame:
#     """Fetches historical market data for a given ticker."""
#     yf_ticker = _format_ticker_for_yf(ticker)
#     logger.info(f"Fetching history for {yf_ticker} from {start} to {end}.")
#     try:
#         df = yf.download(yf_ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True)
#         if df.empty:
#             logger.warning(f"No data found for {yf_ticker} from {start} to {end}.")
#         return df
#     except Exception as e:
#         logger.error(f"An error occurred while fetching history for {yf_ticker}: {e}")
#         return pd.DataFrame()

# # ===================================================================
# #                       DATA ENRICHMENT
# # ===================================================================

# def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
#     """
#     Appends a curated set of key technical indicators to an OHLCV DataFrame.
#     This version is corrected to pass specific columns (Series) to the ta library.
#     """
#     if df.empty or 'Close' not in df.columns or 'Volume' not in df.columns:
#         logger.warning("DataFrame is empty or missing 'Close'/'Volume' columns. Skipping technical indicators.")
#         return df
    
#     logger.info(f"Adding technical indicators to DataFrame with {len(df)} rows...")
#     try:
#         # Pass specific pandas Series (df['ColumnName']) to each function
#         df['volume_obv'] = ta.volume.on_balance_volume(close=df['Close'], volume=df['Volume'], fillna=True)
#         df['volatility_bbh'] = ta.volatility.bollinger_hband(close=df['Close'], window=20, window_dev=2, fillna=True)
#         df['volatility_bbl'] = ta.volatility.bollinger_lband(close=df['Close'], window=20, window_dev=2, fillna=True)
#         df['trend_sma_fast'] = ta.trend.sma_indicator(close=df['Close'], window=50, fillna=True)
#         df['trend_sma_slow'] = ta.trend.sma_indicator(close=df['Close'], window=200, fillna=True)
#         df['trend_macd'] = ta.trend.macd(close=df['Close'], window_slow=26, window_fast=12, fillna=True)
#         df['trend_macd_signal'] = ta.trend.macd_signal(close=df['Close'], window_slow=26, window_fast=12, window_sign=9, fillna=True)
#         df['momentum_rsi'] = ta.momentum.rsi(close=df['Close'], window=14, fillna=True)
        
#         logger.info(f"Successfully added indicators. DataFrame now has {len(df.columns)} columns.")
#         return df
#     except Exception as e:
#         logger.error(f"Error adding technical indicators: {e}")
#         return df # Return original dataframe on failure
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