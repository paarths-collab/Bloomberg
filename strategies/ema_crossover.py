import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from utils.data_loader import get_history
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
# --- Core Strategy & Backtesting Logic ---

def run_backtest(ticker, start_date, end_date, fast=20, slow=50, initial_capital=100000):
    """Runs the full vectorized backtest for the EMA Crossover strategy."""
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if df.empty:
        return pd.DataFrame()
        
    df.dropna(inplace=True)

    df['EMA_Fast'] = df['Close'].ewm(span=fast, adjust=False).mean()
    df['EMA_Slow'] = df['Close'].ewm(span=slow, adjust=False).mean()

    df['Signal'] = 0
    df.loc[df['EMA_Fast'] > df['EMA_Slow'], 'Signal'] = 1
    df['Position'] = df['Signal'].shift(1).fillna(0)

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


def run(ticker, start_date, end_date, cash=10_000, commission=.002):
    class EmaCross(Strategy):
        n1 = 20
        n2 = 50

        def init(self):
            close = self.data.Close
            self.ema1 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), close, self.n1)
            self.ema2 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), close, self.n2)

        def next(self):
            if crossover(self.ema1, self.ema2):
                self.buy()
            elif crossover(self.ema2, self.ema1):
                self.sell()

    hist_df = get_history(ticker, start_date, end_date)
    if hist_df.empty: return {"error": "Could not fetch data."}
    bt = Backtest(hist_df, EmaCross, cash=cash, commission=commission)
    stats = bt.run()
    return {"summary": stats.to_dict(), "plot": bt.plot(open_browser=False)}

# --- Streamlit Visualization (Frontend Part) ---
if __name__ == "__main__":
    st.set_page_config(page_title="EMA Crossover Strategy", layout="wide")
    st.title("📈 EMA Crossover Strategy Showcase")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "TSLA")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        fast_period = st.slider("Fast EMA Period", 5, 100, 20)
        slow_period = st.slider("Slow EMA Period", 20, 300, 50)
        run_button = st.button("🔬 Run Backtest", use_container_width=True)

    if run_button:
        if fast_period >= slow_period:
            st.error("Error: Fast EMA period must be less than Slow EMA period.")
        else:
            st.header(f"Results for {ticker}")
            
            with st.spinner("Running backtest..."):
                results = run(ticker, str(start_date), str(end_date), fast=fast_period, slow=slow_period)
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
                    fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Fast'], name=f'EMA {fast_period}', line=dict(color='green', dash='dash')))
                    fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Slow'], name=f'EMA {slow_period}', line=dict(color='red', dash='dash')))
                    fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))

                    buy_signals = backtest_df[(backtest_df['Signal'] == 1) & (backtest_df['Signal'].shift(1) == 0)]
                    sell_signals = backtest_df[(backtest_df['Signal'] == 0) & (backtest_df['Signal'].shift(1) == 1)]
                    fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'], mode='markers', name='Buy Signal', marker=dict(color='green', size=10, symbol='triangle-up')))
                    fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['Close'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

                    fig.update_layout(
                        title_text=f"{ticker} Backtest: EMA Crossover",
                        xaxis_rangeslider_visible=False,
                        yaxis=dict(title="Price ($)"),
                        yaxis2=dict(title="Equity ($)", overlaying='y', side='right')
                    )
                    st.plotly_chart(fig, use_container_width=True)