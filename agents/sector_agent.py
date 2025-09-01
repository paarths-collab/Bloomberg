import yfinance as yf
import pandas as pd
import numpy as np
import requests
import streamlit as st
import plotly.express as px
import os

# --- Try to import transformers, but don't fail if it's not there ---
try:
    from transformers import pipeline
    _HAS_TRANSFORMERS = True
except ImportError:
    pipeline = None
    _HAS_TRANSFORMERS = False

class SectorAgent:
    def __init__(self, news_api_key: str):
        self.news_api_key = news_api_key
        if _HAS_TRANSFORMERS:
            self.sentiment_model = pipeline("sentiment-analysis", model="ProsusAI/finbert")
            print("✅ SectorAgent: FinBERT sentiment model loaded.")
        else:
            self.sentiment_model = None
            print("❌ SectorAgent WARNING: 'transformers' not installed. Sentiment analysis is disabled.")
        
        # Define sector mappings
        self.sectors = {
            "US": {"Technology": "XLK", "Healthcare": "XLV", "Financials": "XLF", "Energy": "XLE", "Consumer Discretionary": "XLY"},
            "India": {"IT": "TCS.NS", "Pharma": "SUNPHARMA.NS", "Banking": "HDFCBANK.NS", "Auto": "TATAMOTORS.NS"}
        }

    def _fetch_performance(self, ticker, start, end):
        try:
            df = yf.download(ticker, start=start, end=end, progress=False)
            if df.empty: return 0.0
            return (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100
        except Exception:
            return 0.0

    def _get_sentiment_score(self, sector, market):
        if not self.sentiment_model or not self.news_api_key: return 0.0
        query = f"{sector} sector {market}"
        url = f"https://newsapi.org/v2/everything?q={query}&language=en&apiKey={self.news_api_key}"
        try:
            articles = requests.get(url).json().get("articles", [])
            if not articles: return 0.0
            
            texts = [f"{a.get('title', '')}. {a.get('description', '')}" for a in articles[:5]]
            sentiments = self.sentiment_model(texts)
            
            score = 0
            for sent in sentiments:
                if sent['label'] == 'positive': score += sent['score']
                elif sent['label'] == 'negative': score -= sent['score']
            return score / len(sentiments) if sentiments else 0.0
        except Exception:
            return 0.0

    def analyze(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Analyzes all defined sectors and returns a ranked DataFrame."""
        print(f"SectorAgent: Analyzing sector performance from {start_date} to {end_date}...")
        data = []
        for market, sectors_map in self.sectors.items():
            for sector, ticker in sectors_map.items():
                perf = self._fetch_performance(ticker, start_date, end_date)
                sentiment = self._get_sentiment_score(sector, market)
                score = 0.7 * perf + 0.3 * sentiment * 100 # Weighted score
                data.append((market, sector, f"{perf:.2f}%", f"{sentiment:.2f}", f"{score:.2f}"))
        df = pd.DataFrame(data, columns=["Market", "Sector", "Performance", "Sentiment", "Booming Score"])
        df['Booming Score'] = pd.to_numeric(df['Booming Score'])
        return df.sort_values("Booming Score", ascending=False).reset_index(drop=True)

# --- Streamlit Visualization ---
if __name__ == "__main__":
    st.set_page_config(page_title="Sector Analysis Agent", layout="wide")
    st.title("🌍 Sector Analysis Agent Showcase")

    NEWS_API_KEY = st.secrets.get("NEWS_API_KEY", os.getenv("NEWS_API_KEY"))
    if not NEWS_API_KEY:
        st.error("NEWS_API_KEY not found! Please set it in your Streamlit secrets.")
    else:
        agent = SectorAgent(news_api_key=NEWS_API_KEY)
        with st.sidebar:
            st.header("⚙️ Configuration")
            start_date = st.date_input("Start Date", pd.to_datetime("today") - pd.DateOffset(months=3))
            end_date = st.date_input("End Date", pd.to_datetime("today"))
            run_button = st.button("🔬 Analyze Sectors", use_container_width=True)

        if run_button:
            st.header("Sector Performance Rankings")
            with st.spinner("Fetching performance and analyzing news sentiment for all sectors..."):
                results_df = agent.analyze(str(start_date), str(end_date))
                st.dataframe(results_df)
                
                st.subheader("Booming Score Comparison")
                fig = px.bar(results_df, x="Sector", y="Booming Score", color="Market",
                             title="Sector 'Booming' Score (Performance + Sentiment)")
                st.plotly_chart(fig, use_container_width=True)