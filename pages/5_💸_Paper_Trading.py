import streamlit as st
import sys
import pathlib
import pandas as pd
import os

sys.path.append(str(pathlib.Path(__file__).parent.parent))
from agents.orchestrator import Orchestrator

st.set_page_config(page_title="Paper Trading Terminal", layout="wide")
st.title("💸 Alpaca Paper Trading Terminal")

@st.cache_resource
def load_orchestrator():
    config_path = "quant-company-insights-agent/config.yaml"
    return Orchestrator.from_file(config_path)

orchestrator = load_orchestrator()

# --- Display Account Info and Positions ---
st.header("📋 Account Status")
with st.spinner("Fetching account information..."):
    info = orchestrator.execution_agent.get_account_info()
    if "error" in info:
        st.error(f"Could not fetch account info: {info['error']}")
    else:
        cols = st.columns(4)
        cols[0].metric("Equity", f"${info.get('equity'):,.2f}")
        cols[1].metric("Buying Power", f"${info.get('buying_power'):,.2f}")
        cols[2].metric("Cash", f"${info.get('cash'):,.2f}")
        status = info.get('status', 'UNKNOWN')
        cols[3].metric("Status", status)

st.header("📈 Open Positions")
with st.spinner("Fetching open positions..."):
    positions = orchestrator.execution_agent.get_open_positions()
    if positions and "error" in positions[0]:
        st.error(f"Could not fetch positions: {positions[0]['error']}")
    elif not positions:
        st.info("You have no open positions.")
    else:
        st.dataframe(pd.DataFrame(positions).set_index("Symbol"))

# --- Trade Execution Form ---
st.header("🛒 Place a Trade")
with st.form("trade_form"):
    col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
    ticker = col1.text_input("Ticker Symbol", "SPY")
    qty = col2.number_input("Quantity", min_value=0.01, value=1.0, step=0.01)
    side = col3.selectbox("Side", ["buy", "sell"])
    submitted = col4.form_submit_button("Submit Market Order")

    if submitted:
        with st.spinner(f"Submitting {side} order..."):
            result = orchestrator.execution_agent.submit_market_order(ticker, qty, side)
            if "error" in result:
                st.error(f"Order failed: {result['error']}")
            else:
                st.success("Order submitted successfully!")
                st.json(result)
                st.info("Note: It may take a moment for your positions to update.")