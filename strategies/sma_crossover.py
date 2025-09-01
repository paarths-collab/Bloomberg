import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from utils.data_loader import get_history
from backtesting import Backtest, Strategy
from backtesting.lib import crossover

# --- Core Strategy & Backtesting Logic ---
def run_backtest(ticker, start_date, end_date, short_window=50, long_window=200, initial_capital=100000):
    """Runs the full vectorized backtest for the SMA Crossover strategy."""
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if df.empty:
        return pd.DataFrame()
    df.dropna(inplace=True)
    df['SMA_Short'] = df['Close'].rolling(short_window).mean()
    df['SMA_Long'] = df['Close'].rolling(long_window).mean()
    df['Signal'] = 0
    df.loc[df['SMA_Short'] > df['SMA_Long'], 'Signal'] = 1
    df['Position'] = df['Signal'].shift(1).fillna(0)
    df['Strategy_Returns'] = df['Position'] * df['Close'].pct_change()
    df['Equity_Curve'] = (1 + df['Strategy_Returns']).cumprod() * initial_capital
    return df

def calculate_performance_metrics(backtest_df, initial_capital):
    """Calculates a dictionary of professional trading metrics."""
    if backtest_df.empty: return {}
    final_equity = backtest_df['Equity_Curve'].iloc[-1]
    total_return_pct = (final_equity / initial_capital - 1) * 100
    daily_returns = backtest_df['Strategy_Returns'].dropna()
    sharpe_ratio = np.sqrt(252) * daily_returns.mean() / daily_returns.std() if daily_returns.std() != 0 else 0
    peak = backtest_df['Equity_Curve'].cummax()
    drawdown = (backtest_df['Equity_Curve'] - peak) / peak
    max_drawdown_pct = drawdown.min() * 100
    trades = backtest_df[backtest_df['Signal'] != backtest_df['Signal'].shift(1)]
    return {
        "Total Return %": f"{total_return_pct:.2f}", "Sharpe Ratio": f"{sharpe_ratio:.2f}",
        "Max Drawdown %": f"{max_drawdown_pct:.2f}", "Number of Trades": len(trades)
    }

# --- Orchestrator/API Entry Point ---

def run(ticker, start_date, end_date, cash=10_000, commission=.002):
    class SmaCross(Strategy):
        n1 = 50
        n2 = 100

        def init(self):
            close = self.data.Close
            self.sma1 = self.I(lambda x, n: pd.Series(x).rolling(n).mean(), close, self.n1)
            self.sma2 = self.I(lambda x, n: pd.Series(x).rolling(n).mean(), close, self.n2)

        def next(self):
            if crossover(self.sma1, self.sma2):
                self.buy()
            elif crossover(self.sma2, self.sma1):
                self.sell()

    hist_df = get_history(ticker, start_date, end_date)
    if hist_df.empty: return {"error": "Could not fetch data."}
    bt = Backtest(hist_df, SmaCross, cash=cash, commission=commission)
    stats = bt.run()
    return {"summary": stats.to_dict(), "plot": bt.plot(open_browser=False)}

# --- Streamlit Visualization ---
if __name__ == "__main__":
    st.set_page_config(page_title="SMA Crossover Strategy", layout="wide")
    st.title("📈 SMA Crossover Strategy Showcase")
    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "AAPL")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        short_window = st.slider("Short SMA Window", 10, 100, 50)
        long_window = st.slider("Long SMA Window", 50, 300, 200)
        run_button = st.button("🔬 Run Backtest", use_container_width=True)
    if run_button:
        if short_window >= long_window:
            st.error("Error: Short window must be less than long window.")
        else:
            st.header(f"Results for {ticker}")
            with st.spinner("Running backtest..."):
                results = run(ticker, str(start_date), str(end_date), short_window=short_window, long_window=long_window)
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
                    st.subheader("Price Chart with Signals & Equity Curve")
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
                    fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['SMA_Short'], name=f'SMA {short_window}', line=dict(color='green', dash='dash')))
                    fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['SMA_Long'], name=f'SMA {long_window}', line=dict(color='red', dash='dash')))
                    fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))
                    buy_signals = backtest_df[(backtest_df['Signal'] == 1) & (backtest_df['Signal'].shift(1) == 0)]
                    sell_signals = backtest_df[(backtest_df['Signal'] == -1) & (backtest_df['Signal'].shift(1) == 1)]
                    fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'], mode='markers', name='Buy Signal (Golden Cross)', marker=dict(color='green', size=10, symbol='triangle-up')))
                    fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['Close'], mode='markers', name='Sell Signal (Death Cross)', marker=dict(color='red', size=10, symbol='triangle-down')))
                    fig.update_layout(title_text=f"{ticker} Backtest: SMA Crossover", xaxis_rangeslider_visible=False, yaxis=dict(title="Price ($)"), yaxis2=dict(title="Equity ($)", overlaying='y', side='right'))
                    st.plotly_chart(fig, use_container_width=True)