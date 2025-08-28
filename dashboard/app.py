# Interactive visualization
# (Streamlit/NiceGUI/FastAPI UI)
# dashboard/app.py
import streamlit as st
# dashboard/app.py
import sys, os
# add parent directory of dashboard to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# now import orchestrator from agents
from agents.orchestrator import Orchestrator
import pandas as pd
# --- Initialize orchestrator ---
st.set_page_config(page_title="QuantInsights Dashboard", layout="wide")
st.title("🚀 QuantInsights Multi-Perspective Dashboard")

# Load orchestrator
# In dashboard/app.py
import pathlib
from agents.orchestrator import Orchestrator

# --- NEW, ROBUST WAY ---
# 1. Get the path to the current script's directory (e.g., .../Boomerang/dashboard)
current_dir = pathlib.Path(__file__).parent

# 2. Get the project root directory (one level up from 'dashboard')
project_root = current_dir.parent

# 3. Construct the full, absolute path to the config file
config_path = project_root / "quant-company-insights-agent" / "config.yaml"

# 4. Load the orchestrator using the reliable path
orchestrator = Orchestrator.from_file(config_path)

# --- Now the rest of your dashboard code can run ---
# ticker_input = ...
# dashboard = orchestrator.build_dashboard(ticker_input)


# --- Sidebar for user input ---
st.sidebar.header("Settings")
# --- AFTER ---
ticker_input = st.sidebar.text_input(
    "Enter ticker symbol", 
    value=orchestrator.sets.get("default_ticker", "AAPL")
)


run_button = st.sidebar.button("Run Dashboard")

if run_button:
    with st.spinner(f"Fetching data for {ticker_input}..."):
        dashboard = orchestrator.build_dashboard(ticker_input)

    # --- Fundamental Analysis ---
    st.subheader("📊 Fundamental Analysis")
    fundamentals = dashboard.get("Fundamental Analysis", pd.DataFrame()) # Use .get()
    st.table(fundamentals)

    # --- Insider Activity ---
    st.subheader("📝 Insider Activity")
    insider = dashboard.get("Insider Activity", pd.DataFrame()) # Use .get()
    st.table(insider.style.hide(axis="index"))

    # --- Macro Outlook ---
    st.subheader("🌎 Macro Outlook")
    macro = dashboard.get("Macro Outlook", pd.DataFrame()) # Use .get()
    st.table(macro.style.hide(axis="index"))

    # --- Social Sentiment ---
    st.subheader("💬 Social Sentiment")
    sentiment = dashboard.get("Social Sentiment", pd.DataFrame()) # Use .get()
    st.table(sentiment.style.hide(axis="index"))
   # In dashboard/app.py

    # --- Technical Signals ---
    st.subheader("📈 Technical Signals")
    tech = dashboard.get("Technical Signals", {}) # Use .get for safety

    # Display Metrics
    col1, col2 = st.columns(2)
    # In dashboard/app.py
    col1.metric(label="Previous Close", value=tech.get("Previous Close", "N/A"))
    col2.metric(label="Current Price", value=tech.get("Current Price", "N/A"))
    # Display Text-based Signals
    st.write(f"SMA Signal: {tech.get('SMA Signal', 'N/A')}")
    st.write(f"RSI State: {tech.get('RSI State', 'N/A')}")
    st.write(f"ATR Stop-Loss: {tech.get('ATR Stop-Loss', 'N/A')}")
    st.write(f"ATR Take-Profit: {tech.get('ATR Take-Profit', 'N/A')}")
    st.write(f"Headline Sentiment: {tech.get('Headline Sentiment', 'N/A')}")
    
    # Display Headlines
    st.write("Recent Headlines:")
    headlines = tech.get("Recent Headlines", []) # Use .get for safety
    if headlines:
        for h in headlines:
            st.write("•", h)
    else:
        st.write("No recent headlines found.")