import streamlit as st
import sys
import pathlib
import pandas as pd
import plotly.express as px

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

    st.header("🇮🇳 Indian Market Indicators (from NSE)")
    if "Error" in india_data: st.error(india_data["Error"])
    else:
        cols = st.columns(4)
        market_status = india_data.get("NSE Market Status", "Unknown")
        status_color = "green" if market_status == "Open" else "red"
        cols[0].markdown(f"**Market Status:** <span style='color:{status_color};'>**{market_status}**</span>", unsafe_allow_html=True)
        cols[1].metric("Advances 👍", india_data.get("NSE Advances", "N/A"))
        cols[2].metric("Declines 👎", india_data.get("NSE Declines", "N/A"))
        cols[3].metric("Adv/Dec Ratio", india_data.get("NSE Adv/Dec Ratio", "N/A"))