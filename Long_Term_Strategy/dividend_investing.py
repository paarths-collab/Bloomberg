import yfinance as yf
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import datetime

# --- Core Logic ---
def analyze(stock_symbol: str) -> dict:
    try:
        stock = yf.Ticker(stock_symbol)
        info = stock.info
        
        div_yield = info.get("dividendYield")
        if not div_yield or div_yield == 0:
            return {"current_metrics": {"Message": "This stock does not pay a dividend."}, "historical_performance": []}

        payout_ratio = info.get("payoutRatio")
        current_metrics = {
            "Current Dividend Yield": div_yield * 100,
            "Payout Ratio": payout_ratio * 100 if payout_ratio else None,
        }

        dividends = stock.dividends
        hist_prices = stock.history(period="max")
        if dividends.empty or hist_prices.empty:
            return {"current_metrics": current_metrics, "historical_performance": []}
        
        if dividends.index.tz is not None: dividends.index = dividends.index.tz_localize(None)
        if hist_prices.index.tz is not None: hist_prices.index = hist_prices.index.tz_localize(None)
            
        dividends_yearly = dividends.resample("YE").sum()
        historical_performance = []
        
        periods = [1, 3, 5, 10]
        today = pd.Timestamp.now().tz_localize(None)

        for years in periods:
            start_date = today - pd.DateOffset(years=years)
            period_divs = dividends_yearly[dividends_yearly.index >= start_date]
            if len(period_divs) < 2: continue

            start_div, end_div = period_divs.iloc[0], period_divs.iloc[-1]
            actual_years = (period_divs.index[-1] - period_divs.index[0]).days / 365.25

            cagr = ((end_div / start_div) ** (1 / actual_years) - 1) * 100 if start_div > 0 and end_div > 0 and actual_years > 0 else None

            price_at_start = hist_prices["Close"].asof(period_divs.index[0])
            avg_yield = (period_divs.mean() / price_at_start) * 100 if price_at_start is not None and price_at_start > 0 else 0

            historical_performance.append({
                "Period": f"{years}-Year",
                "Dividend Growth (CAGR) %": cagr,
                "Average Yield on Cost %": avg_yield,
            })

        return {"current_metrics": current_metrics, "historical_performance": historical_performance}
    except Exception as e:
        return {"Error": f"Could not fetch dividend metrics for {stock_symbol}: {e}"}

# --- Streamlit Visualization ---
if __name__ == "__main__":
    st.set_page_config(page_title="Dividend Investing Analysis", layout="wide")
    st.title("💰 Dividend Investing Deep Dive")
    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "KO")
        run_button = st.button("🔬 Analyze", use_container_width=True)

    if run_button:
        st.header(f"Results for {ticker}")
        with st.spinner("Fetching and analyzing historical data..."):
            results = analyze(ticker)
            if "Error" in results:
                st.error(results["Error"])
            else:
                current = results.get("current_metrics", {})
                historical_df = pd.DataFrame(results.get("historical_performance", []))

                if "Message" in current:
                    st.warning(current["Message"])
                else:
                    st.subheader("Current Dividend Metrics")
                    cols = st.columns(2)
                    cols[0].metric("Current Dividend Yield", f"{current.get('Current Dividend Yield', 0):.2f}%")
                    cols[1].metric("Payout Ratio", f"{current.get('Payout Ratio', 0):.2f}%" if current.get('Payout Ratio') else "N/A")

                    if not historical_df.empty:
                        st.subheader("Historical Performance")
                        st.dataframe(historical_df.set_index("Period"))
                        fig = px.bar(historical_df, x='Period', y=['Dividend Growth (CAGR) %', 'Average Yield on Cost %'],
                                     title='Historical Dividend Growth and Yield', barmode='group')
                        st.plotly_chart(fig, use_container_width=True)