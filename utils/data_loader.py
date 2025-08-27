# fetch market data (yfinance/TA-Lib)

# utils/data_loader.py
from typing import Dict, Any, Optional, List
import pandas as pd
import yfinance as yf
import ta
import numpy as np
import logging
from datetime import datetime, timedelta

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_company_snapshot(ticker: str) -> Dict[str, Any]:
    """Return key fundamentals and statements for a ticker using yfinance."""
    try:
        t = yf.Ticker(ticker)
        info = t.info if hasattr(t, "info") else {}
        
        snapshot = {
            "symbol": ticker,
            "longName": info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "marketCap": info.get("marketCap"),
            "trailingPE": info.get("trailingPE"),
            "forwardPE": info.get("forwardPE"),
            "pegRatio": info.get("pegRatio"),
            "dividendYield": info.get("dividendYield"),
            "profitMargins": info.get("profitMargins"),
            "returnOnEquity": info.get("returnOnEquity"),
            "returnOnAssets": info.get("returnOnAssets"),
            "debtToEquity": info.get("debtToEquity"),
            "currentRatio": info.get("currentRatio"),
            "quickRatio": info.get("quickRatio"),
            "bookValue": info.get("bookValue"),
            "priceToBook": info.get("priceToBook"),
            "enterpriseValue": info.get("enterpriseValue"),
            "ebitdaMargins": info.get("ebitdaMargins"),
            "grossMargins": info.get("grossMargins"),
            "operatingMargins": info.get("operatingMargins"),
            "beta": info.get("beta"),
            "52WeekHigh": info.get("fiftyTwoWeekHigh"),
            "52WeekLow": info.get("fiftyTwoWeekLow"),
            "averageVolume": info.get("averageVolume"),
            "sharesOutstanding": info.get("sharesOutstanding"),
            "floatShares": info.get("floatShares"),
            "heldPercentInsiders": info.get("heldPercentInsiders"),
            "heldPercentInstitutions": info.get("heldPercentInstitutions"),
        }
        
        # Financial statements (can be empty for some tickers)
        snapshot["financials"] = _safe_df(t.financials)
        snapshot["balance_sheet"] = _safe_df(t.balance_sheet)
        snapshot["cashflow"] = _safe_df(t.cashflow)
        snapshot["earnings"] = _safe_df(t.earnings)
        
        logger.info(f"Successfully retrieved snapshot for {ticker}")
        return snapshot
        
    except Exception as e:
        logger.error(f"Error retrieving snapshot for {ticker}: {e}")
        return {"symbol": ticker, "error": str(e)}

def _safe_df(df: pd.DataFrame | None) -> pd.DataFrame:
    """Safely return DataFrame or empty DataFrame if None."""
    if df is None:
        return pd.DataFrame()
    return df

def get_history(
    ticker: str, 
    period: str = "1y", 
    interval: str = "1d",
    start: Optional[str] = None,
    end: Optional[str] = None
) -> pd.DataFrame:
    """
    Historical OHLCV as DataFrame.
    
    Args:
        ticker: Stock symbol
        period: Valid periods: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max
        interval: Valid intervals: 1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo
        start: Start date string (YYYY-MM-DD) - alternative to period
        end: End date string (YYYY-MM-DD) - alternative to period
    """
    try:
        t = yf.Ticker(ticker)
        
        if start and end:
            df = t.history(start=start, end=end, interval=interval, auto_adjust=True)
        else:
            df = t.history(period=period, interval=interval, auto_adjust=True)
            
        if not isinstance(df, pd.DataFrame) or df.empty:
            raise ValueError(f"No history returned for {ticker}")
            
        # Clean up column names and ensure proper data types
        df.columns = df.columns.str.title()  # Ensure consistent capitalization
        df = df.dropna()  # Remove any NaN rows
        
        logger.info(f"Retrieved {len(df)} rows of data for {ticker}")
        return df
        
    except Exception as e:
        logger.error(f"Error retrieving history for {ticker}: {e}")
        raise

def get_multiple_tickers(
    tickers: List[str], 
    period: str = "1y", 
    interval: str = "1d"
) -> Dict[str, pd.DataFrame]:
    """Get historical data for multiple tickers at once."""
    results = {}
    
    try:
        # Use yfinance's download function for efficiency
        data = yf.download(tickers, period=period, interval=interval, auto_adjust=True, group_by='ticker')
        
        if len(tickers) == 1:
            # Single ticker case
            results[tickers[0]] = data
        else:
            # Multiple tickers case
            for ticker in tickers:
                if ticker in data.columns.get_level_values(0):
                    ticker_data = data[ticker].dropna()
                    if not ticker_data.empty:
                        results[ticker] = ticker_data
                        
        logger.info(f"Retrieved data for {len(results)} out of {len(tickers)} tickers")
        return results
        
    except Exception as e:
        logger.error(f"Error retrieving multiple tickers: {e}")
        return {}

def add_indicators(df: pd.DataFrame, config: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """
    Append commonly used indicators to the OHLCV DataFrame using ta library.
    
    Args:
        df: OHLCV DataFrame
        config: Optional configuration for indicators
    """
    if df.empty:
        return df
        
    # Default configuration
    default_config = {
        "sma_periods": [20, 50, 200],
        "ema_periods": [12, 26],
        "rsi_period": 14,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "atr_period": 14,
        "bb_period": 20,
        "bb_std": 2,
    }
    
    if config:
        default_config.update(config)
    
    try:
        out = df.copy()
        
        # Simple Moving Averages
        for period in default_config["sma_periods"]:
            out[f'SMA{period}'] = ta.trend.sma_indicator(out['Close'], window=period)
            
        # Exponential Moving Averages
        for period in default_config["ema_periods"]:
            out[f'EMA{period}'] = ta.trend.ema_indicator(out['Close'], window=period)
            
        # RSI
        out[f'RSI{default_config["rsi_period"]}'] = ta.momentum.rsi(
            out['Close'], window=default_config["rsi_period"]
        )
        
        # MACD
        macd_line = ta.trend.macd(
            out['Close'],
            window_slow=default_config["macd_slow"],
            window_fast=default_config["macd_fast"]
        )
        macd_signal = ta.trend.macd_signal(
            out['Close'],
            window_slow=default_config["macd_slow"],
            window_fast=default_config["macd_fast"],
            window_sign=default_config["macd_signal"]
        )
        out['MACD'] = macd_line
        out['MACD_Signal'] = macd_signal
        out['MACD_Hist'] = macd_line - macd_signal
        
        # Average True Range
        out[f'ATR{default_config["atr_period"]}'] = ta.volatility.average_true_range(
            out['High'], out['Low'], out['Close'], window=default_config["atr_period"]
        )
        
        # Bollinger Bands
        bb_high = ta.volatility.bollinger_hband(
            out['Close'], 
            window=default_config["bb_period"], 
            window_dev=default_config["bb_std"]
        )
        bb_low = ta.volatility.bollinger_lband(
            out['Close'], 
            window=default_config["bb_period"], 
            window_dev=default_config["bb_std"]
        )
        bb_mid = ta.volatility.bollinger_mavg(
            out['Close'], 
            window=default_config["bb_period"]
        )
        
        out['BB_Upper'] = bb_high
        out['BB_Middle'] = bb_mid
        out['BB_Lower'] = bb_low
        out['BB_Width'] = (bb_high - bb_low) / bb_mid * 100
        out['BB_Position'] = (out['Close'] - bb_low) / (bb_high - bb_low)
        
        # Volume indicators (if volume data available)
        if 'Volume' in out.columns:
            out['OBV'] = ta.volume.on_balance_volume(out['Close'], out['Volume'])
            out['AD'] = ta.volume.acc_dist_index(out['High'], out['Low'], out['Close'], out['Volume'])
        
        # Additional momentum indicators
        stoch_k = ta.momentum.stoch(out['High'], out['Low'], out['Close'])
        stoch_d = ta.momentum.stoch_signal(out['High'], out['Low'], out['Close'])
        out['STOCH_K'] = stoch_k
        out['STOCH_D'] = stoch_d
        
        out['WILLR'] = ta.momentum.williams_r(out['High'], out['Low'], out['Close'])
        out['CCI'] = ta.trend.cci(out['High'], out['Low'], out['Close'])
        
        # Trend indicators
        out['ADX'] = ta.trend.adx(out['High'], out['Low'], out['Close'])
        
        # Parabolic SAR
        out['SAR'] = ta.trend.psar_down(out['High'], out['Low'], out['Close'])
        
        logger.info(f"Added {len(out.columns) - len(df.columns)} technical indicators")
        return out
        
    except Exception as e:
        logger.error(f"Error adding indicators: {e}")
        return df

def calculate_returns(df: pd.DataFrame, periods: List[int] = [1, 5, 21, 63, 252]) -> pd.DataFrame:
    """Calculate returns for various periods."""
    if df.empty or 'Close' not in df.columns:
        return df
        
    out = df.copy()
    
    for period in periods:
        if period == 1:
            out[f'Return_{period}d'] = out['Close'].pct_change()
        else:
            out[f'Return_{period}d'] = out['Close'].pct_change(periods=period)
            
    # Calculate rolling volatility
    out['Volatility_21d'] = out['Return_1d'].rolling(21).std() * (252 ** 0.5)  # Annualized
    out['Volatility_63d'] = out['Return_1d'].rolling(63).std() * (252 ** 0.5)
    
    return out

def get_market_data(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    add_technicals: bool = True,
    add_returns: bool = True,
    technical_config: Optional[Dict[str, Any]] = None
) -> pd.DataFrame:
    """
    Comprehensive function to get market data with indicators.
    
    Args:
        ticker: Stock symbol
        period: Time period for data
        interval: Data frequency
        add_technicals: Whether to add technical indicators
        add_returns: Whether to add return calculations
        technical_config: Custom configuration for technical indicators
    """
    try:
        # Get base OHLCV data
        df = get_history(ticker, period=period, interval=interval)
        
        if add_technicals:
            df = add_indicators(df, config=technical_config)
            
        if add_returns:
            df = calculate_returns(df)
            
        logger.info(f"Final dataset for {ticker}: {df.shape[0]} rows, {df.shape[1]} columns")
        return df
        
    except Exception as e:
        logger.error(f"Error in get_market_data for {ticker}: {e}")
        raise

# Example usage and testing
if __name__ == "__main__":
    # Test the functions
    try:
        # Test single ticker
        print("Testing single ticker data retrieval...")
        data = get_market_data("AAPL", period="6mo", add_technicals=True, add_returns=True)
        print(f"AAPL data shape: {data.shape}")
        print(f"Columns: {list(data.columns)}")
        print(f"Latest data:")
        print(data[['Close', 'SMA50', 'SMA200', 'RSI14', 'MACD']].tail())
        
        # Test company snapshot
        print("\nTesting company snapshot...")
        snapshot = get_company_snapshot("AAPL")
        print(f"Company: {snapshot.get('longName')}")
        print(f"Sector: {snapshot.get('sector')}")
        print(f"P/E Ratio: {snapshot.get('trailingPE')}")
        
        # Test multiple tickers
        print("\nTesting multiple tickers...")
        tickers = ["AAPL", "MSFT", "GOOGL"]
        multi_data = get_multiple_tickers(tickers, period="1mo")
        print(f"Retrieved data for: {list(multi_data.keys())}")
        
    except Exception as e:
        print(f"Error in testing: {e}")

