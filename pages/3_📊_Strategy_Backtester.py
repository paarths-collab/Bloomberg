import streamlit as st
import sys
import pathlib
import pandas as pd

# --- Path setup ---
sys.path.append(str(pathlib.Path(__file__).parent.parent))
from agents.orchestrator import Orchestrator
from utils.visualization import create_price_and_equity_chart # Import our professional charting utility
from utils.data_loader import get_company_snapshot # Import for currency detection

# --- Page Configuration ---
st.set_page_config(page_title="Strategy Backtester", layout="wide")
st.title("📊 Quantitative Strategy Backtester")

# --- Initialize Orchestrator ---
@st.cache_resource
def load_orchestrator():
    config_path = "quant-company-insights-agent/config.yaml"
    return Orchestrator.from_file(config_path)
orchestrator = load_orchestrator()

# --- Sidebar for User Input ---
with st.sidebar:
    st.header("⚙️ Configuration")
    
    # Mode selection
    mode = st.radio("Select View Mode", ["Compare All Strategies", "Detailed Strategy View"])
    
    tickers_input = st.text_input("Enter Tickers (comma-separated)", "AAPL,TCS")
    start_date = st.date_input("Start Date", pd.to_datetime("2023-01-01"))
    end_date = st.date_input("End Date", pd.to_datetime("today"))

    # Inputs specific to Detailed View
    selected_strategy_name = None
    if mode == "Detailed Strategy View":
        st.markdown("---")
        selected_strategy_name = st.selectbox(
            "Choose a Single Strategy to Analyze",
            options=sorted(list(orchestrator.short_term_modules.keys()))
        )

    run_button = st.button("🔬 Run Backtest", use_container_width=True)

# --- Main Panel for Displaying Results ---
if run_button:
    tickers = [t.strip().upper() for t in tickers_input.split(",")]
    
    if mode == "Compare All Strategies":
        st.header("🏆 Performance Comparison of All Strategies")
        with st.spinner(f"Running all short-term strategies on {tickers}... This may take time."):
            # Corrected: Removed the redundant .date() calls
            summary_df = orchestrator.run_short_term_analysis(tickers, str(start_date), str(end_date))
            
            st.subheader("Summary Table")
            st.dataframe(summary_df)

            st.subheader("Total Return % Comparison Chart")
            if not summary_df.empty and 'Return [%]' in summary_df.columns:
                # Import plotly express locally for this chart
                import plotly.express as px
                summary_df['Return [%]'] = pd.to_numeric(summary_df['Return [%]'], errors='coerce')
                fig = px.bar(summary_df, x='Strategy', y='Return [%]', color='Ticker',
                             barmode='group', title='Strategy Performance Comparison')
                st.plotly_chart(fig, use_container_width=True)

    elif mode == "Detailed Strategy View":
        st.header(f"🔍 Detailed View: *{selected_strategy_name}*")
        
        strategy_module = orchestrator.short_term_modules.get(selected_strategy_name)
        
        if not strategy_module:
            st.error(f"Strategy '{selected_strategy_name}' not found in Orchestrator.")
        else:
            # Run the selected strategy for each ticker and display results
            for ticker in tickers:
                st.subheader(f"Results for: {ticker}")
                with st.spinner(f"Running {selected_strategy_name} on {ticker}..."):
                    
                    # Corrected: Removed the redundant .date() calls
                    results = strategy_module.run(ticker, str(start_date), str(end_date))
                    summary = results.get("summary", {})
                    backtest_df = results.get("data", pd.DataFrame())
                    
                    # Extract trades from the backtesting stats object
                    trades_list = summary.get("_trades", pd.DataFrame()).to_dict('records')

                    if "Error" in summary:
                        st.error(summary["Error"])
                    else:
                        # Fetch currency symbol for the current ticker
                        snapshot = get_company_snapshot(ticker)
                        currency_symbol = snapshot.get("currencySymbol", "$")
                        
                        # Display KPI metrics
                        cols = st.columns(4)
                        cols[0].metric("Return [%]", f"{summary.get('Return [%]', 0):.2f}")
                        cols[1].metric("Sharpe Ratio", f"{summary.get('Sharpe Ratio', 0):.2f}")
                        cols[2].metric("Max Drawdown [%]", f"{summary.get('Max. Drawdown [%]', 0):.2f}")
                        cols[3].metric("# Trades", summary.get('# Trades', 0))

                        # Use our professional charting utility to create the plot
                        fig = create_price_and_equity_chart(backtest_df, trades_list, ticker, selected_strategy_name, currency_symbol)
                        st.plotly_chart(fig, use_container_width=True)
                        st.markdown("---")


# import streamlit as st
# import sys
# import pathlib
# import pandas as pd
# import plotly.graph_objects as go

# # --- Path setup ---
# sys.path.append(str(pathlib.Path(__file__).parent.parent))
# from agents.orchestrator import Orchestrator
# from utils.visualization import create_price_and_equity_chart # Import our professional charting utility

# # --- Page Configuration ---
# st.set_page_config(page_title="Strategy Backtester", layout="wide")
# st.title("📊 Quantitative Strategy Backtester")

# # --- Initialize Orchestrator ---
# @st.cache_resource
# def load_orchestrator():
#     config_path = "quant-company-insights-agent/config.yaml"
#     return Orchestrator.from_file(config_path)
# orchestrator = load_orchestrator()

# # --- Sidebar for User Input ---
# with st.sidebar:
#     st.header("⚙️ Configuration")
    
#     # Mode selection
#     mode = st.radio("Select View Mode", ["Compare All Strategies", "Detailed Strategy View"])
    
#     tickers_input = st.text_input("Enter Tickers (comma-separated)", "AAPL,TSLA")
#     start_date = st.date_input("Start Date", pd.to_datetime("2023-01-01"))
#     end_date = st.date_input("End Date", pd.to_datetime("today"))

#     # Inputs specific to Detailed View
#     selected_strategy_name = None
#     if mode == "Detailed Strategy View":
#         st.markdown("---")
#         selected_strategy_name = st.selectbox(
#             "Choose a Single Strategy to Analyze",
#             options=sorted(list(orchestrator.short_term_modules.keys()))
#         )

#     run_button = st.button("🔬 Run Backtest", use_container_width=True)

# # --- Main Panel for Displaying Results ---
# if run_button:
#     tickers = [t.strip().upper() for t in tickers_input.split(",")]
    
#     if mode == "Compare All Strategies":
#         st.header("🏆 Performance Comparison of All Strategies")
#         with st.spinner(f"Running all short-term strategies on {tickers}... This may take time."):
#             summary_df = orchestrator.run_short_term_analysis(tickers, str(start_date), str(end_date))
            
#             st.subheader("Summary Table")
#             st.dataframe(summary_df)

#             st.subheader("Total Return % Comparison Chart")
#             if not summary_df.empty and 'Total Return %' in summary_df.columns:
#                 # Import plotly express locally for this chart
#                 import plotly.express as px
#                 summary_df['Total Return %'] = pd.to_numeric(summary_df['Total Return %'], errors='coerce')
#                 fig = px.bar(summary_df, x='Strategy', y='Total Return %', color='Ticker',
#                              barmode='group', title='Strategy Performance Comparison')
#                 st.plotly_chart(fig, use_container_width=True)

#     elif mode == "Detailed Strategy View":
#         st.header(f"🔍 Detailed View: *{selected_strategy_name}*")
        
#         # Get the specific module to run
#         strategy_module = orchestrator.short_term_modules.get(selected_strategy_name)
        
#         if not strategy_module:
#             st.error(f"Strategy '{selected_strategy_name}' not found in Orchestrator.")
#         else:
#             # Run the selected strategy for each ticker and display results
#             for ticker in tickers:
#                 st.subheader(f"Results for: {ticker}")
#                 with st.spinner(f"Running {selected_strategy_name} on {ticker}..."):
                    
#                     # Each strategy's run() method returns {'summary': {}, 'data': df, 'trades': []}
#                     results = strategy_module.run(ticker, str(start_date), str(end_date))
#                     summary = results.get("summary", {})
#                     backtest_df = results.get("data", pd.DataFrame())
#                     trades_list = results.get("trades", [])

#                     if "Error" in summary:
#                         st.error(summary["Error"])
#                     else:
#                         # Display KPI metrics
#                         cols = st.columns(5)
#                         cols[0].metric("Total Return", f"{summary.get('Total Return %', 0)}%")
#                         cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', 0))
#                         cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', 0)}%")
#                         cols[3].metric("Win Rate", f"{summary.get('Win Rate %', 0)}%")
#                         cols[4].metric("Trades", summary.get('Number of Trades', 0))

#                         # --- THIS IS THE FIX FOR CHARTS ---
#                         # Use our professional charting utility to create the plot
#                         fig = create_price_and_equity_chart(backtest_df, trades_list, ticker, selected_strategy_name)
#                         st.plotly_chart(fig, use_container_width=True)
#                         st.markdown("---")