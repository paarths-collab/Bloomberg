# File: pages/Results.py
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sys
from pathlib import Path

# --- Crucial: Add the project's root directory to Python's path ---
sys.path.append(str(Path(__file__).parent.parent))
from utils.portfolio_engine import run_portfolio_backtest, get_benchmark_data, calculate_portfolio_metrics

st.set_page_config(page_title="Results Dashboard", layout="wide")
st.title("📈 Portfolio Results Dashboard")

if 'portfolio_config' not in st.session_state:
    st.warning("Please build a portfolio from the 'Combination Builder' page first.")
    st.stop()

config = st.session_state['portfolio_config']

with st.spinner("Building and evaluating your custom portfolio..."):
    portfolio_df, metrics, errors = run_portfolio_backtest(
        selections=config['selections'], start_date=config['start_date'],
        end_date=config['end_date'], initial_capital=config['initial_capital']
    )
    if errors:
        for error in errors:
            st.error(error) # Display any non-fatal errors from the engine

    benchmark_df = get_benchmark_data("SPY", config['start_date'], config['end_date'], config['initial_capital'])
    benchmark_metrics = calculate_portfolio_metrics(benchmark_df['Equity_Curve'], config['start_date'], config['end_date'])

if not portfolio_df.empty:
    st.header("Performance Overview")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Your Portfolio")
        st.json(metrics)
    with col2:
        st.markdown("#### Benchmark (SPY)")
        st.json(benchmark_metrics)

    st.header("Equity Curve")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=portfolio_df.index, y=portfolio_df['Equity_Curve'], name='Portfolio', line=dict(color='purple', width=3)))
    fig.add_trace(go.Scatter(x=benchmark_df.index, y=benchmark_df['Equity_Curve'], name='Benchmark (SPY)', line=dict(color='grey', dash='dot')))
    fig.update_layout(title_text="Portfolio vs. Benchmark (SPY)", yaxis_title="Portfolio Value ($)")
    st.plotly_chart(fig, width='stretch', key="equity_curve_chart")

    st.header("Allocation")
    labels = [f"{s['name']} ({s['ticker']})" for s in config['selections'].values()]
    values = [s['weight'] * 100 for s in config['selections'].values()]
    pie_fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.4)])
    pie_fig.update_layout(title_text="Strategy & Ticker Allocation")
    st.plotly_chart(pie_fig, width='stretch', key="allocation_pie_chart")
else:
    st.error("The portfolio backtest failed to produce any valid results.")
# File: pages/3_📈_Results.py
# import streamlit as st
# import pandas as pd
# import numpy as np
# import plotly.graph_objects as go
# import yfinance as yf

# # --- Step 1: Import all standardized strategy run functions ---
# from breakout_strategy import run as run_breakout
# from channel_trading import run as run_channel_trading
# from ema_crossover import run as run_ema_crossover
# from macd_strategy import run as run_macd_strategy
# from mean_inversion import run as run_mean_inversion
# from momentum_strategy import run as run_momentum_strategy
# from pairs_trading import run as run_pairs_trading
# from pullback_fibonacci import run as run_pullback_fibonacci
# from reversal_strategy import run as run_reversal_strategy
# from rsi_strategy import run as run_rsi_strategy
# from sma_crossover import run as run_sma_crossover
# from support_resistance import run as run_support_resistance

# # --- Step 2: Create the strategy mapping ---
# STRATEGY_MAPPING = {
#     "Breakout Strategy": run_breakout, "Channel Trading": run_channel_trading,
#     "EMA Crossover": run_ema_crossover, "MACD Strategy": run_macd_strategy,
#     "Mean Reversion": run_mean_inversion, "Momentum Strategy": run_momentum_strategy,
#     "Pairs Trading": run_pairs_trading, "Fibonacci Pullback": run_pullback_fibonacci,
#     "RSI Reversal": run_reversal_strategy, "RSI Momentum": run_rsi_strategy,
#     "SMA Crossover": run_sma_crossover, "Support/Resistance": run_support_resistance,
# }

# # --- Step 3: Self-Contained Backtesting Engine and Metric Functions ---
# def get_benchmark_data(ticker, start, end, initial_capital):
#     df = yf.download(ticker, start=start, end=end, progress=False)
#     df['Returns'] = df['Close'].pct_change()
#     df['Equity_Curve'] = initial_capital * (1 + df['Returns']).cumprod()
#     return df

# def calculate_portfolio_metrics(equity_curve, start_date, end_date):
#     if equity_curve is None or equity_curve.empty: return {}
#     days = (pd.to_datetime(end_date) - pd.to_datetime(start_date)).days
#     years = max(days / 365.25, 1/52) # Ensure years is not zero
#     initial_capital = equity_curve.iloc[0]
#     final_equity = equity_curve.iloc[-1]
#     total_return_pct = (final_equity / initial_capital - 1) * 100
#     cagr = ((final_equity / initial_capital) ** (1 / years) - 1) * 100
#     daily_returns = equity_curve.pct_change().dropna()
#     if daily_returns.empty or daily_returns.std() == 0:
#         sharpe_ratio, annual_volatility = 0.0, 0.0
#     else:
#         annual_volatility = daily_returns.std() * np.sqrt(252) * 100
#         sharpe_ratio = (daily_returns.mean() * 252) / (daily_returns.std() * np.sqrt(252))
#     peak = equity_curve.cummax()
#     drawdown = (equity_curve - peak) / peak
#     max_drawdown_pct = drawdown.min() * 100
#     return {
#         "Total Return %": f"{total_return_pct:.2f}", "CAGR %": f"{cagr:.2f}",
#         "Annual Volatility %": f"{annual_volatility:.2f}", "Sharpe Ratio": f"{sharpe_ratio:.2f}",
#         "Max Drawdown %": f"{max_drawdown_pct:.2f}",
#     }

# def run_portfolio_backtest(selections, start_date, end_date, initial_capital):
#     all_equity_curves = {}
#     for key, params in selections.items():
#         strategy_name = params['name']
#         run_func = STRATEGY_MAPPING[strategy_name]
#         run_params = {"start_date": start_date, "end_date": end_date, "initial_capital": initial_capital, **params['params']}
#         if strategy_name == "Pairs Trading":
#             tickers = [t.strip().upper() for t in params["ticker"].split(",")]
#             if len(tickers) != 2:
#                 st.error(f"Pairs Trading requires exactly two tickers for '{key}'. Skipping.")
#                 continue
#             run_params["tickers"] = tickers
#         else:
#             run_params["ticker"] = params["ticker"]
        
#         results = run_func(**run_params)
#         if "Error" in results.get("summary", {}) or results.get("data", pd.DataFrame()).empty:
#             st.error(f"Backtest for {strategy_name} on {params['ticker']} failed. Skipping.")
#             continue
#         all_equity_curves[key] = {"equity": results["data"]['Equity_Curve'], "weight": params['weight']}

#     if not all_equity_curves: return pd.DataFrame(), {}
#     portfolio_df = pd.DataFrame()
#     for key, data in all_equity_curves.items():
#         strategy_returns = data['equity'].pct_change().fillna(0)
#         portfolio_df[f'{key}_weighted_returns'] = strategy_returns * data['weight']
#     portfolio_df['Total_Returns'] = portfolio_df.sum(axis=1)
#     portfolio_df['Equity_Curve'] = (1 + portfolio_df['Total_Returns']).cumprod() * initial_capital
#     portfolio_df.iloc[0]['Equity_Curve'] = initial_capital
#     metrics = calculate_portfolio_metrics(portfolio_df['Equity_Curve'], start_date, end_date)
#     return portfolio_df, metrics

# # --- Main Page Logic ---
# st.set_page_config(page_title="Results Dashboard", layout="wide")
# st.title("📈 Portfolio Results Dashboard")

# if 'portfolio_config' not in st.session_state:
#     st.warning("Please build and run a portfolio from the 'Portfolio Builder' page first.")
#     st.stop()

# config = st.session_state['portfolio_config']

# with st.spinner("Building and evaluating your custom portfolio... This may take a moment."):
#     portfolio_df, metrics = run_portfolio_backtest(
#         selections=config['selections'],
#         start_date=config['start_date'],
#         end_date=config['end_date'],
#         initial_capital=config['initial_capital']
#     )
#     benchmark_df = get_benchmark_data("SPY", config['start_date'], config['end_date'], config['initial_capital'])
#     benchmark_metrics = calculate_portfolio_metrics(benchmark_df['Equity_Curve'], config['start_date'], config['end_date'])

# if not portfolio_df.empty:
#     st.header("Performance Overview")
#     col1, col2 = st.columns(2)
#     with col1:
#         st.markdown("#### Your Portfolio")
#         st.json(metrics)
#     with col2:
#         st.markdown("#### Benchmark (SPY)")
#         st.json(benchmark_metrics)

#     st.header("Equity Curve")
#     fig = go.Figure()
#     fig.add_trace(go.Scatter(x=portfolio_df.index, y=portfolio_df['Equity_Curve'], name='Portfolio', line=dict(color='purple', width=3)))
#     fig.add_trace(go.Scatter(x=benchmark_df.index, y=benchmark_df['Equity_Curve'], name='Benchmark (SPY)', line=dict(color='grey', dash='dot')))
#     fig.update_layout(title_text="Portfolio vs. Benchmark (SPY)", yaxis_title="Portfolio Value ($)", legend_title_text='Legend')
#     st.plotly_chart(fig, use_container_width=True)

#     st.header("Allocation")
#     labels = [f"{s['name']} ({s['ticker']})" for s in config['selections'].values()]
#     values = [s['weight'] * 100 for s in config['selections'].values()]
#     pie_fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.4, pull=[0.05]*len(values))])
#     pie_fig.update_layout(title_text="Strategy & Ticker Allocation")
#     st.plotly_chart(pie_fig, use_container_width=True)
# else:
#     st.error("The portfolio backtest failed to produce results. Please check the individual strategy configurations and ticker symbols.")

# import streamlit as st
# import pandas as pd
# import plotly.express as px
# from utils import portfolio_engine, risk_metrics

# st.set_page_config(page_title="Results Dashboard", layout="wide")
# st.title("📈 Portfolio Results Dashboard")

# # Check if the necessary data exists in the session state
# if 'portfolio_config' not in st.session_state or 'orchestrator' not in st.session_state:
#     st.warning("Please build and run a portfolio from the 'Combination Builder' page first.")
#     st.stop()

# config = st.session_state['portfolio_config']
# orchestrator = st.session_state['orchestrator']

# # --- DEFINITIVE FIX IS HERE ---

# # 1. Extract all the required arguments explicitly from the config dictionary.
# #    Use .get() for safety, providing default values where appropriate.
# tickers = config.get("tickers", [])
# market = config.get("market", "us")
# start_date = config.get("start_date", "2022-01-01")
# end_date = config.get("end_date", "2024-01-01")

# # 2. This is the crucial step: Extract the nested dictionary of strategy settings.
# #    The key in your config file is 'strategies', but the function needs an argument
# #    named 'strategies_config'. We perform that mapping here.
# strategies_config = config.get("strategies", {})

# # 3. Call the function with the correctly named keyword arguments.
# with st.spinner(f"Building and evaluating your custom portfolio on {tickers}..."):
#     if not tickers or not strategies_config:
#         st.error("No tickers or strategies were selected in the configuration.")
#         st.stop()
        
#     results = portfolio_engine.build_portfolio(
#         orchestrator=orchestrator,
#         tickers=tickers,
#         market=market,
#         start_date=start_date,
#         end_date=end_date,
#         strategies_config=strategies_config # Pass the correct argument here
#     )
# # --- END OF FIX ---


# # Check for errors and display results
# if results.get("error"):
#     st.error(f"Backtest failed: {results['error']}")
# elif 'equity_curve' not in results or 'metrics' not in results:
#      st.warning("The backtest ran but did not produce any valid results. This can happen if no trades were made. Please try different parameters or a longer time frame.")
# else:
#     equity_curve = results['equity_curve']
#     metrics = results['metrics']
#     weights = results['weights']
#     currency = results.get('currency_symbol', '$')
#     benchmark = results.get('benchmark', 'SPY')
    
#     st.header(f"Performance on {', '.join(tickers)} vs. Benchmark ({benchmark})")
    
#     tab1, tab2 = st.tabs(["🛍️ Retail View", "🏦 Institutional View"])

#     with tab1:
#         st.subheader("Key Performance Metrics")
#         retail_metrics = metrics.get('retail', {})
#         cols = st.columns(3)
#         cols[0].metric("CAGR (%)", retail_metrics.get("CAGR (%)"))
#         cols[1].metric("Max Drawdown (%)", retail_metrics.get("Max Drawdown (%)"))
#         cols[2].metric("Sharpe Ratio", retail_metrics.get("Sharpe Ratio"))

#         st.subheader("Equity Curve")
#         fig_equity = px.line(equity_curve, title=f"Portfolio Growth (Initial Capital: {currency}100,000)")
#         fig_equity.update_layout(yaxis_title=f"Portfolio Value ({currency})", legend_title="Assets")
#         st.plotly_chart(fig_equity, use_container_width=True)
        
#         st.subheader("Strategy Weighting")
#         weights_df = pd.DataFrame(list(weights.items()), columns=['Strategy', 'Weight (%)'])
#         fig_pie = px.pie(weights_df, values='Weight (%)', names='Strategy', title='Portfolio Strategy Allocation')
#         st.plotly_chart(fig_pie, use_container_width=True)

#     with tab2:
#         st.subheader("Institutional Risk & Performance Metrics")
#         inst_metrics = metrics.get('institutional', {})
#         st.table(pd.DataFrame(list(inst_metrics.items()), columns=['Metric', 'Value']))
        
#         st.subheader("Generate Full Professional Report")
#         if st.button("📥 Generate and Download HTML Report"):
#             report_file = "portfolio_report.html"
#             benchmark_returns = risk_metrics.get_benchmark_returns(symbol=benchmark, start=start_date, end=end_date)
#             # Use the 'Portfolio' column from the equity curve for the report
#             portfolio_returns = equity_curve['Portfolio'].pct_change()
#             risk_metrics.generate_quantstats_report(portfolio_returns, benchmark_returns=benchmark_returns, output_file=report_file)
            
#             with open(report_file, "rb") as file:
#                 st.download_button("Download Report", data=file, file_name=report_file, mime="text/html")

# import streamlit as st
# import pandas as pd
# import plotly.express as px
# from utils import portfolio_engine, risk_metrics

# st.set_page_config(page_title="Results Dashboard", layout="wide")
# st.title("📈 Portfolio Results Dashboard")

# if 'portfolio_config' not in st.session_state or 'orchestrator' not in st.session_state:
#     st.warning("Please build and run a portfolio from the 'Combination Builder' page first.")
#     st.stop()

# config = st.session_state['portfolio_config']
# orchestrator = st.session_state['orchestrator']

# with st.spinner(f"Building and evaluating your custom portfolio on {config['tickers'][0]}..."):
#     results = portfolio_engine.build_portfolio(orchestrator=orchestrator, **config)

# if "error" in results:
#     st.error(f"Backtest failed: {results['error']}")
# else:
#     equity_curve = results['equity_curve']
#     metrics = results['metrics']
#     weights = results['weights']
#     currency = results['currency_symbol'] # <-- Get the currency
#     benchmark = results['benchmark'] # <-- Get the benchmark
    
#     st.header(f"Performance on {config['tickers'][0]} vs. Benchmark ({benchmark})")
    
#     tab1, tab2 = st.tabs(["🛍️ Retail View", "🏦 Institutional View"])

#     with tab1:
#         st.subheader("Key Performance Metrics")
#         retail_metrics = metrics.get('retail', {})
#         cols = st.columns(3); cols[0].metric("CAGR (%)", retail_metrics.get("CAGR (%)")); cols[1].metric("Max Drawdown (%)", retail_metrics.get("Max Drawdown (%)")); cols[2].metric("Sharpe Ratio", retail_metrics.get("Sharpe Ratio"))

#         st.subheader("Equity Curve")
#         fig_equity = px.line(equity_curve, title=f"Portfolio Growth (Initial Capital: {currency}100,000)")
#         fig_equity.update_layout(yaxis_title=f"Portfolio Value ({currency})", showlegend=False)
#         st.plotly_chart(fig_equity, use_container_width=True)
        
#         st.subheader("Strategy Weighting")
#         weights_df = pd.DataFrame(list(weights.items()), columns=['Strategy', 'Weight (%)'])
#         fig_pie = px.pie(weights_df, values='Weight (%)', names='Strategy', title='Portfolio Strategy Allocation')
#         st.plotly_chart(fig_pie, use_container_width=True)

#     with tab2:
#         st.subheader("Institutional Risk & Performance Metrics")
#         inst_metrics = metrics.get('institutional', {})
#         st.table(pd.DataFrame(list(inst_metrics.items()), columns=['Metric', 'Value']))
        
#         st.subheader("Generate Full Professional Report")
#         if st.button("📥 Generate and Download HTML Report"):
#             report_file = "portfolio_report.html"
#             benchmark_returns = risk_metrics.get_benchmark_returns(symbol=benchmark, start=config['start_date'], end=config['end_date'])
#             risk_metrics.generate_quantstats_report(equity_curve.pct_change(), benchmark_returns=benchmark_returns, output_file=report_file)
            
#             with open(report_file, "rb") as file:
#                 st.download_button("Download Report", data=file, file_name=report_file, mime="text/html")