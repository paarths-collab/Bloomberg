import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- Core Strategy & Backtesting Logic ---

def get_data(ticker, start, end, interval='1d'):
    """Fetches historical price data."""
    df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
    if df.empty:
        return pd.DataFrame()
    return df[['Open', 'High', 'Low', 'Close', 'Volume']]

def generate_signals(df, fast=12, slow=26, signal=9):
    """Generates buy/sell signals based on the MACD indicator."""
    df = df.copy()
    df['ema_fast'] = df['Close'].ewm(span=fast, adjust=False).mean()
    df['ema_slow'] = df['Close'].ewm(span=slow, adjust=False).mean()
    df['macd'] = df['ema_fast'] - df['ema_slow']
    df['macd_signal'] = df['macd'].ewm(span=signal, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    df['signal'] = 0
    df.loc[df['macd'] > df['macd_signal'], 'signal'] = 1
    df['trade'] = df['signal'].diff().fillna(0)
    return df

def run_backtest(df, init_cash=100000):
    """Event-driven backtester for the MACD crossover strategy."""
    df = df.copy().reset_index()
    cash, shares, position = init_cash, 0, 0
    trades = []
    df['equity'] = init_cash

    if df.empty:
        return pd.DataFrame(), []

    for i in range(len(df) - 1):
        trade_signal = df.loc[i, 'trade']
        next_day_open = df.loc[i+1, 'Open']

        if trade_signal == 1 and position == 0:
            shares_to_buy = cash // next_day_open
            if shares_to_buy > 0:
                cash -= shares_to_buy * next_day_open
                position = 1
                shares = shares_to_buy
                trades.append({'date': df.loc[i+1, 'Date'], 'type': 'BUY', 'price': next_day_open, 'shares': shares})
        elif trade_signal == -1 and position == 1:
            cash += shares * next_day_open
            trades.append({'date': df.loc[i+1, 'Date'], 'type': 'SELL', 'price': next_day_open, 'shares': shares})
            shares, position = 0, 0
            
        df.loc[i, 'equity'] = cash + (shares * df.loc[i, 'Close'])
    
    df.loc[len(df)-1, 'equity'] = cash + (shares * df.loc[len(df)-1, 'Close'])

    return df.set_index('Date'), trades

def calculate_performance_metrics(backtest_df, trades_list, initial_capital):
    """Calculates a dictionary of professional trading metrics."""
    # (This function can be copied from the breakout_strategy.py file)
    if backtest_df.empty or not trades_list: return {}
    final_equity = backtest_df['equity'].iloc[-1]
    total_return_pct = (final_equity / initial_capital - 1) * 100
    daily_returns = backtest_df['equity'].pct_change().dropna()
    sharpe_ratio = np.sqrt(252) * daily_returns.mean() / daily_returns.std() if daily_returns.std() != 0 else 0
    peak = backtest_df['equity'].cummax()
    drawdown = (backtest_df['equity'] - peak) / peak
    max_drawdown_pct = drawdown.min() * 100
    trades_df = pd.DataFrame(trades_list)
    buy_prices = trades_df[trades_df['type'] == 'BUY']['price']
    sell_prices = trades_df[trades_df['type'] == 'SELL']['price']
    min_len = min(len(buy_prices), len(sell_prices))
    trade_returns = (sell_prices.values[:min_len] - buy_prices.values[:min_len]) / buy_prices.values[:min_len]
    win_rate = (trade_returns > 0).mean() * 100 if len(trade_returns) > 0 else 0
    return {
        "Total Return %": f"{total_return_pct:.2f}", "Sharpe Ratio": f"{sharpe_ratio:.2f}",
        "Max Drawdown %": f"{max_drawdown_pct:.2f}", "Win Rate %": f"{win_rate:.2f}",
        "Number of Trades": len(trades_list) // 2
    }

# --- Orchestrator/API Entry Point ---
def run(ticker: str, start_date: str, end_date: str, **kwargs) -> dict:
    """
    Runs the full backtest and returns both the summary and the full data for plotting.
    """
    try:
        fast_period = kwargs.get("fast", 12)
        slow_period = kwargs.get("slow", 26)
        signal_period = kwargs.get("signal", 9)
        initial_capital = 100000

        df = get_data(ticker, start_date, end_date)
        if df.empty:
            return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}

        df_signals = generate_signals(df, fast=fast_period, slow=slow_period, signal=signal_period)
        df_backtest, trades = run_backtest(df_signals, init_cash=initial_capital)
        
        summary_metrics = calculate_performance_metrics(df_backtest, trades, initial_capital)
        
        return {
            "summary": summary_metrics,
            "data": df_backtest
        }
    except Exception as e:
        return {"summary": {"Error": str(e)}, "data": pd.DataFrame()}

# --- Streamlit Visualization (Frontend Part) ---
if __name__ == "__main__":
    st.set_page_config(page_title="MACD Crossover Strategy", layout="wide")
    st.title("📈 MACD Crossover Strategy Showcase")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "GOOGL")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        fast_period = st.slider("Fast EMA Period", 5, 50, 12)
        slow_period = st.slider("Slow EMA Period", 20, 100, 26)
        signal_period = st.slider("Signal EMA Period", 5, 50, 9)
        run_button = st.button("🔬 Run Backtest", use_container_width=True)

    if run_button:
        st.header(f"Results for {ticker}")
        
        with st.spinner("Running backtest..."):
            results = run(ticker, str(start_date), str(end_date), fast=fast_period, slow=slow_period, signal=signal_period)
            summary = results.get("summary", {})
            backtest_df = results.get("data", pd.DataFrame())

            if "Error" in summary:
                st.error(summary["Error"])
            else:
                st.subheader("Performance Summary")
                cols = st.columns(5)
                cols[0].metric("Total Return", f"{summary.get('Total Return %', 0)}%")
                cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', 0))
                cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', 0)}%")
                cols[3].metric("Win Rate", f"{summary.get('Win Rate %', 0)}%")
                cols[4].metric("Trades", summary.get('Number of Trades', 0))

                st.subheader("Price, MACD & Equity Curve")
                
                # Create a figure with 2 subplots
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                    vertical_spacing=0.1, row_heights=[0.7, 0.3])

                # Price Chart on top subplot
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price'), row=1, col=1)
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['equity'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')), row=1, col=1)

                buy_signals = backtest_df[backtest_df['trade'] == 1]
                sell_signals = backtest_df[backtest_df['trade'] == -1]
                fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'], mode='markers', name='Buy Signal', marker=dict(color='green', size=10, symbol='triangle-up')), row=1, col=1)
                fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['Close'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')), row=1, col=1)

                # MACD Chart on bottom subplot
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['macd'], name='MACD Line', line=dict(color='blue')), row=2, col=1)
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['macd_signal'], name='Signal Line', line=dict(color='orange')), row=2, col=1)
                
                # Color the MACD histogram based on positive/negative
                colors = ['green' if val >= 0 else 'red' for val in backtest_df['macd_hist']]
                fig.add_trace(go.Bar(x=backtest_df.index, y=backtest_df['macd_hist'], name='Histogram', marker_color=colors), row=2, col=1)

                fig.update_layout(
                    title_text=f"{ticker} Backtest: MACD Crossover",
                    xaxis_rangeslider_visible=False,
                    yaxis=dict(title="Price ($)"),
                    yaxis2=dict(title="Equity ($)", overlaying='y', side='right')
                )
                st.plotly_chart(fig, use_container_width=True)