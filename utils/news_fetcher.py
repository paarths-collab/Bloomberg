# fetch news headlines


# utils/news_fetcher.py
from __future__ import annotations
from datetime import date, timedelta
from typing import List, Dict, Any, Tuple
import os
import requests

# Simple local sentiment (no paid API): VADER
import nltk
from nltk.sentiment import SentimentIntensityAnalyzer

# Ensure VADER lexicon is available (downloads once)
try:
    nltk.data.find("sentiment/vader_lexicon.zip")
except LookupError:
    nltk.download("vader_lexicon")

# In utils/news_fetcher.py (add this new function)
import pandas as pd

def get_insider_transactions(symbol: str, api_key: str) -> pd.DataFrame:
    """Fetches insider transactions from Finnhub and returns them as a DataFrame."""
    url = f"{FINNHUB_BASE}/stock/insider-transactions"
    params = {"symbol": symbol, "token": api_key}
    try:
        r = requests.get(url, headers=_headers(), params=params, timeout=15)
        r.raise_for_status()
        data = r.json().get('data', [])
        
        if not data:
            return pd.DataFrame({"Message": [f"No recent insider data found for {symbol}"]})
            
        # Convert the list of dictionaries to a DataFrame
        df = pd.DataFrame(data)
        
        # Select and rename columns for a cleaner display
        df = df[['name', 'share', 'change', 'transactionDate', 'transactionPrice']]
        df.columns = ['Insider Name', 'Shares', 'Change', 'Date', 'Price']
        
        # Keep only the top 10 most recent transactions
        return df.head(10)
        
    except Exception as e:
        print(f"Error fetching insider data for {symbol}: {e}")
        return pd.DataFrame({"Message": [f"Could not fetch insider data for {symbol}"]})
FINNHUB_BASE = "https://finnhub.io/api/v1"

def _headers():
    return {"accept": "application/json"}

def finnhub_symbol(symbol: str, use_nse_prefix: bool = False, nse_prefix: str = "NSE:") -> str:
    # Finnhub US symbols are plain ("AAPL"); Indian NSE tickers use "NSE:INFY"
    if use_nse_prefix and ":" not in symbol:
        return f"{nse_prefix}{symbol.replace('.NS','').upper()}"
    return symbol

def get_live_quote(symbol: str, api_key: str, use_nse: bool = False, nse_prefix: str = "NSE:") -> Dict[str, Any]:
    sym = finnhub_symbol(symbol, use_nse, nse_prefix)
    url = f"{FINNHUB_BASE}/quote"
    params = {"symbol": sym, "token": api_key}
    r = requests.get(url, headers=_headers(), params=params, timeout=15)
    r.raise_for_status()
    return r.json()  # keys: c (current), h, l, o, pc, t

def get_company_news(symbol: str, api_key: str, days_back: int = 7,
                     use_nse: bool = False, nse_prefix: str = "NSE:") -> List[Dict[str, Any]]:
    sym = finnhub_symbol(symbol, use_nse, nse_prefix)
    to_dt = date.today()
    from_dt = to_dt - timedelta(days=days_back)
    url = f"{FINNHUB_BASE}/company-news"
    params = {
        "symbol": sym,
        "from": from_dt.isoformat(),
        "to": to_dt.isoformat(),
        "token": api_key,
    }
    r = requests.get(url, headers=_headers(), params=params, timeout=20)
    r.raise_for_status()
    return r.json()  # list of articles

def sentiment_on_headlines(headlines: List[str]) -> Tuple[float, List[Dict[str, Any]]]:
    """Return average compound sentiment and per-headline scores using VADER."""
    if not headlines:
        return 0.0, []
    sia = SentimentIntensityAnalyzer()
    scored = []
    total = 0.0
    for h in headlines:
        s = sia.polarity_scores(h)  # dict with 'compound'
        total += s["compound"]
        scored.append({"headline": h, "scores": s})
    avg = total / len(headlines)
    return avg, scored
