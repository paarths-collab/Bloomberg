import streamlit as st
import pandas as pd
import sys
import os
import pathlib
import plotly.express as px
import matplotlib.pyplot as plt

# --- Path setup to allow importing from project directories ---
current_dir = pathlib.Path(__file__).parent
sys.path.append(str(current_dir))

# --- Import all strategy and analysis modules ---
# Long-Term Strategy Modules
from Long_Term_Strategy import value_investing, growth_investing, dividend_investing, dca_investing, index_etf_investing
# Short-Term Strategy Modules
from strategies import sma_crossover, ema_crossover, momentum_strategy, mean_inversion, rsi_strategy, reversal_strategy, breakout_strategy, channel_trading, custom_strategy, mcd_strategy, pullback_fibonacci, support_resistance, pairs_trading

# --- Page Configuration ---
st.set_page_config(page_title="Strategy Showcase", layout="wide")
st.title("📊 QuantInsights Strategy Showcase")
st.markdown("Select a strategy from the sidebar to run an individual analysis and see the results.")

# --- Strategy Registry ---
# Create a dictionary to hold all callable strategy functions
STRATEGY_REGISTRY = {
    # Long-Term
    "Value Investing": value_investing.analyze,
    "Growth Investing": growth_investing.analyze,
    "Dividend Investing": dividend_investing.analyze,
    "DCA Simulation": dca_investing.dca_investing,
    "Index/ETF Analysis": index_etf_investing.index_etf_investing,
    # Short-Term
    "SMA Crossover": sma_crossover.run,
    "EMA Crossover": ema_crossover.run,
    "Momentum": momentum_strategy.run,
    "Mean Reversion (Bollinger Bands)": mean_inversion.run,
    "RSI Momentum": rsi_strategy.run,
    "RSI Divergence Reversal": reversal_strategy.run,
    "Volume Breakout": breakout_strategy.run,
    "Channel Trading (Donchian)": channel_trading.run,
    "Custom (SMA + RSI)": custom_strategy.run,
    "MACD Crossover": mcd_strategy.run,
    "Fibonacci Pullback": pullback_fibonacci.run,
    "Support/Resistance Bounce": support_resistance.run,
    "Pairs Trading": pairs_trading.run,
}

# --- Sidebar for User Input ---
with st.sidebar:
    st.header("⚙️ Strategy Selector")
    
    selected_strategy_name = st.selectbox(
        "Choose a Strategy to Test",
        options=list(STRATEGY_REGISTRY.keys())
    )
    
    st.markdown("---")
    
    # Get the selected function from the registry
    selected_strategy_func = STRATEGY_REGISTRY[selected_strategy_name]
    
    # --- Dynamic Inputs based on Strategy ---
    st.header("Parameters")
    
    if selected_strategy_name == "Pairs Trading":
        ticker_input = st.text_input("Enter Ticker Pair (comma-separated)", "PEP,KO")
    elif selected_strategy_name == "Index/ETF Analysis":
        ticker_input = st.text_input("Enter ETF Ticker", "SPY")
    else:
        ticker_input = st.text_input("Enter Ticker", "AAPL")
        
    start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
    end_date = st.date_input("End Date", pd.to_datetime("today"))
    
    run_button = st.button("🔬 Run Test", use_container_width=True)

# --- Main Panel for Displaying Results ---
if run_button:
    st.header(f"Results for: *{selected_strategy_name}*")
    
    with st.spinner("Analyzing..."):
        # --- Execute the selected function with the correct parameters ---
        
        if selected_strategy_name == "Pairs Trading":
            tickers = [t.strip().upper() for t in ticker_input.split(",")]
            results = selected_strategy_func(tickers, str(start_date), str(end_date))
        elif selected_strategy_name == "DCA Simulation":
            # DCA is special, it plots itself
            st.subheader("DCA Simulation Chart")
            fig, ax = plt.subplots() # Create a matplotlib figure to capture the plot
            dca_investing.dca_investing(ticker_input, monthly_invest=1000, years=5, ax=ax) # Pass the axis
            st.pyplot(fig)
            results = None # Mark as handled
        elif selected_strategy_name == "Index/ETF Analysis":
    # Refactor the function to return data
            results = selected_strategy_func(ticker_input) 
            if results:
                st.subheader("Index/ETF Analysis Results")
        # Display the results in the UI
                st.json(results) 
            else:
                st.error("Could not retrieve Index/ETF Analysis data.")

        else: # All other short-term strategies
            results = selected_strategy_func(ticker_input, str(start_date), str(end_date))

        # --- Display the results ---
        if results:
            if "Error" in results:
                st.error(results["Error"])
            
            # Display for Long-Term historical data
            elif "historical_performance" in results:
                st.subheader("Current Metrics")
                st.json(results.get("current_metrics", {}))
                
                st.subheader("Historical Performance")
                df = pd.DataFrame(results["historical_performance"])
                st.dataframe(df)
                
                # Try to create a smart chart
                if not df.empty:
                    try:
                        id_vars = [col for col in ['Year', 'Period'] if col in df.columns]
                        value_vars = [col for col in df.columns if col not in id_vars]
                        fig = px.bar(df, x=id_vars[0], y=value_vars, barmode='group', title=f"{selected_strategy_name} History")
                        st.plotly_chart(fig, use_container_width=True)
                    except Exception as e:
                        st.warning(f"Could not automatically generate a chart: {e}")

            # Display for Short-Term backtest summaries
            else:
                st.subheader("Backtest Summary")
                st.json(results)