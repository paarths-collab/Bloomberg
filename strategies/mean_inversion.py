import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go

# --- Core Strategy & Backtesting Logic ---

def run_backtest(ticker, start_date, end_date, window=20, num_std=2, initial_capital=100000):
    """Runs the full vectorized backtest for the Mean Reversion strategy."""
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if df.empty:
        return pd.DataFrame()
        
    df.dropna(inplace=True)

    df['MA'] = df['Close'].rolling(window).mean()
    df['STD'] = df['Close'].rolling(window).std()
    df['Upper'] = df['MA'] + num_std * df['STD']
    df['Lower'] = df['MA'] - num_std * df['STD']

    df['Signal'] = 0
    df.loc[df['Close'] < df['Lower'], 'Signal'] = 1   # Buy
    df.loc[df['Close'] > df['Upper'], 'Signal'] = -1  # Sell (Go flat)
    
    # Forward fill signals to hold positions until an opposite signal
    df['Position'] = df['Signal'].replace(0, np.nan).ffill().fillna(0).shift(1)

    df['Strategy_Returns'] = df['Position'] * df['Close'].pct_change()
    df['Equity_Curve'] = (1 + df['Strategy_Returns']).cumprod() * initial_capital
    return df

def calculate_performance_metrics(backtest_df, initial_capital):
    """Calculates a dictionary of professional trading metrics."""
    if backtest_df.empty:
        return {}

    final_equity = backtest_df['Equity_Curve'].iloc[-1]
    total_return_pct = (final_equity / initial_capital - 1) * 100
    
    daily_returns = backtest_df['Strategy_Returns'].dropna()
    sharpe_ratio = np.sqrt(252) * daily_returns.mean() / daily_returns.std() if daily_returns.std() != 0 else 0
    
    peak = backtest_df['Equity_Curve'].cummax()
    drawdown = (backtest_df['Equity_Curve'] - peak) / peak
    max_drawdown_pct = drawdown.min() * 100

    trades = backtest_df[backtest_df['Signal'] != backtest_df['Signal'].shift(1)]
    
    return {
        "Total Return %": f"{total_return_pct:.2f}",
        "Sharpe Ratio": f"{sharpe_ratio:.2f}",
        "Max Drawdown %": f"{max_drawdown_pct:.2f}",
        "Number of Trades": len(trades)
    }

# --- Orchestrator/API Entry Point ---
def run(ticker: str, start_date: str, end_date: str, **kwargs) -> dict:
    """
    Runs the full backtest and returns both the summary and the full data for plotting.
    """
    try:
        window = kwargs.get("window", 20)
        num_std = kwargs.get("num_std", 2.0)
        
        df_backtest = run_backtest(ticker, start_date, end_date, window=window, num_std=num_std)
        if df_backtest.empty:
            return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}
            
        summary_metrics = calculate_performance_metrics(df_backtest, 100000)
        
        return {
            "summary": summary_metrics,
            "data": df_backtest
        }
    except Exception as e:
        return {"summary": {"Error": str(e)}, "data": pd.DataFrame()}

# --- Streamlit Visualization (Frontend Part) ---
if __name__ == "__main__":
    st.set_page_config(page_title="Mean Reversion Strategy", layout="wide")
    st.title("📈 Mean Reversion (Bollinger Bands) Showcase")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "BTC-USD")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        window = st.slider("Moving Average Window", 10, 100, 20)
        num_std = st.slider("Number of Standard Deviations", 1.0, 3.0, 2.0, 0.1)
        run_button = st.button("🔬 Run Backtest", use_container_width=True)

    if run_button:
        st.header(f"Results for {ticker}")
        
        with st.spinner("Running backtest..."):
            results = run(ticker, str(start_date), str(end_date), window=window, num_std=num_std)
            summary = results.get("summary", {})
            backtest_df = results.get("data", pd.DataFrame())

            if "Error" in summary:
                st.error(summary["Error"])
            else:
                st.subheader("Performance Summary")
                cols = st.columns(4)
                cols[0].metric("Total Return", f"{summary.get('Total Return %', 0)}%")
                cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', 0))
                cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', 0)}%")
                cols[3].metric("Trades", summary.get('Number of Trades', 0))

                st.subheader("Price Chart with Bollinger Bands & Equity Curve")
                fig = go.Figure()

                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Upper'], name='Upper Band', line=dict(color='orange', dash='dash')))
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Lower'], name='Lower Band', line=dict(color='orange', dash='dash')))
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))

                buy_signals = backtest_df[backtest_df['Signal'] == 1]
                sell_signals = backtest_df[backtest_df['Signal'] == -1]
                fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'], mode='markers', name='Buy Signal', marker=dict(color='green', size=10, symbol='triangle-up')))
                fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['Close'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

                fig.update_layout(
                    title_text=f"{ticker} Backtest: Mean Reversion",
                    xaxis_rangeslider_visible=False,
                    yaxis=dict(title="Price ($)"),
                    yaxis2=dict(title="Equity ($)", overlaying='y', side='right')
                )
                st.plotly_chart(fig, use_container_width=True)