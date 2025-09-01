import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from utils.data_loader import get_history
from backtesting import Backtest, Strategy

# --- Core Strategy & Backtesting Logic ---
def get_data(ticker, start, end, interval='1d'):
    df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
    if df.empty: return pd.DataFrame()
    return df[['Open', 'High', 'Low', 'Close', 'Volume']]

def generate_signals(df, lookback=50):
    df = df.copy()
    df['trade'] = 0
    levels = [0.382, 0.5, 0.618]
    for i in range(lookback, len(df)):
        window_df = df.iloc[i-lookback:i]
        low, high = window_df['Low'].min(), window_df['High'].max()
        move = high - low
        if move <= 0: continue
        price = df.iloc[i]['Close']
        tol = 0.005 * price
        for lvl in levels:
            fib_level_price = high - lvl * move
            if abs(price - fib_level_price) <= tol:
                df.iloc[i, df.columns.get_loc('trade')] = 1
                break
    return df

def run_backtest(df, hold_days=10, init_cash=100000):
    df = df.copy().reset_index()
    cash, position, shares, entry_idx = init_cash, 0, 0, None
    trades = []
    df['equity'] = init_cash
    if df.empty: return pd.DataFrame(), []
    for i in range(len(df)-1):
        trade_signal = df.loc[i, 'trade']
        next_day_open = df.loc[i+1, 'Open']
        if trade_signal == 1 and position == 0:
            shares_to_buy = cash // next_day_open
            if shares_to_buy > 0:
                cash -= shares_to_buy * next_day_open
                position, shares, entry_idx = 1, shares_to_buy, i + 1
                trades.append({'date': df.loc[i+1, 'Date'], 'type': 'BUY', 'price': next_day_open, 'shares': shares})
        if position == 1 and entry_idx is not None and (i + 1 - entry_idx) >= hold_days:
            cash += shares * next_day_open
            trades.append({'date': df.loc[i+1, 'Date'], 'type': 'SELL', 'price': next_day_open, 'shares': shares})
            shares, position, entry_idx = 0, 0, None
        df.loc[i, 'equity'] = cash + (shares * df.loc[i, 'Close'])
    df.loc[len(df)-1, 'equity'] = cash + (shares * df.loc[len(df)-1, 'Close'])
    return df.set_index('Date'), trades

def calculate_performance_metrics(backtest_df, trades_list, initial_capital):
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




def run(ticker, start_date, end_date, cash=10_000, commission=.002):
    class FibonacciPullback(Strategy):
        lookback_period = 50

        def init(self):
            # Indicators defined in init
            self.highest_high = self.I(lambda x, n: pd.Series(x).rolling(n).max(), self.data.High, self.lookback_period)
            self.lowest_low = self.I(lambda x, n: pd.Series(x).rolling(n).min(), self.data.Low, self.lookback_period)

        def next(self):
            if self.highest_high[-1] > self.lowest_low[-1]:
                fib_level_38 = self.highest_high[-1] - 0.382 * (self.highest_high[-1] - self.lowest_low[-1])
                if self.data.Close[-1] < fib_level_38 and self.data.Close[-1] > self.data.Close[-2]:
                    self.buy()
                elif self.position and self.data.Close[-1] > self.highest_high[-1]:
                    self.position.close()

    hist_df = get_history(ticker, start_date, end_date)
    if hist_df.empty: return {"error": "Could not fetch data."}
    bt = Backtest(hist_df, FibonacciPullback, cash=cash, commission=commission)
    stats = bt.run()
    return {"summary": stats.to_dict(), "plot": bt.plot(open_browser=False)}
    
# --- Streamlit Visualization ---
if __name__ == "__main__":
    st.set_page_config(page_title="Fibonacci Pullback Strategy", layout="wide")
    st.title("📈 Fibonacci Pullback Strategy Showcase")
    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "NVDA")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        lookback = st.slider("Lookback Period for Swings (days)", 20, 200, 50)
        hold_days = st.slider("Holding Period (days)", 3, 30, 10)
        run_button = st.button("🔬 Run Backtest", use_container_width=True)
    if run_button:
        st.header(f"Results for {ticker}")
        with st.spinner("Running backtest..."):
            results = run(ticker, str(start_date), str(end_date), lookback=lookback, hold_days=hold_days)
            summary = results.get("summary", {})
            backtest_df = results.get("data", pd.DataFrame())
            trades_list = results.get("trades", [])
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
                st.subheader("Price Chart with Signals & Equity Curve")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['equity'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))
                trades_df = pd.DataFrame(trades_list)
                if not trades_df.empty:
                    buy_signals = trades_df[trades_df['type'] == 'BUY']
                    sell_signals = trades_df[trades_df['type'] == 'SELL']
                    fig.add_trace(go.Scatter(x=buy_signals['date'], y=buy_signals['price'], mode='markers', name='Buy Signal', marker=dict(color='green', size=10, symbol='triangle-up')))
                    fig.add_trace(go.Scatter(x=sell_signals['date'], y=sell_signals['price'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))
                fig.update_layout(title_text=f"{ticker} Backtest: Fibonacci Pullback", xaxis_rangeslider_visible=False, yaxis=dict(title="Price ($)"), yaxis2=dict(title="Equity ($)", overlaying='y', side='right'))
                st.plotly_chart(fig, use_container_width=True)