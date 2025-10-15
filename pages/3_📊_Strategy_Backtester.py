import streamlit as st
import sys
import pathlib
import pandas as pd
import numpy as np
from pathlib import Path

# --- Path setup ---
sys.path.append(str(pathlib.Path(__file__).parent.parent))
from agents.orchestrator import Orchestrator
from utils.visualization import create_strategy_specific_chart, create_performance_metrics_cards, visualize_strategy_performance, create_fibonacci_retracement_chart, create_pairs_trading_chart, create_rsi_strategy_chart, create_momentum_strategy_chart
from utils.data_loader import get_company_snapshot # Import for currency detection
from utils.risk_metrics import calculate_all_metrics, get_benchmark_returns

# --- Page Configuration ---
st.set_page_config(page_title="Strategy Backtester", layout="wide")
st.title("📊 Institutional-Grade Strategy Backtester")

# --- Initialize Orchestrator ---
@st.cache_resource
def load_orchestrator():
    config_path = "quant-company-insights-agent/config.yaml"
    return Orchestrator.from_file(config_path)
orchestrator = load_orchestrator()

# --- Cached Functions for Performance ---
@st.cache_data
def load_us_stock_list():
    """
    Loads and prepares the US stock list from us_stocks.csv
    for the searchable selectbox.
    """
    try:
        project_root = Path(__file__).parent.parent
        us_file_path = project_root / "data" / "us_stocks.csv"
        df = pd.read_csv(us_file_path)

        company_col = 'Company Name'
        symbol_col = 'Symbol'

        if company_col not in df.columns or symbol_col not in df.columns:
            st.error(f"CRITICAL ERROR: '{company_col}' or '{symbol_col}' not found in us_stocks.csv.")
            return None

        df['Display'] = df[company_col] + " (" + df[symbol_col] + ")"
        
        return df[[symbol_col, 'Display']].sort_values("Display")

    except FileNotFoundError:
        st.error("CRITICAL ERROR: 'us_stocks.csv' not found. Please ensure it is in the 'data/' folder.")
        return None

@st.cache_data
def load_nse_stock_list():
    """
    Loads and prepares the Nifty 500 stock list from nifty500.csv
    for the searchable selectbox.
    """
    try:
        project_root = Path(__file__).parent.parent
        nse_file_path = project_root / "data" / "nifty500.csv"
        df = pd.read_csv(nse_file_path)

        company_col = 'Company Name'
        symbol_col = 'Symbol'

        if company_col not in df.columns or symbol_col not in df.columns:
            st.error(f"CRITICAL ERROR: '{company_col}' or '{symbol_col}' not found in nifty500.csv.")
            return None

        df['Display'] = df[company_col] + " (" + df[symbol_col] + ")"
        
        return df[[symbol_col, 'Display']].sort_values("Display")

    except FileNotFoundError:
        st.error("CRITICAL ERROR: 'nifty500.csv' not found. Please ensure it is in the 'data/' folder.")
        return None

# --- Load stock lists ---
us_stocks_df = load_us_stock_list()
nse_stocks_df = load_nse_stock_list()

# --- Sidebar for User Input ---
with st.sidebar:
    st.header("⚙️ Configuration")
    
    # Mode selection
    mode = st.radio("Select View Mode", ["Compare All Strategies", "Detailed Strategy View"])
    
    # Market selection
    market = st.selectbox("Select Market", ["USA", "India"], index=0)
    
    # Stock selection based on market
    if market == "India" and nse_stocks_df is not None:
        selected_display = st.selectbox("Search for an NSE Stock", options=nse_stocks_df['Display'])
        if selected_display:
            tickers_input = nse_stocks_df[nse_stocks_df['Display'] == selected_display]['Symbol'].iloc[0] + ".NS"
        else:
            tickers_input = "RELIANCE.NS"  # Default fallback
    elif market == "USA" and us_stocks_df is not None:
        try:
            # Find the default index for AAPL
            default_index = int(us_stocks_df[us_stocks_df['Symbol'] == 'AAPL'].index[0])
        except (IndexError, TypeError):
            default_index = 0  # fallback to first row if AAPL missing
        selected_display = st.selectbox(
            "Search for a US Stock",
            options=us_stocks_df['Display'],
            index=default_index
        )
        if selected_display:
            tickers_input = us_stocks_df[us_stocks_df['Display'] == selected_display]['Symbol'].iloc[0]
        else:
            tickers_input = "AAPL"  # Default fallback
    else:
        # Fallback to text input if data files are not available
        tickers_input = st.text_input("Enter Tickers (comma-separated)", "AAPL")
    
    start_date = st.date_input("Start Date", pd.to_datetime("2023-01-01"))
    end_date = st.date_input("End Date", pd.to_datetime("today"))

    # Benchmark selection for comparison
    benchmark = st.selectbox("Select Benchmark", ["SPY", "QQQ", "IWM", "^NSEI", "^BSESN"], index=0)

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
    # Ensure tickers_input is always a string before processing
    ticker_str = str(tickers_input) if tickers_input else "AAPL"
    if ',' in ticker_str:
        tickers = [t.strip().upper() for t in ticker_str.split(",")]
    else:
        tickers = [ticker_str.upper()]
    
    if mode == "Compare All Strategies":
        st.header("🏆 Performance Comparison of All Strategies")
        with st.spinner(f"Running all short-term strategies on {tickers}... This may take time."):
            # Corrected: Removed the redundant .date() calls and added market parameter
            summary_df = orchestrator.run_short_term_analysis(tickers, str(start_date), str(end_date), market)
            
            st.subheader("Summary Table")
            st.dataframe(summary_df)

            # Enhanced visualization with multiple metrics
            if not summary_df.empty:
                import plotly.express as px
                
                # Prepare data for visualization
                if 'Return [%]' in summary_df.columns:
                    summary_df['Return [%]'] = pd.to_numeric(summary_df['Return [%]'], errors='coerce')
                
                if 'Sharpe Ratio' in summary_df.columns:
                    summary_df['Sharpe Ratio'] = pd.to_numeric(summary_df['Sharpe Ratio'], errors='coerce')
                
                if 'Max. Drawdown [%]' in summary_df.columns:
                    summary_df['Max. Drawdown [%]'] = pd.to_numeric(summary_df['Max. Drawdown [%]'], errors='coerce')
                
                if '# Trades' in summary_df.columns:
                    summary_df['# Trades'] = pd.to_numeric(summary_df['# Trades'], errors='coerce')
                
                # Create tabs for different metrics
                tab1, tab2, tab3, tab4 = st.tabs(["📊 Returns", "⚖️ Risk-Adjusted", "📉 Drawdowns", "📈 Activity"])
                
                with tab1:
                    if 'Return [%]' in summary_df.columns:
                        fig_return = px.bar(summary_df, x='Strategy', y='Return [%]', color='Ticker',
                                            barmode='group', title='Total Return % Comparison')
                        st.plotly_chart(fig_return, width='stretch')
                
                with tab2:
                    if 'Sharpe Ratio' in summary_df.columns:
                        fig_sharpe = px.bar(summary_df, x='Strategy', y='Sharpe Ratio', color='Ticker',
                                            barmode='group', title='Sharpe Ratio Comparison')
                        st.plotly_chart(fig_sharpe, width='stretch')
                
                with tab3:
                    if 'Max. Drawdown [%]' in summary_df.columns:
                        # Convert to positive values for visualization (since drawdowns are negative)
                        summary_df['Max. Drawdown (Abs) [%]'] = summary_df['Max. Drawdown [%]'].abs()
                        fig_drawdown = px.bar(summary_df, x='Strategy', y='Max. Drawdown (Abs) [%]', color='Ticker',
                                              barmode='group', title='Maximum Drawdown Comparison (Absolute Values)')
                        st.plotly_chart(fig_drawdown, width='stretch')
                
                with tab4:
                    if '# Trades' in summary_df.columns:
                        fig_trades = px.bar(summary_df, x='Strategy', y='# Trades', color='Ticker',
                                            barmode='group', title='Number of Trades Comparison')
                        st.plotly_chart(fig_trades, width='stretch')
                
                # Additional metrics comparison table
                st.subheader("Performance Metrics Overview")
                metric_cols = ['Strategy', 'Ticker', 'Return [%]', 'Sharpe Ratio', 'Max. Drawdown [%]', '# Trades']
                display_cols = [col for col in metric_cols if col in summary_df.columns]
                if display_cols:
                    st.dataframe(summary_df[display_cols].style.format({
                        'Return [%]': '{:.2f}%', 
                        'Sharpe Ratio': '{:.2f}', 
                        'Max. Drawdown [%]': '{:.2f}%', 
                        '# Trades': '{:.0f}'
                    }))

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
                    
                    # Get strategy results
                    results = strategy_module.run(ticker, str(start_date), str(end_date), market)
                    summary = results.get("summary", {})
                    backtest_df = results.get("data", pd.DataFrame())
                    trades_list = results.get("trades", [])
                    
                    if "Error" in summary:
                        st.error(summary["Error"])
                    else:
                        # Fetch currency symbol for the current ticker
                        snapshot = get_company_snapshot(ticker, market)
                        currency_symbol = snapshot.get("currencySymbol", "$")
                        
                        # Calculate additional metrics if returns data is available
                        returns = None
                        equity_col = None
                        if 'Equity_Curve' in backtest_df.columns:
                            equity_col = 'Equity_Curve'
                        elif 'Equity' in backtest_df.columns:
                            equity_col = 'Equity'
                        
                        if equity_col and len(backtest_df) > 1:
                            equity_data = backtest_df[equity_col]
                            returns = equity_data.pct_change().dropna()
                        
                        # Calculate comprehensive metrics
                        benchmark_returns = get_benchmark_returns(benchmark, str(start_date), str(end_date))
                        comprehensive_metrics = calculate_all_metrics(returns, benchmark_returns) if returns is not None else {}
                        
                        # Display KPI metrics in a structured layout
                        retail_metrics = comprehensive_metrics.get("retail", {})
                        institutional_metrics = comprehensive_metrics.get("institutional", {})
                        
                        # Create 4 metric cards in a row
                        metric1, metric2, metric3, metric4 = st.columns(4)
                        
                        # Total Return card
                        total_return = retail_metrics.get("Total Return %", 0)
                        metric1.metric(
                            label="📊 Total Return %",
                            value=f"{total_return:.2f}%" if pd.notna(total_return) else "N/A",
                            delta=f"{retail_metrics.get('CAGR %', 0):.2f}% CAGR"
                        )
                        
                        # Risk-adjusted return card
                        sharpe = retail_metrics.get("Sharpe Ratio", 0)
                        metric2.metric(
                            label="⚖️ Sharpe Ratio",
                            value=f"{sharpe:.2f}" if pd.notna(sharpe) else "N/A",
                            delta=f"{retail_metrics.get('Sortino Ratio', 0):.2f} Sortino" if pd.notna(retail_metrics.get('Sortino Ratio', 0)) else "N/A"
                        )
                        
                        # Max Drawdown card
                        max_dd = retail_metrics.get("Max Drawdown %", 0)
                        metric3.metric(
                            label="📉 Max Drawdown %",
                            value=f"{max_dd:.2f}%" if pd.notna(max_dd) else "N/A",
                            delta=f"{institutional_metrics.get('Volatility (ann.) %', 0):.2f}% Volatility"
                        )
                        
                        # Activity card
                        win_rate = retail_metrics.get("Win Rate %", 0)
                        trades = summary.get('# Trades', summary.get('Number of Trades', 0))
                        metric4.metric(
                            label="📈 Win Rate / Trades",
                            value=f"{win_rate:.1f}%" if pd.notna(win_rate) else "N/A",
                            delta=f"{trades} trades"
                        )
                        
                        # Create performance chart with strategy-specific visualization
                        strategy_lower = selected_strategy_name.lower()
                        
                        # Select the appropriate chart based on strategy type
                        if 'fibonacci' in strategy_lower or 'pullback' in strategy_lower:
                            fig = create_fibonacci_retracement_chart(backtest_df, trades_list, ticker, currency_symbol)
                        elif 'pairs' in strategy_lower:
                            fig = create_pairs_trading_chart(backtest_df, trades_list, ticker, currency_symbol)
                        elif 'rsi' in strategy_lower:
                            fig = create_rsi_strategy_chart(backtest_df, trades_list, ticker, currency_symbol)
                        elif 'momentum' in strategy_lower:
                            fig = create_momentum_strategy_chart(backtest_df, trades_list, ticker, currency_symbol)
                        else:
                            # Use the general strategy-specific chart
                            fig = create_strategy_specific_chart(backtest_df, trades_list, ticker, selected_strategy_name, currency_symbol)
                        
                        # Enhance chart title to be more strategy-specific
                        strategy_display_name = selected_strategy_name
                        if "EMA" in selected_strategy_name.upper():
                            fig.update_layout(title_text=f"{ticker} - {selected_strategy_name} (EMA-based)")
                        elif "SMA" in selected_strategy_name.upper():
                            fig.update_layout(title_text=f"{ticker} - {selected_strategy_name} (SMA-based)")
                        elif "RSI" in selected_strategy_name.upper():
                            fig.update_layout(title_text=f"{ticker} - {selected_strategy_name} (RSI-based)")
                        elif "MACD" in selected_strategy_name.upper():
                            fig.update_layout(title_text=f"{ticker} - {selected_strategy_name} (MACD-based)")
                        elif "BREAKOUT" in selected_strategy_name.upper():
                            fig.update_layout(title_text=f"{ticker} - {selected_strategy_name} (Breakout-based)")
                        elif "CHANNEL" in selected_strategy_name.upper():
                            fig.update_layout(title_text=f"{ticker} - {selected_strategy_name} (Channel-based)")
                        elif "MOMENTUM" in selected_strategy_name.upper():
                            fig.update_layout(title_text=f"{ticker} - {selected_strategy_name} (Momentum-based)")
                        elif "MEAN" in selected_strategy_name.upper() or "REVERSION" in selected_strategy_name.upper():
                            fig.update_layout(title_text=f"{ticker} - {selected_strategy_name} (Mean Reversion)")
                        elif "SUPPORT" in selected_strategy_name.upper() or "RESISTANCE" in selected_strategy_name.upper():
                            fig.update_layout(title_text=f"{ticker} - {selected_strategy_name} (Support/Resistance-based)")
                        elif "FIBONACCI" in selected_strategy_name.upper() or "PULLBACK" in selected_strategy_name.upper():
                            fig.update_layout(title_text=f"{ticker} - {selected_strategy_name} (Fibonacci-based)")
                        elif "PAIRS" in selected_strategy_name.upper():
                            fig.update_layout(title_text=f"{ticker} - {selected_strategy_name} (Pairs Trading)")
                        else:
                            fig.update_layout(title_text=f"{ticker} - {selected_strategy_name}")
                        
                        st.plotly_chart(fig, width='stretch')
                        
                        # Performance metrics breakdown in tabs
                        tab1, tab2, tab3 = st.tabs(["📊 Performance Metrics", "⚖️ Risk Metrics", "📈 Strategy Details"])
                        
                        with tab1:
                            st.subheader("Performance Metrics")
                            def format_metric_value(k, v):
                                try:
                                    # Handle pandas Series by getting the scalar value
                                    if hasattr(v, 'iloc'):
                                        v = v.iloc[0] if len(v) > 0 else 0
                                    val = float(v)
                                    return f"{val:.2f}%" if k.endswith('%') else f"{val:.2f}"
                                except (ValueError, TypeError):
                                    # If conversion fails, return the original value as string
                                    return str(v)
                            
                            perf_df = pd.DataFrame({
                                'Metric': list(retail_metrics.keys()),
                                'Value': [format_metric_value(k, v) for k, v in retail_metrics.items()]
                            })
                            st.dataframe(perf_df)
                        
                        with tab2:
                            st.subheader("Risk Metrics")
                            def format_metric_value(k, v):
                                try:
                                    # Handle pandas Series by getting the scalar value
                                    if hasattr(v, 'iloc'):
                                        v = v.iloc[0] if len(v) > 0 else 0
                                    val = float(v)
                                    return f"{val:.2f}%" if k.endswith('%') else f"{val:.2f}"
                                except (ValueError, TypeError):
                                    # If conversion fails, return the original value as string
                                    return str(v)
                            
                            risk_df = pd.DataFrame({
                                'Metric': list(institutional_metrics.keys()),
                                'Value': [format_metric_value(k, v) for k, v in institutional_metrics.items()]
                            })
                            st.dataframe(risk_df)
                        
                        with tab3:
                            # Add a brief strategy description
                            strategy_descriptions = {
                                "EMA Crossover": "Uses Exponential Moving Average crossovers to generate buy/sell signals",
                                "SMA Crossover": "Uses Simple Moving Average crossovers to generate buy/sell signals", 
                                "RSI Strategy": "Uses Relative Strength Index for overbought/oversold conditions",
                                "MACD Strategy": "Uses Moving Average Convergence Divergence for trend analysis",
                                "Momentum Strategy": "Captures price momentum for trend-following opportunities",
                                "Mean Reversion": "Assumes prices revert to their mean over time",
                                "Breakout Strategy": "Identifies and trades breakouts from established price ranges",
                                "Channel Trading": "Trades within established price channels using support and resistance",
                                "Support/Resistance": "Uses key support and resistance levels for trade entries",
                                "Reversal Strategy": "Looks for potential price reversals at key technical levels",
                                "Pullback Fibonacci": "Identifies pullback opportunities using Fibonacci ratios",
                                "Pairs Trading": "Uses statistical relationships between correlated assets",
                                "Dca Investing": "Dollar-cost averaging investment approach",
                                "Value Investing": "Focuses on fundamentally undervalued stocks",
                                "Growth Investing": "Targets companies with strong growth potential"
                            }
                            
                            if selected_strategy_name in strategy_descriptions:
                                st.info(f"**Strategy Approach**: {strategy_descriptions[selected_strategy_name]}")
                            
                            # Show trade details
                            if trades_list is not None and (isinstance(trades_list, pd.DataFrame) and not trades_list.empty) or (isinstance(trades_list, list) and len(trades_list) > 0):
                                st.subheader("Trade Details")
                                if isinstance(trades_list, list):
                                    trades_df = pd.DataFrame(trades_list)
                                else:
                                    trades_df = trades_list
                                if not trades_df.empty:
                                    st.dataframe(trades_df)
                        
                        st.markdown("---")