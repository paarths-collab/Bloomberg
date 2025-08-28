# chooses stocks from sectors

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from textblob import TextBlob
import random
import requests
from transformers import pipeline


# -------------------------------
# SECTOR & STOCK MAPPING
# -------------------------------
SECTOR_STOCKS = {
    "India": {
        "IT": ["INFY.NS", "TCS.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS", "MPHASIS.NS", "LTIM.NS", "COFORGE.NS", "PERSISTENT.NS", "NIITTECH.NS"],
        "Banking": ["HDFCBANK.NS", "ICICIBANK.NS", "AXISBANK.NS", "KOTAKBANK.NS", "SBIN.NS", "PNB.NS", "IDFCFIRSTB.NS", "BANDHANBNK.NS", "RBLBANK.NS", "YESBANK.NS"],
        "Pharma": ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "AUROPHARMA.NS", "BIOCON.NS", "LUPIN.NS", "ZYDUSLIFE.NS", "ALKEM.NS", "TORNTPHARM.NS"]
    },
    "US": {
        "Tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "ADBE", "INTC", "CSCO"],
        "Banking": ["JPM", "BAC", "WFC", "C", "GS", "MS", "PNC", "USB", "SCHW", "TFC"],
        "Healthcare": ["JNJ", "PFE", "MRK", "UNH", "ABBV", "AMGN", "BMY", "LLY", "GILD", "CVS"]
    }
}

# -------------------------------
# SENTIMENT SCORING (stub for demo)
# -------------------------------
def get_sentiment_score(stock: str) -> float:
    # Ideally: fetch news → NLP sentiment scoring
    # Placeholder: random with slight positive bias
    return round(random.uniform(-1, 1), 2)

# -------------------------------
# SEASONALITY SCORING
# -------------------------------
sentiment_analyzer = pipeline("sentiment-analysis")

def fetch_seasonal_news(sector: str, month: int, region: str = "India") -> list:
    """
    Fetch seasonal news for a given sector and month.
    You can replace this with a real news API (e.g., NewsAPI, Google News).
    """
    query = f"{sector} sector seasonality {datetime.now().year} {region} month {month}"
    url = f"https://newsapi.org/v2/everything?q={query}&apiKey=YOUR_NEWS_API_KEY"
    response = requests.get(url)
    if response.status_code == 200:
        articles = response.json().get("articles", [])
        return [a["title"] + " " + a.get("description", "") for a in articles]
    return []

def seasonality_factor(sector: str, date: datetime, region: str = "India") -> float:
    """
    Dynamically calculates seasonality factor using news + sentiment.
    """
    month = date.month
    news_articles = fetch_seasonal_news(sector, month, region)

    if not news_articles:
        return 0.0

    sentiment_scores = []
    for article in news_articles:
        result = sentiment_analyzer(article[:512])[0]  # Truncate long text
        score = result["score"] if result["label"] == "POSITIVE" else -result["score"]
        sentiment_scores.append(score)

    # Average sentiment as seasonality factor
    if sentiment_scores:
        return sum(sentiment_scores) / len(sentiment_scores)
    return 0.0
# -------------------------------
# STOCK PERFORMANCE
# -------------------------------
def get_stock_performance(ticker: str, start: str, end: str) -> float:
    try:
        data = yf.download(ticker, start=start, end=end, progress=False)
        if len(data) > 1:
            start_price = data["Close"].iloc[0]
            end_price = data["Close"].iloc[-1]
            return ((end_price - start_price) / start_price) * 100
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
    return 0.0

# -------------------------------
# MAIN FUNCTION
# -------------------------------
def analyze_markets(start_date: str, end_date: str):
    results = {}
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    
    for market, sectors in SECTOR_STOCKS.items():
        results[market] = {}
        for sector, stocks in sectors.items():
            stock_scores = []
            for stock in stocks:
                perf = get_stock_performance(stock, start_date, end_date)
                sentiment = get_sentiment_score(stock)
                seasonal = seasonality_factor(sector, end_dt)
                
                # Weighted score
                score = (0.6 * perf) + (0.3 * sentiment * 10) + (0.1 * seasonal * 100)
                stock_scores.append((stock, perf, sentiment, seasonal, score))
            
            # Sort top 10 stocks per sector
            stock_scores.sort(key=lambda x: x[-1], reverse=True)
            results[market][sector] = stock_scores[:10]
    
    return results

# -------------------------------
# RUN EXAMPLE
# -------------------------------
if __name__ == "__main__":
    start = "2025-01-01"
    end = "2025-08-01"
    booming = analyze_markets(start, end)

    for market, sectors in booming.items():
        print(f"\n=== {market} ===")
        for sector, stocks in sectors.items():
            print(f"\nTop Stocks in {sector}:")
            for stock, perf, sentiment, seasonal, score in stocks:
                print(f"{stock}: Perf {perf:.2f}%, Sent {sentiment}, Seas {seasonal}, Final Score {score:.2f}")
