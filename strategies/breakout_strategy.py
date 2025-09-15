# File: strategies/breakout_strategy.py

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from backtesting import Backtest, Strategy

# --- CORRECT: Import the single, centralized get_data function ---
from utils.data_loader import get_data

# --- Main Run Function (Callable by Portfolio Builder) ---
def run(ticker: str, start_date: str, end_date: str, initial_capital=100000, **kwargs) -> dict:
    """ Main orchestrator function for the Breakout strategy. """
    
    lookback_period = kwargs.get('lookback', 20)

    class Breakout(Strategy):
        lookback = lookback_period

        def init(self):
            # Calculate rolling max of the high and min of the low over the lookback period
            self.highs = self.I(lambda x: pd.Series(x).rolling(self.lookback).max(), self.data.High)
            self.lows = self.I(lambda x: pd.Series(x).rolling(self.lookback).min(), self.data.Low)

        def next(self):
            # A breakout occurs if the closing price exceeds the highest high of the *previous* N bars
            if self.data.Close[-1] > self.highs[-2]:
                self.position.close() # Close any short position
                self.buy()
            # A breakdown occurs if the closing price falls below the lowest low of the *previous* N bars
            elif self.data.Close[-1] < self.lows[-2]:
                self.position.close() # Close any long position
                self.sell()

    # --- CORRECT: Call the centralized get_data function ---
    hist_df = get_data(ticker, start_date, end_date)
    if hist_df.empty:
        return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}

    # CORRECT CODE:
    bt = Backtest(hist_df, Breakout, cash=initial_capital, commission=.002, finalize_trades=True) # <-- CORRECT PLACE
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
    plot_df['Breakout_High'] = plot_df['High'].rolling(lookback_period).max().shift(1) # Shift for correct plotting
    plot_df['Breakout_Low'] = plot_df['Low'].rolling(lookback_period).min().shift(1)  # Shift for correct plotting
    
    trades = stats._trades
    
    return {"summary": summary, "data": plot_df, "trades": trades}

# --- Streamlit Visualization for Standalone Testing ---
if __name__ == "__main__":
    st.set_page_config(page_title="Breakout Strategy", layout="wide")
    st.title("📈 Breakout Strategy (Standalone)")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "NVDA")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        
        st.header("Strategy Parameters")
        lookback = st.slider("Lookback Period (days)", 10, 100, 20)
        
        run_button = st.button("🔬 Run Backtest", use_container_width=True)

    if run_button:
        st.header(f"Results for {ticker}")
        with st.spinner("Running backtest..."):
            results = run(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                lookback=lookback
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
            st.subheader("Price Chart with Breakout Levels, Trades & Equity")
            fig = go.Figure()

            # Price, Breakout Levels, and Equity Curve
            fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
            fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Breakout_High'], name='Breakout High', line=dict(color='lightcoral', dash='dash')))
            fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Breakout_Low'], name='Breakout Low', line=dict(color='lightgreen', dash='dash')))
            fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))
            
            # Trade Markers
            buy_signals = trades_df[trades_df['Size'] > 0]
            sell_signals = trades_df[trades_df['Size'] < 0]
            fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['EntryPrice'], mode='markers', name='Buy Signal', marker=dict(color='lime', size=10, symbol='triangle-up')))
            fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['EntryPrice'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

            fig.update_layout(
                title_text=f"{ticker} Breakout Strategy Backtest",
                xaxis_rangeslider_visible=False,
                yaxis=dict(title="Price ($)"),
                yaxis2=dict(title="Equity ($)", overlaying='y', side='right', showgrid=False)
            )
            st.plotly_chart(fig, use_container_width=True)
# import yfinance as yf
# import pandas as pd
# import streamlit as st
# import plotly.graph_objects as go
# from backtesting import Backtest, Strategy

# @st.cache_data 
# def get_data(ticker, start, end):
#     """ Standardized data fetching function. """
#     df = yf.download(ticker, start=start, end=end, progress=False)
#     if df.empty: return pd.DataFrame()
#     df.rename(columns={
#         "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"
#     }, inplace=True, errors='ignore')
#     df.columns = [col.title() for col in df.columns]
#     return df[['Open', 'High', 'Low', 'Close', 'Volume']]

# # --- Main Run Function (Callable by Portfolio Builder) ---
# def run(ticker: str, start_date: str, end_date: str, initial_capital=100000, **kwargs) -> dict:
#     """ Main orchestrator function for the Breakout strategy. """
    
#     lookback_period = kwargs.get('lookback', 20)

#     class Breakout(Strategy):
#         lookback = lookback_period

#         def init(self):
#             # Calculate rolling max of the high and min of the low over the lookback period
#             self.highs = self.I(lambda x: pd.Series(x).rolling(self.lookback).max(), self.data.High)
#             self.lows = self.I(lambda x: pd.Series(x).rolling(self.lookback).min(), self.data.Low)

#         def next(self):
#             # A breakout occurs if the closing price exceeds the highest high of the *previous* N bars
#             if self.data.Close[-1] > self.highs[-2]:
#                 self.position.close() # Close any short position
#                 self.buy()
#             # A breakdown occurs if the closing price falls below the lowest low of the *previous* N bars
#             elif self.data.Close[-1] < self.lows[-2]:
#                 self.position.close() # Close any long position
#                 self.sell()

#     hist_df = get_data(ticker, start_date, end_date)
#     if hist_df.empty:
#         return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}

#     bt = Backtest(hist_df, Breakout, cash=initial_capital, commission=.002)
#     stats = bt.run(finalize_trades=True)

#     summary = {
#         "Total Return %": f"{stats['Return [%]']:.2f}",
#         "Sharpe Ratio": f"{stats['Sharpe Ratio']:.2f}",
#         "Max Drawdown %": f"{stats['Max. Drawdown [%]']:.2f}",
#         "Number of Trades": stats['# Trades']
#     }
    
#     # --- Prepare detailed data for professional plotting ---
#     plot_df = hist_df.copy()
#     plot_df['Equity_Curve'] = stats._equity_curve['Equity']
#     plot_df['Breakout_High'] = plot_df['High'].rolling(lookback_period).max().shift(1) # Shift for correct plotting
#     plot_df['Breakout_Low'] = plot_df['Low'].rolling(lookback_period).min().shift(1)  # Shift for correct plotting
    
#     trades = stats._trades
    
#     return {"summary": summary, "data": plot_df, "trades": trades}

# # --- Streamlit Visualization for Standalone Testing ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="Breakout Strategy", layout="wide")
#     st.title("📈 Breakout Strategy (Standalone)")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "NVDA")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
        
#         st.header("Strategy Parameters")
#         lookback = st.slider("Lookback Period (days)", 10, 100, 20)
        
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker}")
#         with st.spinner("Running backtest..."):
#             results = run(
#                 ticker=ticker,
#                 start_date=start_date,
#                 end_date=end_date,
#                 lookback=lookback
#             )
#             summary = results.get("summary", {})
#             backtest_df = results.get("data", pd.DataFrame())
#             trades_df = results.get("trades", pd.DataFrame())

#         if "Error" in summary:
#             st.error(summary["Error"])
#         elif not backtest_df.empty:
#             st.subheader("Performance Summary")
#             cols = st.columns(4)
#             cols[0].metric("Total Return", f"{summary.get('Total Return %', '0.00')}%")
#             cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', '0.00'))
#             cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', '0.00')}%")
#             cols[3].metric("Trades", summary.get('Number of Trades', 0))

#             # --- Professional Charting ---
#             st.subheader("Price Chart with Breakout Levels, Trades & Equity")
#             fig = go.Figure()

#             # Price, Breakout Levels, and Equity Curve
#             fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
#             fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Breakout_High'], name='Breakout High', line=dict(color='lightcoral', dash='dash')))
#             fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Breakout_Low'], name='Breakout Low', line=dict(color='lightgreen', dash='dash')))
#             fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))
            
#             # Trade Markers
#             buy_signals = trades_df[trades_df['Size'] > 0]
#             sell_signals = trades_df[trades_df['Size'] < 0]
#             fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['EntryPrice'], mode='markers', name='Buy Signal', marker=dict(color='lime', size=10, symbol='triangle-up')))
#             fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['EntryPrice'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

#             fig.update_layout(
#                 title_text=f"{ticker} Breakout Strategy Backtest",
#                 xaxis_rangeslider_visible=False,
#                 yaxis=dict(title="Price ($)"),
#                 yaxis2=dict(title="Equity ($)", overlaying='y', side='right', showgrid=False)
#             )
#             st.plotly_chart(fig, use_container_width=True)
# #  import pandas as pd
# from utils.data_loader import get_history
# from backtesting import Backtest, Strategy
# import streamlit as st
# import plotly.graph_objects as go
# import yfinance as yf

# # --- Robust Data Fetching and Cleaning Function ---
# def get_data(ticker, start, end):
#     """
#     Fetches and correctly formats data for the backtesting.py library.
#     """
#     df = yf.download(ticker, start=start, end=end, progress=False)
#     if df.empty:
#         return pd.DataFrame()

#     # Flatten MultiIndex columns and ensure Title Case
#     if isinstance(df.columns, pd.MultiIndex):
#         df.columns = df.columns.get_level_values(0)
#     df.columns = [col.title() for col in df.columns]

#     return df

# class Breakout(Strategy):
#     lookback = 20  # This will be overridden by the UI

#     def init(self):
#         self.highs = self.I(lambda x: pd.Series(x).rolling(self.lookback).max(), self.data.High)
#         self.lows = self.I(lambda x: pd.Series(x).rolling(self.lookback).min(), self.data.Low)

#     def next(self):
#         if self.data.Close[-1] > self.highs[-2]:
#             self.position.close()
#             self.buy()
#         elif self.data.Close[-1] < self.lows[-2]:
#             self.position.close()
#             self.sell()

# def run(ticker, start_date, end_date, cash=10_000, commission=.002, **kwargs):
#     """
#     Main entry point for the strategy.
#     """
#     try:
#         hist_df = get_data(ticker, start_date, end_date)
#         if hist_df.empty:
#             return {"summary": {"Error": f"Could not fetch data for {ticker}."}}

#         # *** FIX: Set the lookback period from the UI ***
#         Breakout.lookback = kwargs.get('lookback_period', 20)

#         bt = Backtest(hist_df, Breakout, cash=100_000, commission=commission)
#         stats = bt.run()

#         # *** FIX: Return the correct dictionary structure ***
#         return {
#             "summary": stats.to_dict(),
#             "data": stats._equity_curve
#         }

#     except Exception as e:
#         print(f"ERROR: Backtest for {ticker} failed: {e}")
#         return {"summary": {"Error": str(e)}}

# # --- Streamlit Visualization (for standalone testing) ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="Breakout Strategy", layout="wide")
#     st.title("📈 Breakout Strategy Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         market = st.selectbox("Market", ["usa", "india"])
#         ticker = st.text_input("Ticker Symbol", "NVDA" if market == "usa" else "RELIANCE")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         lookback_period = st.slider("Lookback Period (days)", 10, 100, 20)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker} ({market.upper()})")
#         with st.spinner("Running backtest..."):
#             # The 'market' argument is not needed by run, but kwargs will accept it
#             results = run(
#                 ticker=ticker,
#                 start_date=str(start_date.date()),
#                 end_date=str(end_date.date()),
#                 lookback_period=lookback_period
#             )
#             summary = results.get("summary", {})
#             backtest_df = results.get("data", pd.DataFrame())

#         if "Error" in summary:
#             st.error(summary["Error"])
#         elif not backtest_df.empty and 'Equity' in backtest_df.columns:
#             st.subheader("Performance Summary")
#             cols = st.columns(4)
#             cols[0].metric("Return [%]", f"{summary.get('Return [%]', 0):.2f}")
#             cols[1].metric("Sharpe Ratio", f"{summary.get('Sharpe Ratio', 0):.2f}")
#             cols[2].metric("Max Drawdown [%]", f"{summary.get('Max. Drawdown [%]', 0):.2f}")
#             cols[3].metric("# Trades", summary.get('# Trades', 0))

#             st.subheader("Equity Curve & Price")
#             # Fetch price data separately for the chart's secondary axis
#             price_data = get_data(ticker, str(start_date.date()), str(end_date.date()))

#             fig = go.Figure()
#             fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity'], name='Equity Curve', line=dict(color='purple')))
#             if not price_data.empty:
#                 # Use .title() to match the 'Close' column from get_data
#                 fig.add_trace(go.Scatter(x=price_data.index, y=price_data['Close'], name='Close Price', yaxis='y2', line=dict(color='blue', dash='dash')))

#             fig.update_layout(
#                 title_text=f"{ticker} Equity Curve and Price",
#                 yaxis=dict(title="Equity ($)"),
#                 yaxis2=dict(title="Price ($)", overlaying='y', side='right')
#             )
#             st.plotly_chart(fig, use_container_width=True)
#         else:
#             st.warning("Backtest completed, but no trades were made or data could not be plotted.")
# # import pandas as pd
# from utils.data_loader import get_history
# from backtesting import Backtest, Strategy
# import streamlit as st
# import plotly.graph_objects as go
# class Breakout(Strategy):
#     n1 = 20  # Lookback period for high/low

#     def init(self):
#         self.highs = self.I(lambda x: pd.Series(x).rolling(self.n1).max(), self.data.High)
#         self.lows = self.I(lambda x: pd.Series(x).rolling(self.n1).min(), self.data.Low)

#     def next(self):
#         # If the price breaks the high, close any short and go long
#         if self.data.Close[-1] > self.highs[-2]:
#             self.position.close()
#             self.buy()
#         # If the price breaks the low, close any long and go short
#         elif self.data.Close[-1] < self.lows[-2]:
#             self.position.close()
#             self.sell()

# def run(ticker, start_date, end_date, cash=10_000, commission=.002, **kwargs):
#     hist_df = get_history(ticker, start_date, end_date)
#     if hist_df.empty:
#         return {"summary": {"Error": "Could not fetch historical data."}}

#     if isinstance(hist_df.columns, pd.MultiIndex):
#         hist_df.columns = hist_df.columns.get_level_values(0)
#     hist_df.columns = [col.title() for col in hist_df.columns]

#     Breakout.n1 = kwargs.get('lookback_period', 20)
#     bt = Backtest(hist_df, Breakout, cash=cash, commission=commission, finalize_trades=True)
#     stats = bt.run()
    
#     return {"summary": stats.to_dict()}

# # --- Streamlit Visualization (for standalone testing) ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="Breakout Strategy", layout="wide")
#     st.title("📈 Breakout Strategy Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "NVDA")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         lookback_period = st.slider("Lookback Period (days)", 10, 100, 20)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker}")
#         with st.spinner("Running backtest..."):
#             results = run(
#                 ticker=ticker, start_date=str(start_date.date()),
#                 end_date=str(end_date.date()), lookback_period=lookback_period
#             )
#             summary = results.get("summary", {})
#             backtest_df = results.get("data", pd.DataFrame())

#         if "Error" in summary:
#             st.error(summary["Error"])
#         elif not backtest_df.empty and 'Equity' in backtest_df.columns and 'Close' in backtest_df.columns:
#             st.subheader("Performance Summary")
#             cols = st.columns(4)
#             cols[0].metric("Return [%]", f"{summary.get('Return [%]', 0):.2f}")
#             cols[1].metric("Sharpe Ratio", f"{summary.get('Sharpe Ratio', 0):.2f}")
#             cols[2].metric("Max Drawdown [%]", f"{summary.get('Max. Drawdown [%]', 0):.2f}")
#             cols[3].metric("# Trades", summary.get('# Trades', 0))

#             st.subheader("Equity Curve & Price")
#             fig = go.Figure()
#             fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity'], name='Equity Curve', line=dict(color='purple')))
#             fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Close Price', yaxis='y2', line=dict(color='blue', dash='dash')))
#             fig.update_layout(
#                 title_text=f"{ticker} Equity Curve and Price",
#                 yaxis=dict(title="Equity ($)"),
#                 yaxis2=dict(title="Price ($)", overlaying='y', side='right')
#             )
#             st.plotly_chart(fig, use_container_width=True)
#         else:
#             st.warning("Backtest completed, but no trades were made or data could not be plotted.")

# import pandas as pd
# from utils.data_loader import get_history
# from backtesting import Backtest, Strategy
# import streamlit as st
# import plotly.graph_objects as go

# # --- Core Strategy Logic for backtesting.py ---

# import pandas as pd
# from utils.data_loader import get_history
# from backtesting import Backtest, Strategy

# def run(ticker, start_date, end_date, cash=10_000, commission=.002, **kwargs):
#     """
#     Runs a backtest for the Breakout strategy.
#     """
#     class BreakoutStrategy(Strategy):
#         n1 = 20  # Lookback period for the breakout high

#         def init(self):
#             # Pre-calculate the rolling high to use in the strategy
#             self.highs = self.I(lambda x: pd.Series(x).rolling(self.n1).max(), self.data.High)

#         def next(self):
#             # Entry signal: Buy if not in a position and the price breaks above the recent high
#             if not self.position and self.data.Close[-1] > self.highs[-2]:
#                 self.buy(size=0.2)  # Invest 20% of equity
#             # Exit signal: Sell if in a position and the price falls back below the recent high
#             elif self.position and self.data.Close[-1] < self.highs[-2]:
#                 self.position.close()

#     # 1. Fetch historical data
#     hist_df = get_history(ticker, start_date, end_date)
#     if hist_df.empty:
#         return {"summary": {"Error": "Could not fetch historical data."}, "data": pd.DataFrame()}
    
#     # 2. Fix DataFrame column names for the backtesting library
#     if isinstance(hist_df.columns, pd.MultiIndex):
#         hist_df.columns = hist_df.columns.get_level_values(0)
#     hist_df.columns = hist_df.columns.str.title()

#     # 3. Run the backtest
#     bt = Backtest(hist_df, BreakoutStrategy, cash=cash, commission=commission)
#     stats = bt.run()
    
#     # 4. Prepare the data for charting by merging price data with the equity curve
#     backtest_data = hist_df.join(stats._equity_curve)

#     # 5. Return the results
#     return {"summary": stats.to_dict(), "data": backtest_data}



# # --- Streamlit Visualization (for standalone testing) ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="Volume Breakout Strategy", layout="wide")
#     st.title("📈 Volume Breakout Strategy Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "NVDA")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         lookback_period = st.slider("Lookback Period (days)", 10, 100, 20)
#         volume_multiplier = st.slider("Volume Multiplier", 1.0, 3.0, 1.5, 0.1)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker}")
        
#         with st.spinner("Running backtest..."):
#             results = run(
#                 ticker=ticker,
#                 start_date=str(start_date.date()),
#                 end_date=str(end_date.date()),
#                 lookback_period=lookback_period,
#                 volume_multiplier=volume_multiplier
#             )
#             summary = results.get("summary", {})
#             backtest_df = results.get("data", pd.DataFrame())

#         if "Error" in summary:
#             st.error(summary["Error"])
#         elif not backtest_df.empty:
#             st.subheader("Performance Summary")
#             cols = st.columns(4)
#             cols[0].metric("Return [%]", f"{summary.get('Return [%]', 0):.2f}")
#             cols[1].metric("Sharpe Ratio", f"{summary.get('Sharpe Ratio', 0):.2f}")
#             cols[2].metric("Max Drawdown [%]", f"{summary.get('Max. Drawdown [%]', 0):.2f}")
#             cols[3].metric("# Trades", summary.get('# Trades', 0))

#             st.subheader("Equity Curve & Price")
#             fig = go.Figure()
#             # Plot the equity curve
#             fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity'], name='Equity Curve', line=dict(color='purple')))
#             # Plot the closing price on a secondary y-axis
#             fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Close Price', yaxis='y2', line=dict(color='blue', dash='dash')))
            
#             fig.update_layout(
#                 title_text=f"{ticker} Equity Curve and Price",
#                 xaxis_title="Date",
#                 yaxis=dict(title="Equity ($)"),
#                 yaxis2=dict(title="Price ($)", overlaying='y', side='right')
#             )
#             st.plotly_chart(fig, use_container_width=True)
#         else:
#             st.warning("Backtest did not produce any results.")