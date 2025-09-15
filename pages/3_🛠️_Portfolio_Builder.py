# File: pages/2_🛠️_Portfolio_Builder.py
import streamlit as st
import pandas as pd

# This list defines all the strategies that the user can choose from in the UI.
STRATEGY_NAMES = [
    "Breakout Strategy", "Channel Trading", "EMA Crossover", "MACD Strategy",
    "Mean Reversion", "Momentum Strategy", "Pairs Trading", "Fibonacci Pullback",
    "RSI Reversal", "RSI Momentum", "SMA Crossover", "Support/Resistance"
]

st.set_page_config(page_title="Portfolio Builder", layout="wide")
st.title("🛠️ Portfolio Builder")
st.markdown("Configure your custom multi-strategy portfolio. Your settings will be used to run a backtest on the Results page.")

# --- UI for Global Settings ---
with st.sidebar:
    st.header("⚙️ Global Configuration")
    start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
    end_date = st.date_input("End Date", pd.to_datetime("today"))
    initial_capital = st.number_input("Initial Capital", 1000, 10000000, 100000)

    st.header("⚖️ Strategy Selection & Allocation")
    
    selected_strategies = st.multiselect(
        "Choose strategies to combine:",
        options=sorted(STRATEGY_NAMES),
        default=["EMA Crossover", "Mean Reversion"]
    )
    
    selections = {}
    total_weight = 0

    # --- Main Loop to Dynamically Build the UI ---
    if not selected_strategies:
        st.warning("Please select at least one strategy.")
    else:
        for i, strategy in enumerate(selected_strategies):
            key = f"{strategy.replace(' ', '_')}_{i}"
            with st.expander(f"Configure: {strategy}", expanded=True):
                # Special UI for Pairs Trading (multiple tickers)
                if strategy == "Pairs Trading":
                    ticker = st.text_input("Ticker Pair (e.g., PEP,KO)", "PEP,KO", key=f"ticker_{key}")
                else:
                    ticker = st.text_input("Ticker Symbol", "AAPL", key=f"ticker_{key}")
                
                weight = st.slider("Allocation Weight (%)", 0, 100, int(100 / len(selected_strategies)), key=f"weight_{key}")
                
                params = {}
                # This block intelligently creates the correct UI sliders for each strategy
                if strategy == "EMA Crossover":
                    params['fast'] = st.slider("Fast EMA", 5, 100, 20, key=f"fast_{key}")
                    params['slow'] = st.slider("Slow EMA", 20, 200, 50, key=f"slow_{key}")
                elif strategy == "SMA Crossover":
                    params['short_window'] = st.slider("Short SMA", 5, 100, 50, key=f"fast_{key}")
                    params['long_window'] = st.slider("Long SMA", 20, 200, 100, key=f"slow_{key}")
                elif strategy == "MACD Strategy":
                    params['fast'] = st.slider("Fast Period", 5, 50, 12, key=f"fast_{key}")
                    params['slow'] = st.slider("Slow Period", 20, 100, 26, key=f"slow_{key}")
                    params['signal'] = st.slider("Signal Period", 5, 50, 9, key=f"signal_{key}")
                elif strategy == "Mean Reversion":
                    params['window'] = st.slider("Lookback Window", 10, 100, 20, key=f"window_{key}")
                    params['num_std'] = st.slider("Std. Deviations", 1.0, 3.0, 2.0, 0.1, key=f"std_{key}")
                elif strategy == "RSI Reversal":
                    params['lower_bound'] = st.slider("RSI Lower Bound", 10, 40, 30, key=f"lower_{key}")
                    params['upper_bound'] = st.slider("RSI Upper Bound", 60, 90, 70, key=f"upper_{key}")
                elif strategy == "RSI Momentum":
                    params['rsi_lower'] = st.slider("RSI Lower Threshold", 10, 45, 40, key=f"rsilower_{key}")
                    params['rsi_upper'] = st.slider("RSI Upper Threshold", 55, 90, 60, key=f"rsiupper_{key}")
                elif strategy in ["Breakout Strategy", "Channel Trading", "Momentum Strategy", "Fibonacci Pullback", "Support/Resistance"]:
                    param_name = "period" if strategy == "Channel Trading" else "lookback"
                    params[param_name] = st.slider("Lookback Period (days)", 10, 100, 20, key=f"lookback_{key}")
                elif strategy == "Pairs Trading":
                     params['lookback'] = st.slider("Lookback Period (days)", 10, 100, 30, key=f"lookback_{key}")
                     params['entry_z'] = st.slider("Entry Z-Score", 1.0, 3.0, 2.0, 0.1, key=f"zscore_{key}")
                
                selections[key] = {"name": strategy, "ticker": ticker, "weight": weight / 100.0, "params": params}
                total_weight += weight

        st.metric(label="Total Weight Allocated", value=f"{total_weight}%")

    # The button to trigger the process
    run_button = st.button("▶️ Run Portfolio Backtest", use_container_width=True, disabled=(total_weight != 100))

if run_button:
    if total_weight != 100:
        st.error("Total allocation weight must be exactly 100%. Please adjust the sliders.")
    else:
        # Save the complete configuration to session state
        st.session_state['portfolio_config'] = {
            "selections": selections,
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": initial_capital
        }
        st.success("Configuration saved! Navigating to the Results Dashboard...")
        # Automatically switch the user to the results page
        st.switch_page("pages/3_📈_Results.py")