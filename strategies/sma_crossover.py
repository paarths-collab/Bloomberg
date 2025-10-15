import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from backtesting import Backtest, Strategy
from backtesting.lib import crossover

# --- CORRECT: Import the single, centralized get_data function ---
from utils.data_loader import get_data

class SmaCross(Strategy):
    """
    SMA Crossover Strategy implementation for backtesting.py library.
    
    This strategy generates buy signals when the short SMA crosses above the long SMA
    (Golden Cross) and sell signals when the short SMA crosses below the long SMA
    (Death Cross).
    """
    
    def init(self):
        close = self.data.Close
        self.sma1 = self.I(lambda x, n: pd.Series(x).rolling(n).mean(), close, self.short_sma_window)
        self.sma2 = self.I(lambda x, n: pd.Series(x).rolling(n).mean(), close, self.long_sma_window)

    def next(self):
        if crossover(self.sma1, self.sma2):
            self.buy()
        elif crossover(self.sma2, self.sma1):
            self.sell()

# --- Main Run Function (Callable by Portfolio Builder) ---
def run(ticker: str, start_date: str, end_date: str, market, initial_capital=100000, **kwargs) -> dict:
    """ Main orchestrator function for the SMA Crossover strategy. """
    
    short_window = kwargs.get('short_window', 50)
    long_window = kwargs.get('long_window', 200)

    # Set the parameters for the strategy class
    SmaCross.short_sma_window = short_window
    SmaCross.long_sma_window = long_window

    hist_df = get_data(ticker, start_date, end_date, market)
    if hist_df.empty:
        return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}

    bt = Backtest(hist_df, SmaCross, cash=initial_capital, commission=.002, finalize_trades=True)
    stats = bt.run()

    summary = {
        "Total Return %": f"{stats['Return [%]']:.2f}",
        "Sharpe Ratio": f"{stats['Sharpe Ratio']:.2f}",
        "Max Drawdown %": f"{stats['Max. Drawdown [%]']:.2f}",
        "Number of Trades": stats['# Trades']
    }
    
    # --- Prepare detailed data for professional plotting ---
    plot_df = hist_df.copy()
    plot_df['Equity_Curve'] = stats._equity_curve['Equity']
    plot_df['SMA_Short'] = plot_df['Close'].rolling(short_window).mean()
    plot_df['SMA_Long'] = plot_df['Close'].rolling(long_window).mean()
    
    trades = stats._trades
    
    return {"summary": summary, "data": plot_df, "trades": trades}

# --- Streamlit Visualization for Standalone Testing ---
if __name__ == "__main__":
    st.set_page_config(page_title="SMA Crossover Strategy", layout="wide")
    st.title("📈 SMA Crossover Strategy (Standalone)")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "AAPL")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        
        st.header("Strategy Parameters")
        short_window = st.slider("Short SMA Window", 10, 100, 50)
        long_window = st.slider("Long SMA Window", 50, 300, 200)
        
        run_button = st.button("🔬 Run Backtest", use_container_width=True)

    if run_button:
        if short_window >= long_window:
            st.error("Error: Short window must be less than long window.")
        else:
            st.header(f"Results for {ticker}")
            with st.spinner("Running backtest..."):
                results = run(
                    ticker=ticker,
                    start_date=start_date,
                    end_date=end_date,
                    market="USA",  # Default market for standalone testing
                    short_window=short_window,
                    long_window=long_window
                )
                summary = results.get("summary", {})
                backtest_df = results.get("data", pd.DataFrame())
                trades_df = results.get("trades", pd.DataFrame())

            if "Error" in summary:
                st.error(summary["Error"])
            elif not backtest_df.empty:
                st.subheader("Performance Summary")
                cols = st.columns(4)
                cols[0].metric("Total Return", f"{summary.get('Total Return %', '0.00')}%")
                cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', '0.00'))
                cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', '0.00')}%")
                cols[3].metric("Trades", summary.get('Number of Trades', 0))

                # --- Professional Charting ---
                st.subheader("Price Chart with SMA Crossover, Trades & Equity")
                fig = go.Figure()

                # Price, SMAs, and Equity Curve
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['SMA_Short'], name=f'SMA {short_window}', line=dict(color='green', dash='dash')))
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['SMA_Long'], name=f'SMA {long_window}', line=dict(color='red', dash='dash')))
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))
                
                # Trade Markers
                buy_signals = trades_df[trades_df['Size'] > 0]
                sell_signals = trades_df[trades_df['Size'] < 0]
                fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['EntryPrice'], mode='markers', name='Buy (Golden Cross)', marker=dict(color='lime', size=10, symbol='triangle-up')))
                fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['EntryPrice'], mode='markers', name='Sell (Death Cross)', marker=dict(color='red', size=10, symbol='triangle-down')))

                fig.update_layout(
                    title_text=f"{ticker} SMA Crossover Backtest ({short_window}/{long_window})",
                    xaxis_rangeslider_visible=False,
                    yaxis=dict(title="Price ($)"),
                    yaxis2=dict(title="Equity ($)", overlaying='y', side='right', showgrid=False)
                )
                st.plotly_chart(fig, use_container_width=True)