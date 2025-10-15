import requests
import streamlit as st
import pandas as pd
import os

class AnalystAgent:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.metrics_url = "https://finnhub.io/api/v1/stock/metric"
        if not self.api_key:
            print("[WARNING] AnalystAgent: Finnhub API Key is missing.")

    def _safe_request(self, url, params):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def analyze(self, ticker: str) -> dict:
        """
        Provides a quantitative analysis snapshot using Finnhub's financial metrics.
        """
        if not self.api_key: return {"error": "API key not provided."}

        params = {"symbol": ticker.upper(), "metric": "all", "token": self.api_key}
        response = self._safe_request(self.metrics_url, params)

        if "error" in response or not isinstance(response, dict) or "metric" not in response:
            return {"error": response.get("error", "No financial data available from Finnhub.")}

        metrics = response["metric"]
        pe_ratio = metrics.get("peNormalizedAnnual")
        
        # Simple valuation heuristic
        if pe_ratio is None: valuation = "Unknown"
        elif pe_ratio > 35: valuation = "Potentially Overvalued"
        elif pe_ratio > 20: valuation = "Fairly Valued"
        else: valuation = "Potentially Undervalued"

        return {
            "P/E Ratio (Normalized Annual)": pe_ratio,
            "EPS (Normalized Annual)": metrics.get("epsNormalizedAnnual"),
            "52-Week High": metrics.get("52WeekHigh"),
            "52-Week Low": metrics.get("52WeekLow"),
            "Beta": metrics.get("beta"),
            "Market Capitalization (M)": metrics.get("marketCapitalization"),
            "Quick Valuation": valuation,
        }

# --- Streamlit Visualization ---
if __name__ == "__main__":
    st.set_page_config(page_title="Quantitative Analyst Agent", layout="wide")
    st.title("🔬 Quantitative Analyst Snapshot (Finnhub)")

    FINNHUB_KEY = st.secrets.get("FINNHUB_API_KEY", os.getenv("FINNHUB_API_KEY"))

    if not FINNHUB_KEY:
        st.error("Finnhub API key not found! Please set it in your Streamlit secrets.")
    else:
        agent = AnalystAgent(api_key=FINNHUB_KEY)
        
        st.sidebar.header("⚙️ Configuration")
        ticker = st.sidebar.text_input("Ticker Symbol", "TSLA")
        run_button = st.sidebar.button("🔬 Get Analysis", use_container_width=True)

        if run_button:
            st.header(f"Results for {ticker}")
            with st.spinner(f"Fetching quantitative metrics for {ticker}..."):
                results = agent.analyze(ticker)

                if "error" in results:
                    st.error(results["error"])
                else:
                    st.subheader("Valuation & Risk Metrics")
                    # Display as a clean table
                    df = pd.DataFrame(list(results.items()), columns=['Metric', 'Value'])
                    st.table(df.set_index('Metric'))