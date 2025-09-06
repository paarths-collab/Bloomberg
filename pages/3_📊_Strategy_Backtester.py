# import streamlit as st
# import sys
# import pathlib
# import pandas as pd

# # --- Path setup ---
# sys.path.append(str(pathlib.Path(__file__).parent.parent))
# from agents.orchestrator import Orchestrator
# from utils.visualization import plot_backtest_comparison

# # --- Page Configuration ---
# st.set_page_config(page_title="Strategy Backtester", layout="wide")
# st.title("📊 Institutional Strategy Portfolio Backtester")

# # --- Load Orchestrator ---
# @st.cache_resource
# def load_orchestrator():
#     config_path = "../config.yaml"
#     return Orchestrator.from_file(config_path)

# orchestrator = load_orchestrator()

# # --- Professional Strategy Combination Mapping & Metadata ---
# STRATEGY_COMBINATIONS = {
#     "Balanced Alpha Generator": {
#         "modules": ["Momentum Strategy", "Rsi Strategy", "Pairs Trading", "Dca Investing"],
#         "type": "short_and_long",
#         "users": "Institutional Investors, Fund Managers",
#         "benefits": "Aims for risk-adjusted returns through diversification across different market dynamics."
#     },
#     "Trend & Reversion Hybrid": {
#         "modules": ["Ema Crossover", "Sma Crossover", "Reversal Strategy", "Support Resistance"],
#         "type": "short",
#         "users": "Professional Traders, Hedge Funds",
#         "benefits": "Designed to capture profits in both trending and range-bound market conditions."
#     },
#     "Trend Following Suite": {
#         "modules": ["Momentum Strategy", "Ema Crossover", "Breakout Strategy", "Channel Trading"],
#         "type": "short",
#         "users": "Active Traders, Momentum Funds",
#         "benefits": "Focuses on capitalizing on strong, sustained market trends for high return potential."
#     },
#     "Contrarian Value Hunter": {
#         "modules": ["Mean Inversion", "Rsi Strategy", "Pullback Fibonacci", "Value Investing"],
#         "type": "short_and_long",
#         "users": "Value Investors, Contrarian Funds",
#         "benefits": "Seeks to find undervalued assets by buying into oversold conditions and dips."
#     },
#     "Institutional Core Holdings": {
#         "modules": ["Index Etf Investing", "Dca Investing", "Dividend Investing", "Value Investing"],
#         "type": "long",
#         "users": "Pension Funds, Endowments, Family Offices",
#         "benefits": "A conservative portfolio focused on steady growth, income, and low volatility."
#     },
#     "Growth & Income Blend": {
#         "modules": ["Growth Investing", "Dividend Investing", "Dca Investing", "Value Investing"],
#         "type": "long",
#         "users": "Mutual Fund Managers, Retail Advisory",
#         "benefits": "A balanced approach aiming for both capital appreciation and income generation."
#     },
# }

# # --- Sidebar ---
# with st.sidebar:
#     st.header("⚙️ Configuration")
#     selected_combination = st.selectbox("Select a Strategy Portfolio", options=list(STRATEGY_COMBINATIONS.keys()))
    
#     tickers_input = st.text_input("Enter Tickers (comma-separated)", "AAPL,MSFT")
#     start_date = st.date_input("Start Date", pd.to_datetime("2023-01-01"))
#     end_date = st.date_input("End Date", pd.to_datetime("today"))

#     run_button = st.button("🔬 Run Portfolio Backtest", use_container_width=True)

# # --- Main Panel ---
# if run_button:
#     tickers = [t.strip().upper() for t in tickers_input.split(",")]
#     portfolio = STRATEGY_COMBINATIONS[selected_combination]
    
#     st.header(f"🏆 Analysis Results for: *{selected_combination}*")
#     st.info(f"**Target Users:** {portfolio['users']}\n\n**Benefits:** {portfolio['benefits']}")
    
#     all_summaries = []

#     with st.spinner(f"Running portfolio strategies on {tickers}..."):
#         # --- THIS IS THE FIX: We now loop through the specific modules ---
        
#         # Run short-term strategies if applicable
#         if portfolio['type'] in ["short", "short_and_long"]:
#             short_term_modules_to_run = {
#                 name: module for name, module in orchestrator.short_term_modules.items()
#                 if name in portfolio['modules']
#             }
#             for ticker in tickers:
#                 for name, module in short_term_modules_to_run.items():
#                     try:
#                         results = module.run(ticker, str(start_date.date()), str(end_date.date()))
#                         summary = results.get("summary", {})
#                         summary['Strategy'], summary['Ticker'] = name, ticker
#                         all_summaries.append(summary)
#                     except Exception as e:
#                         all_summaries.append({'Strategy': name, 'Ticker': ticker, 'Error': str(e)})

#         # Run long-term strategies if applicable
#         if portfolio['type'] in ["long", "short_and_long"]:
#             long_term_modules_to_run = {
#                 name: module for name, module in orchestrator.long_term_modules.items()
#                 if name in portfolio['modules']
#             }
#             for ticker in tickers:
#                 for name, module in long_term_modules_to_run.items():
#                     try:
#                         results = module.analyze(ticker)
#                         summary = results.get("summary", {})
#                         summary['Strategy'], summary['Ticker'] = name, ticker
#                         all_summaries.append(summary)
#                     except Exception as e:
#                         all_summaries.append({'Strategy': name, 'Ticker': ticker, 'Error': str(e)})

#     # Consolidate all results into a single DataFrame
#     summary_df = pd.DataFrame(all_summaries)

#     st.subheader("Performance Summary Table")
#     # Display a cleaned-up version of the results
#     display_cols = ['Strategy', 'Ticker', 'Return [%]', 'Sharpe Ratio', 'Max. Drawdown [%]', 'Win Rate [%]', '# Trades', 'Error']
#     # Filter for columns that actually exist in the dataframe
#     final_cols = [col for col in display_cols if col in summary_df.columns]
#     st.dataframe(summary_df[final_cols])

#     # Only show the performance chart for strategies that have a numeric return
#     chart_df = summary_df.copy()
#     if 'Return [%]' in chart_df.columns:
#         chart_df['Return [%]'] = pd.to_numeric(chart_df['Return [%]'], errors='coerce').fillna(0)
#         st.subheader("Total Return Comparison Chart")
#         fig = plot_backtest_comparison(chart_df)
#         st.plotly_chart(fig, use_container_width=True)


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