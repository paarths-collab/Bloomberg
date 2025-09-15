 # File: pages/Combination_Builder.py
# File: pages/Combination_Builder.py
import streamlit as st
import pandas as pd
import sys
from pathlib import Path

# --- Crucial: Add the project's root directory to Python's path ---
sys.path.append(str(Path(__file__).parent.parent))

st.set_page_config(page_title="Combination Builder", layout="wide")
st.title("🛠️ Portfolio Builder")
st.markdown("Configure your custom multi-strategy portfolio.")

# --- Professional, Cached Data Loading Functions ---
@st.cache_data
def load_stock_list(market_name):
    """Loads a stock list CSV and prepares it for display."""
    filename = "us_stocks.csv" if market_name == "US" else "nifty500.csv"
    try:
        project_root = Path(__file__).parent.parent
        file_path = project_root / "data" / filename
        df = pd.read_csv(file_path)
        df['Display'] = df['Company Name'] + " (" + df['Symbol'] + ")"
        return df.sort_values("Company Name")
    except FileNotFoundError:
        st.error(f"CRITICAL ERROR: '{filename}' not found in the 'data' folder. Please create it.")
        return None

# --- Load data once at the start ---
us_stocks_df = load_stock_list("US")
indian_stocks_df = load_stock_list("Indian")

STRATEGY_NAMES = [
    "Breakout Strategy", "Channel Trading", "EMA Crossover", "MACD Strategy",
    "Mean Reversion", "Momentum Strategy", "Pairs Trading", "Fibonacci Pullback",
    "RSI Reversal", "RSI Momentum", "SMA Crossover", "Support/Resistance"
]

# --- UI for Configuration ---
with st.sidebar:
    # --- SECTION 1: GLOBAL CONFIG ---
    st.header("1. Global Configuration")
    start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
    end_date = st.date_input("End Date", pd.to_datetime("today"))
    initial_capital = st.number_input("Initial Capital", 1000, 10000000, 100000)

    # --- SECTION 2: CENTRALIZED ASSET SELECTION ---
    st.header("2. Asset Selection")
    market = st.radio("Select Market", ["🇺🇸 US Market", "🇮🇳 Indian Market"], horizontal=True)
    
    primary_ticker = None
    if market == "🇺🇸 US Market" and us_stocks_df is not None:
        try:
            default_index = int(us_stocks_df[us_stocks_df['Symbol'] == 'AAPL'].index[0])
        except (IndexError, TypeError):
            default_index = 0
        selected_display = st.selectbox("Select Primary US Stock", options=us_stocks_df['Display'], index=default_index)
        if selected_display:
            primary_ticker = us_stocks_df[us_stocks_df['Display'] == selected_display]['Symbol'].iloc[0]
    elif market == "🇮🇳 Indian Market" and indian_stocks_df is not None:
        selected_display = st.selectbox("Select Primary Indian Stock", options=indian_stocks_df['Display'])
        if selected_display:
            primary_ticker = indian_stocks_df[indian_stocks_df['Display'] == selected_display]['Symbol'].iloc[0]
    else:
        primary_ticker = st.text_input("Primary Ticker Symbol", "AAPL")

    # --- SECTION 3: STRATEGY SELECTION & ALLOCATION ---
    st.header("3. Strategy Selection & Allocation")
    selected_strategies = st.multiselect("Choose strategies:", options=sorted(STRATEGY_NAMES), default=["EMA Crossover", "Mean Reversion"])
    
    selections = {}
    total_weight = 0

    if selected_strategies:
        for i, strategy in enumerate(selected_strategies):
            key = f"{strategy.replace(' ', '_')}_{i}"
            with st.expander(f"Configure: {strategy}", expanded=True):
                
                # --- Intelligent Ticker Override Logic ---
                if strategy == "Pairs Trading":
                    ticker_for_strategy = st.text_input("Ticker Pair (e.g., PEP,KO)", "PEP,KO", key=f"ticker_{key}")
                else:
                    ticker_for_strategy = primary_ticker
                    st.markdown(f"**Ticker:** `{ticker_for_strategy}` (from Asset Selection)")

                weight = st.slider("Weight (%)", 0, 100, int(100 / len(selected_strategies)), key=f"weight_{key}")
                params = {}
                # (All your dynamic UI parameter blocks for strategies go here - no changes needed)
                if strategy == "EMA Crossover":
                    params['fast'] = st.slider("Fast EMA", 5, 100, 20, key=f"fast_{key}")
                    params['slow'] = st.slider("Slow EMA", 20, 200, 50, key=f"slow_{key}")
                # ... Add all other elif blocks for strategy parameters ...

                if ticker_for_strategy:
                    selections[key] = {"name": strategy, "ticker": ticker_for_strategy, "weight": weight / 100.0, "params": params}
                    total_weight += weight

        st.metric(label="Total Weight", value=f"{total_weight}%")

    run_button = st.button("▶️ Run & View Results", use_container_width=True, disabled=(total_weight != 100))

if run_button:
    st.session_state['portfolio_config'] = {
        "selections": selections, "start_date": start_date,
        "end_date": end_date, "initial_capital": initial_capital
    }
    st.success("Configuration saved! Switching to Results page...")
    st.switch_page("pages/4_📈_Results.py")
# import streamlit as st
# import pandas as pd
# import sys
# from pathlib import Path

# # --- Crucial: Add the project's root directory to Python's path ---
# # This allows this script to find the 'utils', 'strategies', and 'data' folders.
# sys.path.append(str(Path(__file__).parent.parent))

# st.set_page_config(page_title="Combination Builder", layout="wide")
# st.title("🛠️ Portfolio Builder")
# st.markdown("Configure your custom multi-strategy portfolio.")

# # --- Professional, Cached Data Loading Functions ---
# @st.cache_data
# def load_stock_list(market_name):
#     """Loads a stock list CSV and prepares it for display."""
#     filename = "us_stocks.csv" if market_name == "US" else "nifty500.csv"
#     try:
#         # Build a robust path to the data file
#         project_root = Path(__file__).parent.parent
#         file_path = project_root / "data" / filename
#         df = pd.read_csv(file_path)
#         # Create a user-friendly display column
#         df['Display'] = df['Company Name'] + " (" + df['Symbol'] + ")"
#         return df.sort_values("Company Name")
#     except FileNotFoundError:
#         st.error(f"CRITICAL ERROR: '{filename}' not found in the 'data' folder.")
#         return None

# # --- Load data once at the start ---
# us_stocks_df = load_stock_list("US")
# indian_stocks_df = load_stock_list("Indian")

# STRATEGY_NAMES = [
#     "Breakout Strategy", "Channel Trading", "EMA Crossover", "MACD Strategy",
#     "Mean Reversion", "Momentum Strategy", "Pairs Trading", "Fibonacci Pullback",
#     "RSI Reversal", "RSI Momentum", "SMA Crossover", "Support/Resistance"
# ]

# # --- UI for Configuration ---
# with st.sidebar:
#     st.header("⚙️ Global Configuration")
#     market = st.radio("Select Market", ["🇺🇸 US Market", "🇮🇳 Indian Market"], horizontal=True)
#     start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#     end_date = st.date_input("End Date", pd.to_datetime("today"))
#     initial_capital = st.number_input("Initial Capital", 1000, 10000000, 100000)

#     st.header("⚖️ Strategy Selection & Allocation")
#     selected_strategies = st.multiselect("Choose strategies:", options=sorted(STRATEGY_NAMES), default=["EMA Crossover", "Mean Reversion"])
    
#     selections = {}
#     total_weight = 0

#     if selected_strategies:
#         for i, strategy in enumerate(selected_strategies):
#             key = f"{strategy.replace(' ', '_')}_{i}"
#             with st.expander(f"Configure: {strategy}", expanded=True):
                
#                 # --- NEW: Dynamic Stock Selector Logic ---
#                 ticker = None
#                 if strategy == "Pairs Trading":
#                     ticker = st.text_input("Ticker Pair (e.g., PEP,KO)", "PEP,KO", key=f"ticker_{key}")
#                 elif market == "🇺🇸 US Market" and us_stocks_df is not None:
#                     # Set a default value for better UX
#                     try:
#                         default_index = int(us_stocks_df[us_stocks_df['Symbol'] == 'AAPL'].index[0])
#                     except (IndexError, TypeError):
#                         default_index = 0 # Fallback if AAPL not found
#                     selected_display = st.selectbox("Search for a US Stock", options=us_stocks_df['Display'], index=default_index, key=f"ticker_{key}")
#                     if selected_display:
#                         ticker = us_stocks_df[us_stocks_df['Display'] == selected_display]['Symbol'].iloc[0]
#                 elif market == "🇮🇳 Indian Market" and indian_stocks_df is not None:
#                     selected_display = st.selectbox("Search for an Indian Stock", options=indian_stocks_df['Display'], key=f"ticker_{key}")
#                     if selected_display:
#                         ticker = indian_stocks_df[indian_stocks_df['Display'] == selected_display]['Symbol'].iloc[0]
#                 else:
#                     # Fallback to text input if data files are missing
#                     ticker = st.text_input("Ticker Symbol", "AAPL", key=f"ticker_{key}")

#                 weight = st.slider("Weight (%)", 0, 100, int(100 / len(selected_strategies)), key=f"weight_{key}")
#                 params = {}
#                 # (All your dynamic UI parameter blocks for strategies go here - no changes needed)
#                 if strategy == "EMA Crossover":
#                     params['fast'] = st.slider("Fast EMA", 5, 100, 20, key=f"fast_{key}")
#                     params['slow'] = st.slider("Slow EMA", 20, 200, 50, key=f"slow_{key}")
#                 # ... Add all other elif blocks for strategy parameters ...

#                 if ticker: # Only add to selections if a ticker was successfully chosen
#                     selections[key] = {"name": strategy, "ticker": ticker, "weight": weight / 100.0, "params": params}
#                     total_weight += weight

#         st.metric(label="Total Weight", value=f"{total_weight}%")

#     run_button = st.button("▶️ Run & View Results", use_container_width=True, disabled=(total_weight != 100))

# if run_button:
#     st.session_state['portfolio_config'] = {
#         "selections": selections, "start_date": start_date,
#         "end_date": end_date, "initial_capital": initial_capital
#     }
#     st.success("Configuration saved! Switching to Results page...")
#     st.switch_page("pages/4_📈_Results.py")
# import streamlit as st
# import sys
# import pathlib
# import pandas as pd
# from pathlib import Path

# sys.path.append(str(pathlib.Path(__file__).parent.parent))
# from agents.orchestrator import Orchestrator

# st.set_page_config(page_title="Combination Builder", layout="wide")

# @st.cache_resource
# def load_orchestrator():
#     config_path = "quant-company-insights-agent/config.yaml"
#     return Orchestrator.from_file(config_path)

# # --- NEW: Function to load US stocks ---
# @st.cache_data
# def load_us_stock_list():
#     """Loads the US stock list for the dropdown selector."""
#     try:
#         project_root = Path(__file__).parent.parent
#         us_file_path = project_root / "data" / "us_stocks.csv"
#         df = pd.read_csv(us_file_path)
#         df['Display'] = df['Company Name'] + " (" + df['Symbol'] + ")"
#         return df.sort_values("Company Name")
#     except FileNotFoundError:
#         st.error("CRITICAL ERROR: 'us_stocks.csv' not found.")
#         return None

# @st.cache_data
# def load_nse_stock_list():
#     try:
#         project_root = Path(__file__).parent.parent
#         nse_file_path = project_root / "data" / "nifty500.csv"
#         df = pd.read_csv(nse_file_path)
#         df['Display'] = df['Company Name'] + " (" + df['Symbol'] + ")"
#         return df.sort_values("Company Name")
#     except FileNotFoundError:
#         st.error("CRITICAL ERROR: 'nifty500.csv' not found.")
#         return None

# orchestrator = load_orchestrator()
# nse_stocks_df = load_nse_stock_list()
# us_stocks_df = load_us_stock_list() # <-- Load the new data
# st.session_state['orchestrator'] = orchestrator

# st.title("🔄 Strategy Combination Builder")
# st.markdown("Select a market, choose a stock, build your strategy portfolio, and run a professional-grade backtest.")

# with st.sidebar:
#     st.header("Portfolio Configuration")
    
#     market = st.radio("Select Market", ["🇺🇸 US", "🇮🇳 India (NSE)"], horizontal=True)
    
#     # --- THIS IS THE NEW SYMMETRICAL LOGIC ---
#     ticker = None
#     if market == "🇮🇳 India (NSE)":
#         if nse_stocks_df is not None:
#             selected_stock = st.selectbox("Search for an NSE Stock", options=nse_stocks_df['Display'])
#             ticker = nse_stocks_df[nse_stocks_df['Display'] == selected_stock]['Symbol'].iloc[0]
#     else: # US Market
#         if us_stocks_df is not None:
#             try:
#                 default_index = int(us_stocks_df[us_stocks_df['Symbol'] == 'AAPL'].index[0])
#             except IndexError:
#                 default_index = 0  # fallback to first row if AAPL missing

#             selected_stock = st.selectbox(
#                 "Search for a US Stock",
#                 options=us_stocks_df['Display'],
#                 index=default_index
#             )
#             ticker = us_stocks_df[us_stocks_df['Display'] == selected_stock]['Symbol'].iloc[0]
#         else:
#             ticker = st.text_input("Enter Primary US Ticker for Backtest", "AAPL")

             
#     start_date = st.date_input("Start Date", pd.to_datetime("2020-01-01"))
#     end_date = st.date_input("End Date", pd.to_datetime("today"))
    
#     st.markdown("---")
    
#     available_strategies = sorted(list(orchestrator.short_term_modules.keys()))
#     selected_strategies = st.multiselect("Select Strategies to Combine", options=available_strategies, default=available_strategies[:2])
    
#     weights = []
#     if selected_strategies:
#         st.write("Set Strategy Weights:")
#         for strategy in selected_strategies:
#             weights.append(st.slider(f"Weight for {strategy} (%)", 0, 100, int(100/len(selected_strategies))))
    
#     run_button = st.button("▶️ Run Portfolio Backtest", use_container_width=True)

# if run_button and ticker:
#     if sum(weights) != 100:
#         st.error("Error: The sum of all weights must be exactly 100%.")
#     else:
#         st.session_state['portfolio_config'] = {
#             "tickers": [ticker],
#             "strategies": selected_strategies,
#             "weights": weights,
#             "start_date": str(start_date),
#             "end_date": str(end_date),
#             "market": "India" if market == "🇮🇳 India (NSE)" else "US"
#         }
#         st.success("Configuration saved! Navigating to the Results Dashboard...")
#         st.switch_page("pages/4_📈_Results.py")