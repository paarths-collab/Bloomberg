  # finds booming sectors
import yfinance as yf
import pandas as pd
import numpy as np
import datetime
import requests
from transformers import pipeline

# ---------------------------
# 1. Setup FinBERT for sentiment
# ---------------------------
sentiment_model = pipeline("sentiment-analysis", model="ProsusAI/finbert")

# ---------------------------
# 2. Define sectors & tickers
# ---------------------------
sectors = {
    "India": {
        "Consumer": ["HINDUNILVR.NS", "MARICO.NS"],
        "Pharma": ["SUNPHARMA.NS", "DRREDDY.NS"],
        "IT": ["TCS.NS", "INFY.NS"],
        "Auto": ["TATAMOTORS.NS", "M&M.NS"],
        "Power": ["POWERGRID.NS", "NTPC.NS"]
    },
    "US": {
        "Tech": ["XLK"],        # Sector ETFs
        "Healthcare": ["XLV"],
        "Financials": ["XLF"],
        "Energy": ["XLE"],
        "Utilities": ["XLU"]
    }
}

# ---------------------------
# 3. Fetch performance
# ---------------------------
def fetch_performance(tickers, start, end):
    changes = []
    for ticker in tickers:
        df = yf.download(ticker, start=start, end=end, progress=False)
        if df.empty: 
            continue
        pct = (df["Close"][-1] / df["Close"][0] - 1) * 100
        changes.append(pct)
    return np.mean(changes) if changes else np.nan

# ---------------------------
# 4. News Sentiment
# ---------------------------
NEWS_API_KEY = "YOUR_NEWSAPI_KEY"   # 🔑 Replace with your API key

def get_sentiment_score(sector, market="India"):
    url = f"https://newsapi.org/v2/everything?q={sector}+{market}+stocks&sortBy=publishedAt&language=en&apiKey={NEWS_API_KEY}"
    articles = requests.get(url).json().get("articles", [])
    
    if not articles:
        return 0.0  # neutral if no news
    
    scores = []
    for article in articles[:5]:  # analyze top 5 articles
        text = (article.get("title", "") or "") + " " + (article.get("description", "") or "")
        if not text.strip():
            continue
        result = sentiment_model(text)[0]
        if result["label"] == "positive":
            scores.append(result["score"])
        elif result["label"] == "negative":
            scores.append(-result["score"])
        else:
            scores.append(0)
    return sum(scores) / len(scores) if scores else 0

# ---------------------------
# 5. Seasonality Scoring
# ---------------------------
def get_seasonality_score(sector, market="India"):
    month = datetime.datetime.now().month
    score = 0
    
    if market == "India":
        if sector == "Consumer" and month in [9,10,11]:  # festive demand
            score += 0.5
        if sector == "Power" and month in [4,5,6,7]:    # summer demand
            score += 0.4
        if sector == "Auto" and month in [8,9,10]:      # festive demand
            score += 0.3
    
    elif market == "US":
        if sector == "Retail" and month == 12:          # holiday shopping
            score += 0.5
        if sector == "Tech" and month in [7]:           # Q2 earnings
            score += 0.3
        if month in [8,9]:                              # weak months
            score -= 0.4
    
    return score

# ---------------------------
# 6. Combine everything
# ---------------------------
start_date, end_date = "2025-06-01", "2025-08-28"
data = []

for market in sectors:
    for sector, ticks in sectors[market].items():
        perf = fetch_performance(ticks, start_date, end_date)
        sentiment = get_sentiment_score(sector, market)
        seasonality = get_seasonality_score(sector, market)
        
        # Weighted booming score
        score = 0.5*perf + 0.3*sentiment*100 + 0.2*seasonality*100  # scaled sentiment & seasonality
        data.append((market, sector, perf, sentiment, seasonality, score))

df = pd.DataFrame(data, columns=["Market","Sector","Performance(%)","Sentiment","Seasonality","Booming Score"])
df = df.sort_values(["Market","Booming Score"], ascending=[True, False])

print("📊 Booming Sectors Ranking:")
print(df.groupby("Market").head(3))
