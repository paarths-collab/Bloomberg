from __future__ import annotations
from datetime import date
from typing import List, Dict, Any
import pandas as pd
import requests
import logging
from functools import lru_cache
from pathlib import Path

# --- Module Configuration ---
logger = logging.getLogger(__name__)

# --- NLTK for VADER Sentiment (Local/Free) ---
# This provides a much more accurate sentiment score than simple keyword matching.
try:
    import nltk
    from nltk.sentiment import SentimentIntensityAnalyzer
    # Check if the lexicon is already downloaded
    nltk.data.find("sentiment/vader_lexicon.zip")
except LookupError:
    print("Downloading VADER lexicon for sentiment analysis (one-time download)...")
    nltk.download("vader_lexicon")
finally:
    # Ensure the analyzer is available for the function
    _HAS_NLTK = True
    SIA = SentimentIntensityAnalyzer()


# --- Constants ---
FINNHUB_BASE = "https://finnhub.io/api/v1"

# --- Helper function to format tickers for API calls ---
# This is the crucial missing helper function
@lru_cache(maxsize=1)
def _get_indian_symbols_set():
    """Loads the set of Indian stock symbols from the EQUITY_L.csv file."""
    try:
        project_root = Path(__file__).parent.parent
        equity_file = project_root / "data" / "EQUITY_L (1).csv"
        if equity_file.exists():
            df = pd.read_csv(equity_file)
            return set(df['SYMBOL'].str.upper())
        return set()
    except Exception:
        return set()

def _format_ticker_for_finnhub(ticker: str) -> str:
    """Appends .NS to Indian stock tickers for Finnhub API compatibility."""
    ticker_upper = ticker.upper().replace(".NS", "")
    indian_symbols = _get_indian_symbols_set()
    if ticker_upper in indian_symbols:
        return f"{ticker_upper}.NS"
    return ticker_upper

# ===================================================================
#                       FINNHUB API FUNCTIONS
# ===================================================================

def get_live_quote(symbol: str, api_key: str) -> Dict[str, Any]:
    """Fetches a live quote from Finnhub."""
    formatted_symbol = _format_ticker_for_finnhub(symbol)
    url = f"{FINNHUB_BASE}/quote"
    params = {"symbol": formatted_symbol, "token": api_key}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed (Finnhub get_live_quote for {formatted_symbol}): {e}")
        return {"error": str(e), "c": 0, "pc": 0}

def get_company_news(symbol: str, api_key: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """
    Fetches company news from Finnhub for a dynamic date range.
    """
    formatted_symbol = _format_ticker_for_finnhub(symbol)
    url = f"{FINNHUB_BASE}/company-news"
    params = {"symbol": formatted_symbol, "from": start_date, "to": end_date, "token": api_key}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed (Finnhub get_company_news for {formatted_symbol}): {e}")
        return []

# ===================================================================
#                       NLP SENTIMENT FUNCTION
# ===================================================================

def calculate_headline_sentiment(headlines: List[str]) -> float:
    """
    Calculates a single average compound sentiment score for a list of headlines
    using the robust VADER sentiment model.
    Returns a float between -1 (very negative) and 1 (very positive).
    """
    if not _HAS_NLTK or not headlines:
        return 0.0
    
    compound_scores = []
    for h in headlines:
        if isinstance(h, str):
            # Get the polarity scores and use the 'compound' score
            compound_scores.append(SIA.polarity_scores(h)["compound"])
            
    return sum(compound_scores) / len(compound_scores) if compound_scores else 0.0
# from __future__ import annotations
# from datetime import date, timedelta
# from typing import List, Dict, Any, Tuple
# import pandas as pd
# import requests
# import logging

# # --- Module Configuration ---
# logger = logging.getLogger(__name__)

# # --- NLTK for VADER Sentiment (Local/Free) ---
# try:
#     import nltk
#     from nltk.sentiment import SentimentIntensityAnalyzer
#     nltk.data.find("sentiment/vader_lexicon.zip")
#     _HAS_NLTK = True
# except LookupError:
#     print("Downloading VADER lexicon for sentiment analysis...")
#     nltk.download("vader_lexicon")
#     _HAS_NLTK = True
# except ImportError:
#     _HAS_NLTK = False

# # --- Constants ---
# FINNHUB_BASE = "https://finnhub.io/api/v1"

# # ===================================================================
# #                      FINNHUB API FUNCTIONS
# # ===================================================================

# def get_live_quote(symbol: str, api_key: str) -> Dict[str, Any]:
#     """Fetches a live quote from Finnhub."""
#     url = f"{FINNHUB_BASE}/quote"
#     params = {"symbol": symbol.upper(), "token": api_key}
#     try:
#         r = requests.get(url, params=params, timeout=10)
#         r.raise_for_status()
#         return r.json()
#     except requests.exceptions.RequestException as e:
#         logger.error(f"API request failed (Finnhub get_live_quote for {symbol}): {e}")
#         return {"error": str(e)}

# def get_company_news(symbol: str, api_key: str, days_back: int = 30) -> List[Dict[str, Any]]:
#     """Fetches company news from Finnhub for the last N days."""
#     to_dt = date.today()
#     from_dt = to_dt - timedelta(days=days_back)
#     url = f"{FINNHUB_BASE}/company-news"
#     params = {"symbol": symbol.upper(), "from": from_dt.isoformat(), "to": to_dt.isoformat(), "token": api_key}
#     try:
#         r = requests.get(url, params=params, timeout=15)
#         r.raise_for_status()
#         return r.json()
#     except requests.exceptions.RequestException as e:
#         logger.error(f"API request failed (Finnhub get_company_news for {symbol}): {e}")
#         return []

# # ===================================================================
# #                      RAPIDAPI FUNCTIONS
# # ===================================================================

# def get_indian_stock_by_scrip_id(scrip_id: str, rapidapi_config: dict) -> dict:
#     """Fetches detailed stock information from the indian-stock-exchange RapidAPI."""
#     api_key = rapidapi_config.get("key")
#     host = rapidapi_config.get("hosts", {}).get("indian_stock_exchange")
#     if not api_key or not host:
#         return {"error": "RapidAPI key or host for indian-stock-exchange not found in config."}

#     url = f"https://{host}/index.php"
#     querystring = {"id": scrip_id}
#     headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": host}
    
#     logger.info(f"Fetching Indian stock details for scrip ID {scrip_id} from RapidAPI...")
#     try:
#         response = requests.get(url, headers=headers, params=querystring, timeout=15)
#         response.raise_for_status()
#         return response.json()
#     except requests.exceptions.RequestException as e:
#         logger.error(f"API request failed (RapidAPI get_indian_stock_by_scrip_id for {scrip_id}): {e}")
#         return {"error": str(e)}

# # ===================================================================
# #                      NLP SENTIMENT FUNCTION
# # ===================================================================

# def calculate_headline_sentiment(headlines: List[str]) -> float:
#     """
#     Calculates a single average compound sentiment score for a list of headlines.
#     Returns a float between -1 (very negative) and 1 (very positive).
#     """
#     if not _HAS_NLTK or not headlines:
#         return 0.0
        
#     sia = SentimentIntensityAnalyzer()
    
#     compound_scores = []
#     for h in headlines:
#         if isinstance(h, str):
#             compound_scores.append(sia.polarity_scores(h)["compound"])
            
#     return sum(compound_scores) / len(compound_scores) if compound_scores else 0.0