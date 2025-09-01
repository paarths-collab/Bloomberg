import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- Core Strategy & Backtesting Logic ---
def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).fillna(0)
    loss = -delta.clip(upper=0).fillna(0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def get_data(ticker, start, end):
    df = yf.download(ticker, start=start, end=end, progress=False)
    if df.empty: return pd.DataFrame()
    df.dropna(inplace=True)
    return df

def detect_divergence(df, window=30):
    df = df.copy()
    df['rsi'] = compute_rsi(df['Close'])
    df['trade'] = 0
    for i in range(window, len(df)):
        sub = df.iloc[i-window:i]
        lows = sub['Close'].nsmallest(2)
        if len(lows) == 2:
            idx1, idx2 = lows.index[0], lows.index[1]
            if sub.loc[idx2, 'Close'] < sub.loc[idx1, 'Close'] and sub.loc[idx2, 'rsi'] > sub.loc[idx1, 'rsi']:
                df.iloc[i, df.columns.get_loc('trade')] = 1
        highs = sub['Close'].nlargest(2)
        if len(highs) == 2:
            idx1, idx2 = highs.index[0], highs.index[1]
            if sub.loc[idx2, 'Close'] > sub.loc[idx1, 'Close'] and sub.loc[idx2, 'rsi'] < sub.loc[idx1, 'rsi']:
                df.iloc[i, df.columns.get_loc('trade')] = -1
    return df

def run_backtest(df, initial_capital=100000):
    df = df.copy()
    df['Position'] = df['trade'].replace(0, np.nan).ffill().fillna(0).shift(1)
    df['Strategy_Returns'] = df['Close'].pct_change() * df['Position']
    df['Equity_Curve'] = (1 + df['Strategy_Returns']).cumprod() * initial_capital
    return df

def calculate_performance_metrics(backtest_df, initial_capital):
    # (This function can be copied from other strategy files)
    if backtest_df.empty: return {}
    final_equity = backtest_df['Equity_Curve'].iloc[-1]
    total_return_pct = (final_equity / initial_capital - 1) * 100
    daily_returns = backtest_df['Strategy_Returns'].dropna()
    sharpe_ratio = np.sqrt(252) * daily_returns.mean() / daily_returns.std() if daily_returns.std() != 0 else 0
    peak = backtest_df['Equity_Curve'].cummax()
    drawdown = (backtest_df['Equity_Curve'] - peak) / peak
    max_drawdown_pct = drawdown.min() * 100
    trades = backtest_df[backtest_df['trade'] != 0]
    return {
        "Total Return %": f"{total_return_pct:.2f}", "Sharpe Ratio": f"{sharpe_ratio:.2f}",
        "Max Drawdown %": f"{max_drawdown_pct:.2f}", "Number of Trades": len(trades)
    }

# --- Orchestrator/API Entry Point ---
def run(ticker: str, start_date: str, end_date: str, **kwargs) -> dict:
    try:
        window = kwargs.get("window", 30)
        df = get_data(ticker, start_date, end_date)
        if df.empty:
            return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}
        df_signals = detect_divergence(df, window=window)
        df_backtest = run_backtest(df_signals)
        summary_metrics = calculate_performance_metrics(df_backtest, 100000)
        return {"summary": summary_metrics, "data": df_backtest}
    except Exception as e:
        return {"summary": {"Error": str(e)}, "data": pd.DataFrame()}

# --- Streamlit Visualization ---
if __name__ == "__main__":
    st.set_page_config(page_title="RSI Divergence Strategy", layout="wide")
    st.title("📈 RSI Divergence Reversal Strategy Showcase")
    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "AAPL")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        window = st.slider("Divergence Lookback Window (days)", 10, 100, 30)
        run_button = st.button("🔬 Run Backtest", use_container_width=True)
    if run_button:
        st.header(f"Results for {ticker}")
        with st.spinner("Running backtest..."):
            results = run(ticker, str(start_date), str(end_date), window=window)
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
                st.subheader("Price, RSI & Divergence Signals")
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1, row_heights=[0.7, 0.3])
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price'), row=1, col=1)
                buy_signals = backtest_df[backtest_df['trade'] == 1]
                sell_signals = backtest_df[backtest_df['trade'] == -1]
                fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'], mode='markers', name='Bullish Divergence (Buy)', marker=dict(color='green', size=10, symbol='triangle-up')), row=1, col=1)
                fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['Close'], mode='markers', name='Bearish Divergence (Sell)', marker=dict(color='red', size=10, symbol='triangle-down')), row=1, col=1)
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['rsi'], name='RSI'), row=2, col=1)
                fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
                fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)
                fig.update_layout(title_text=f"{ticker} Backtest: RSI Divergence Reversal", xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)