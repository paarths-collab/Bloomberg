import yfinance as yf
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
import ta # Make sure you have the 'ta' library installed (pip install ta)

@st.cache_data 
def get_data(ticker, start, end):
    """ Standardized data fetching function. """
    df = yf.download(ticker, start=start, end=end, progress=False)
    if df.empty: return pd.DataFrame()
    df.rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"
    }, inplace=True, errors='ignore')
    df.columns = [col.title() for col in df.columns]
    return df[['Open', 'High', 'Low', 'Close', 'Volume']]

# --- Main Run Function (Callable by Portfolio Builder) ---
def run(ticker, start_date, end_date, initial_capital=100000, **kwargs):
    """ Main orchestrator function for the MACD Crossover strategy. """
    
    # Get strategy-specific parameters from kwargs
    fast_period = kwargs.get('fast', 12)
    slow_period = kwargs.get('slow', 26)
    signal_period = kwargs.get('signal', 9)
    
    class MacdCross(Strategy):
        fast = fast_period
        slow = slow_period
        signal = signal_period

        def init(self):
            close = pd.Series(self.data.Close)
            self.macd_line = self.I(ta.trend.macd, close, window_fast=self.fast, window_slow=self.slow)
            self.macd_signal_line = self.I(ta.trend.macd_signal, close, window_fast=self.fast, window_slow=self.slow, window_sign=self.signal)

        def next(self):
            if crossover(self.macd_line, self.macd_signal_line):
                self.position.close()
                self.buy()
            elif crossover(self.macd_signal_line, self.macd_line):
                self.position.close()
                self.sell()

    hist_df = get_data(ticker, start_date, end_date)
    if hist_df.empty:
        return {"summary": {"Error": "Could not fetch data."}, "data": pd.DataFrame()}
    
    bt = Backtest(hist_df, MacdCross, cash=initial_capital, commission=.002)
    stats = bt.run()

    summary = {
        "Total Return %": f"{stats['Return [%]']:.2f}",
        "Sharpe Ratio": f"{stats['Sharpe Ratio']:.2f}",
        "Max Drawdown %": f"{stats['Max. Drawdown [%]']:.2f}",
        "Number of Trades": stats['# Trades']
    }
    
    plot_df = hist_df.copy()
    plot_df['Equity_Curve'] = stats._equity_curve['Equity']
    
    return {"summary": summary, "data": plot_df}

# --- Streamlit UI for Standalone Testing ---
# This part only runs when you execute this script directly
if __name__ == "__main__":
    st.set_page_config(page_title="MACD Crossover Backtester", layout="wide")
    st.title("📈 MACD Crossover Strategy (Standalone)")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "GOOGL")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        
        st.header("Strategy Parameters")
        fast_period = st.slider("Fast EMA Period", 5, 50, 12)
        slow_period = st.slider("Slow EMA Period", 20, 100, 26)
        signal_period = st.slider("Signal EMA Period", 5, 50, 9)
        
        run_button = st.button("🔬 Run Backtest", use_container_width=True)

    if run_button:
        if fast_period >= slow_period:
            st.error("Error: Fast EMA period must be less than Slow EMA period.")
        else:
            st.header(f"Results for {ticker}")
            
            with st.spinner("Running backtest..."):
                results = run(
                    ticker=ticker, 
                    start_date=start_date, 
                    end_date=end_date, 
                    fast=fast_period, 
                    slow=slow_period,
                    signal=signal_period
                )
                summary = results.get("summary", {})
                backtest_df = results.get("data", pd.DataFrame())

            if "Error" in summary:
                st.error(summary["Error"])
            elif not backtest_df.empty:
                st.subheader("Performance Summary")
                cols = st.columns(4)
                cols[0].metric("Total Return", f"{summary.get('Total Return %', '0.00')}%")
                cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', '0.00'))
                cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', '0.00')}%")
                cols[3].metric("Trades", summary.get('Number of Trades', 0))

                st.subheader("Equity Curve")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity'))
                st.plotly_chart(fig, use_container_width=True)
# import pandas as pd
# from utils.data_loader import get_history
# from backtesting import Backtest, Strategy
# from backtesting.lib import crossover
# import ta
# import streamlit as st
# import yfinance as yf
# def get_data(ticker, start, end, interval='1d'):
#     df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
#     if df.empty:
#         return pd.DataFrame()
#     if isinstance(df.columns, pd.MultiIndex):
#         df.columns = df.columns.get_level_values(0)
#     df.columns = [col.title() for col in df.columns]
#     return df[['Open','High','Low','Close','Volume']]
# class ChannelTrading(Strategy):
#     """
#     Implements a Donchian Channel trading strategy.
#     Goes long on an upside breakout and short on a downside breakout.
#     """
#     # Default parameter for the channel lookback period
#     period = 20

#     def init(self):
#         """Initialize the indicators."""
#         # Calculate the rolling upper and lower channel bands
#         self.upper_band = self.I(lambda x: pd.Series(x).rolling(self.period).max(), self.data.High)
#         self.lower_band = self.I(lambda x: pd.Series(x).rolling(self.period).min(), self.data.Low)

#     def next(self):
#         """Define the trading logic for each bar."""
#         # If the price breaks above the previous bar's upper band, close any short and go long.
#         if self.data.Close[-1] > self.upper_band[-2]:
#             self.position.close()
#             self.buy()
#         # If the price breaks below the previous bar's lower band, close any long and go short.
#         elif self.data.Close[-1] < self.lower_band[-2]:
#             self.position.close()
#             self.sell()

# class MacdCross(Strategy):
#     """
#     A strategy that trades on the crossover of the MACD line and its signal line.
#     """
#     # Default parameters for the MACD indicator
#     fast = 12
#     slow = 26
#     signal = 9

#     def init(self):
#         """Initialize the indicators."""
#         close = pd.Series(self.data.Close)
#         # Calculate the MACD line and the Signal line
#         self.macd_line = self.I(ta.trend.macd, close, window_fast=self.fast, window_slow=self.slow)
#         self.macd_signal_line = self.I(ta.trend.macd_signal, close, window_fast=self.fast, window_slow=self.slow, window_sign=self.signal)

#     def next(self):
#         """Define the trading logic."""
#         # If the MACD line crosses above the signal line, close any short and buy.
#         if crossover(self.macd_line, self.macd_signal_line):
#             self.position.close()
#             self.buy()
#         # If the MACD line crosses below the signal line, close any long and sell.
#         elif crossover(self.macd_signal_line, self.macd_line):
#             self.position.close()
#             self.sell()

# def run(ticker, start_date, end_date, cash=10_000, commission=.002, **kwargs):
#     """
#     The main entry point called by the orchestrator to run the backtest.
#     """
#     hist_df = get_history(ticker, start_date, end_date)
#     if hist_df.empty:
#         return {"summary": {"Error": "Could not fetch historical data."}}

#     # Sanitize DataFrame columns to prevent errors with backtesting.py
#     if isinstance(hist_df.columns, pd.MultiIndex):
#         hist_df.columns = hist_df.columns.get_level_values(0)
#     hist_df.columns = [col.title() for col in hist_df.columns]

#     # Update strategy parameters from any provided kwargs
#     MacdCross.fast = kwargs.get('fast', 12)
#     MacdCross.slow = kwargs.get('slow', 26)
#     MacdCross.signal = kwargs.get('signal', 9)

#     # Instantiate and run the backtest
#     bt = Backtest(hist_df, MacdCross, cash=cash, commission=commission, finalize_trades=True)
#     stats = bt.run()
    
#     return {"summary": stats.to_dict()}