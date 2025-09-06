import streamlit as st
import sys
import pathlib
import pandas as pd
import plotly.express as px
import alpaca_trade_api
import alpacalib
from alpaca.trading.client import TradingClient
from backtesting import Backtest, Strategy

# Path setup
sys.path.append(str(pathlib.Path(__file__).parent.parent))
from agents.orchestrator import Orchestrator

st.set_page_config(page_title="Market Overview", layout="wide")
st.title("📈 Global Market Overview")

@st.cache_resource
def load_orchestrator():
    config_path = "quant-company-insights-agent/config.yaml"
    return Orchestrator.from_file(config_path)

orchestrator = load_orchestrator()

with st.spinner("Fetching live market and economic data..."):
    overview_data = orchestrator.run_market_overview()

    global_data = overview_data.get("global_indicators", {})
    us_data = overview_data.get("us_indicators", {})
    india_data = overview_data.get("india_indicators", {})

    st.header("🌐 Global Risk Indicators")
    if "Error" in global_data: st.error(global_data["Error"])
    else:
        cols = st.columns(4)
        cols[0].metric("VIX (Fear Index)", global_data.get("VIX (Fear Index)", "N/A"))
        cols[1].metric("US 10Y Yield", f"{global_data.get('US 10Y Yield %', 'N/A')}%")
        cols[2].metric("Gold Price", global_data.get("Gold Price (USD)", "N/A"))
        cols[3].metric("Crude Oil (WTI)", global_data.get("Crude Oil (WTI)", "N/A"))

    st.header("🇺🇸 US Economic Indicators (from FRED)")
    if "Error" in us_data: st.error(us_data["Error"])
    else:
        cols = st.columns(4)
        cols[0].metric("GDP", us_data.get("US GDP (Billions $)", "N/A"))
        cols[1].metric("CPI", us_data.get("US CPI (Inflation Index)", "N/A"))
        cols[2].metric("Unemployment Rate", f"{us_data.get('US Unemployment Rate %', 'N/A')}%")
        cols[3].metric("Fed Funds Rate", f"{us_data.get('US Fed Funds Rate %', 'N/A')}%")

        # --- Indian Market Snapshot ---
        # --- Indian Market Snapshot ---
    st.header("🇮🇳 Indian Market Indicators")

    # The orchestrator will return all Indian data under one key
    india_data = overview_data.get("india_indicators", {})

    if "Error" in india_data:
        st.error(f"Could not retrieve Indian market data: {india_data['Error']}")
    else:
        # --- Display the Timestamp first ---
        # This will be right-aligned and subtle, providing clear context.
        timestamp = india_data.get("Data Timestamp", "Not available")
        st.markdown(f"<p style='text-align: right; color: grey; font-size: 0.9em;'>As of: {timestamp}</p>", unsafe_allow_html=True)

        # --- Row 1: Headline Indices ---
        st.subheader("Indices")
        cols = st.columns(2)
        cols[0].metric(
            label="Nifty 50",
            value=india_data.get("Nifty 50", "N/A"),
            delta=india_data.get("Nifty 50 Change", "N/A")
        )
        cols[1].metric(
            label="BSE Sensex",
            value=india_data.get("Sensex", "N/A"),
            delta=india_data.get("Sensex Change", "N/A")
        )

        st.divider()

        # --- Row 2: Market Internals (Breadth) ---
        st.subheader("Market Internals (Nifty 500)")
        cols = st.columns(4)
        
        # Market Status Display
        market_status = india_data.get("NSE Market Status", "Unknown")
        status_color = "green" if "open" in market_status.lower() else "red"
        status_icon = "🟢" if "open" in market_status.lower() else "🔴"
        cols[0].markdown(f"**Status:** <span style='color:{status_color};'>**{status_icon} {market_status}**</span>", unsafe_allow_html=True)
        
        # Advances, Declines, and Ratio
        cols[1].metric(label="Advances 👍", value=india_data.get("NSE Advances", "N/A"))
        cols[2].metric(label="Declines 👎", value=india_data.get("NSE Declines", "N/A"))
        cols[3].metric(label="Adv/Dec Ratio", value=india_data.get("NSE Adv/Dec Ratio", "N/A"))