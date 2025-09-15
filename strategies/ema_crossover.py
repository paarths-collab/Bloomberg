# File: strategies/ema_crossover.py

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from backtesting import Backtest, Strategy
from backtesting.lib import crossover

# --- CORRECT: Import the single, centralized get_data function ---
from utils.data_loader import get_data
# --- Main Run Function (Callable by Portfolio Builder) ---
def run(ticker, start_date, end_date, initial_capital=100000, **kwargs):
    """ Main orchestrator function for the EMA Crossover strategy. """
    
    fast_period = kwargs.get('fast', 20)
    slow_period = kwargs.get('slow', 50)
    
    class EmaCross(Strategy):
        n1 = fast_period
        n2 = slow_period

        def init(self):
            self.ema1 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), self.data.Close, self.n1)
            self.ema2 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), self.data.Close, self.n2)

        def next(self):
            if crossover(self.ema1, self.ema2):
                self.buy()
            elif crossover(self.ema2, self.ema1):
                self.sell()

    hist_df = get_data(ticker, start_date, end_date)
    if hist_df.empty:
        return {"summary": {"Error": "Could not fetch data."}, "data": pd.DataFrame()}
    
    bt = Backtest(hist_df, EmaCross, cash=initial_capital, commission=.002)
    stats = bt.run(finalize_trades=True)

    summary = {
        "Total Return %": f"{stats['Return [%]']:.2f}",
        "Sharpe Ratio": f"{stats['Sharpe Ratio']:.2f}",
        "Max Drawdown %": f"{stats['Max. Drawdown [%]']:.2f}",
        "Number of Trades": stats['# Trades']
    }
    
    # --- Prepare detailed data for professional plotting ---
    plot_df = hist_df.copy()
    plot_df['Equity_Curve'] = stats._equity_curve['Equity']
    plot_df['EMA_Fast'] = plot_df['Close'].ewm(span=fast_period, adjust=False).mean()
    plot_df['EMA_Slow'] = plot_df['Close'].ewm(span=slow_period, adjust=False).mean()
    
    trades = stats._trades
    
    return {"summary": summary, "data": plot_df, "trades": trades}

# --- Streamlit UI for Standalone Testing ---
if __name__ == "__main__":
    st.set_page_config(page_title="EMA Crossover Backtester", layout="wide")
    st.title("📈 EMA Crossover Strategy (Standalone)")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "AAPL")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        
        st.header("Strategy Parameters")
        fast_period = st.slider("Fast EMA Period", 5, 100, 20)
        slow_period = st.slider("Slow EMA Period", 20, 300, 50)
        
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
                    slow=slow_period
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
                st.subheader("Price Chart with EMA Crossover, Trades & Equity")
                fig = go.Figure()

                # Price, EMAs, and Equity Curve
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Fast'], name=f'EMA {fast_period}', line=dict(color='green', dash='dash')))
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Slow'], name=f'EMA {slow_period}', line=dict(color='red', dash='dash')))
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))
                
                # Trade Markers
                buy_signals = trades_df[trades_df['Size'] > 0]
                sell_signals = trades_df[trades_df['Size'] < 0]
                fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['EntryPrice'], mode='markers', name='Buy Signal', marker=dict(color='lime', size=10, symbol='triangle-up')))
                fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['EntryPrice'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

                fig.update_layout(
                    title_text=f"{ticker} EMA Crossover Backtest ({fast_period}/{slow_period})",
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
# from backtesting.lib import crossover




# @st.cache_data
# def get_data(ticker, start, end):
#     """
#     Final, robust data fetching function for single-ticker backtests.
#     Correctly flattens the MultiIndex from yfinance and ensures OHLCV columns.
#     """
#     # Download data for a single ticker.
#     df = yf.download(ticker, start=start, end=end, progress=False)
#     if df.empty:
#         return pd.DataFrame()

#     # --- THIS IS THE CRITICAL FIX ---
#     # If yfinance returns a MultiIndex, flatten it to simple column names
#     if isinstance(df.columns, pd.MultiIndex):
#         df.columns = df.columns.droplevel(0)
#     # --- END OF FIX ---

#     # Standardize all column names to Title Case for backtesting.py compatibility
#     df.columns = [col.title() for col in df.columns]

#     # The backtesting library requires these specific column names.
#     df.rename(columns={
#         "Adj Close": "Adj_Close" # backtesting.py doesn't like spaces
#     }, inplace=True, errors='ignore')


#     # Ensure the essential columns exist, otherwise backtesting will fail.
#     required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
#     if not all(col in df.columns for col in required_cols):
#         # Return an empty DataFrame if the data is malformed
#         st.error(f"Data for {ticker} is missing required columns. Got: {df.columns.tolist()}")
#         return pd.DataFrame()

#     return df
# # --- Main Run Function (Callable by Portfolio Builder) ---
# def run(ticker, start_date, end_date, initial_capital=100000, **kwargs):
#     """ Main orchestrator function for the strategy. """
    
#     fast_period = kwargs.get('fast', 20)
#     slow_period = kwargs.get('slow', 50)
    
#     class EmaCross(Strategy):
#         n1 = fast_period
#         n2 = slow_period

#         def init(self):
#             self.ema1 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), self.data.Close, self.n1)
#             self.ema2 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), self.data.Close, self.n2)

#         def next(self):
#             if crossover(self.ema1, self.ema2): self.buy()
#             elif crossover(self.ema2, self.ema1): self.sell()

#     hist_df = get_data(ticker, start_date, end_date)
#     if hist_df.empty:
#         return {"summary": {"Error": "Could not fetch data."}, "data": pd.DataFrame()}
    
#     bt = Backtest(hist_df, EmaCross, cash=initial_capital, commission=.002)
#     stats = bt.run()

#     summary = {
#         "Total Return %": f"{stats['Return [%]']:.2f}",
#         "Sharpe Ratio": f"{stats['Sharpe Ratio']:.2f}",
#         "Max Drawdown %": f"{stats['Max. Drawdown [%]']:.2f}",
#         "Number of Trades": stats['# Trades']
#     }
    
#     plot_df = hist_df.copy()
#     plot_df['Equity_Curve'] = stats._equity_curve['Equity']
    
#     return {"summary": summary, "data": plot_df}

# # --- Streamlit UI for Standalone Testing ---
# # This part only runs when you execute this script directly
# if __name__ == "__main__":
#     st.set_page_config(page_title="EMA Crossover Backtester", layout="wide")
#     st.title("📈 EMA Crossover Strategy (Standalone)")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "AAPL")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         fast_period = st.slider("Fast EMA Period", 5, 100, 20)
#         slow_period = st.slider("Slow EMA Period", 20, 300, 50)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         if fast_period >= slow_period:
#             st.error("Error: Fast EMA period must be less than Slow EMA period.")
#         else:
#             st.header(f"Results for {ticker}")
            
#             with st.spinner("Running backtest..."):
#                 results = run(
#                     ticker=ticker, 
#                     start_date=start_date, 
#                     end_date=end_date, 
#                     fast=fast_period, 
#                     slow=slow_period
#                 )
#                 summary = results.get("summary", {})
#                 backtest_df = results.get("data", pd.DataFrame())

#             if "Error" in summary:
#                 st.error(summary["Error"])
#             elif not backtest_df.empty:
#                 st.subheader("Performance Summary")
#                 cols = st.columns(4)
#                 cols[0].metric("Total Return", f"{summary.get('Total Return %', '0.00')}%")
#                 cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', '0.00'))
#                 cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', '0.00')}%")
#                 cols[3].metric("Trades", summary.get('Number of Trades', 0))

#                 st.subheader("Equity Curve")
#                 fig = go.Figure()
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity'))
#                 st.plotly_chart(fig, use_container_width=True)




                #--------
# import pandas as pd
# import streamlit as st
# import plotly.graph_objects as go
# from backtesting import Backtest, Strategy
# from backtesting.lib import crossover


# def get_data(ticker, start, end, interval='1d'):
#     """
#     Fetches and prepares historical price data, ensuring correct column names.
#     """
#     df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
#     if df.empty:
#         return pd.DataFrame()
#     # Sanitize column names for backtesting.py compatibility
#     if isinstance(df.columns, pd.MultiIndex):
#         df.columns = df.columns.get_level_values(0)
#     df.columns = [col.title() for col in df.columns]
#     return df[['Open', 'High', 'Low', 'Close', 'Volume']]

# # --- Backtesting Engine and Strategy Definition ---

# def run(ticker, start_date, end_date, initial_capital=100000, fast=20, slow=50):
#     """
#     This function orchestrates the EMA Crossover backtest.
#     It is designed to be called by another module (like a portfolio engine) and requires
#     'fast' and 'slow' periods to be passed as arguments.
#     """
    
#     # 1. Define the Strategy Class dynamically to use the input parameters
#     class EmaCross(Strategy):
#         # Assign the dynamic parameters passed from the function call
#         n1 = fast
#         n2 = slow

#         def init(self):
#             self.ema1 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), self.data.Close, self.n1)
#             self.ema2 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), self.data.Close, self.n2)

#         def next(self):
#             if crossover(self.ema1, self.ema2):
#                 self.buy()
#             elif crossover(self.ema2, self.ema1):
#                 self.sell()

#     # 2. Fetch data using the helper function and run the backtest
#     hist_df = get_data(ticker, start_date, end_date)
#     if hist_df.empty:
#         return {"summary": {"Error": "Could not fetch data for the given ticker and date range."}, "data": pd.DataFrame()}
    
#     bt = Backtest(hist_df, EmaCross, cash=initial_capital, commission=.002)
#     stats = bt.run()

#     # 3. Prepare results for the frontend
#     summary = {
#         "Total Return %": f"{stats['Return [%]']:.2f}",
#         "Sharpe Ratio": f"{stats['Sharpe Ratio']:.2f}",
#         "Max Drawdown %": f"{stats['Max. Drawdown [%]']:.2f}",
#         "Number of Trades": stats['# Trades']
#     }

#     plot_df = hist_df.copy()
#     plot_df['Equity_Curve'] = stats._equity_curve['Equity']
#     plot_df['EMA_Fast'] = plot_df['Close'].ewm(span=fast, adjust=False).mean()
#     plot_df['EMA_Slow'] = plot_df['Close'].ewm(span=slow, adjust=False).mean()
    
#     trades = stats._trades
#     buy_signals = trades[trades['Size'] > 0]
#     sell_signals = trades[trades['Size'] < 0]
    
#     return {
#         "summary": summary, 
#         "data": plot_df,
#         "buy_signals": buy_signals,
#         "sell_signals": sell_signals
#     }

# # --- Streamlit Frontend (The User Interface) ---

# # This part only runs when you execute the script directly (e.g., "streamlit run ema_app.py")
# if __name__ == "__main__":
#     st.set_page_config(page_title="EMA Crossover Backtester", layout="wide")
#     st.title("📈 EMA Crossover Strategy Backtester")

#     # Sidebar for user inputs
#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "AAPL")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         fast_period = st.slider("Fast EMA Period", 5, 100, 20, help="The shorter-term trend line.")
#         slow_period = st.slider("Slow EMA Period", 20, 300, 50, help="The longer-term trend line.")
#         initial_capital = st.number_input("Initial Capital", 1000, 1000000, 100000)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     # Main content area
#     if run_button:
#         # Input validation
#         if fast_period >= slow_period:
#             st.error("Error: Fast EMA period must be less than Slow EMA period.")
#         else:
#             st.header(f"Results for {ticker}")
            
#             with st.spinner("Fetching data and running backtest..."):
#                 # Call the backtesting function with the inputs from the UI
#                 # FIX: Changed argument names to 'fast' and 'slow' to match the function definition
#                 results = run(
#                     ticker=ticker, 
#                     start_date=start_date, 
#                     end_date=end_date, 
#                     initial_capital=initial_capital,
#                     fast=fast_period, 
#                     slow=slow_period
#                 )
#                 summary = results.get("summary", {})
#                 backtest_df = results.get("data", pd.DataFrame())
#                 buy_signals = results.get("buy_signals", pd.DataFrame())
#                 sell_signals = results.get("sell_signals", pd.DataFrame())

#             # Display results
#             if "Error" in summary:
#                 st.error(summary["Error"])
#             elif not backtest_df.empty:
#                 st.subheader("Performance Summary")
#                 cols = st.columns(4)
#                 cols[0].metric("Total Return", f"{summary.get('Total Return %', '0.00')}%")
#                 cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', '0.00'))
#                 cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', '0.00')}%")
#                 cols[3].metric("Trades", summary.get('Number of Trades', 0))

#                 st.subheader("Price Chart with Signals & Equity Curve")
#                 fig = go.Figure()

#                 # Main Price and Equity Curve
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))
                
#                 # EMAs
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Fast'], name=f'EMA {fast_period}', line=dict(color='green', dash='dash')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Slow'], name=f'EMA {slow_period}', line=dict(color='red', dash='dash')))
                
#                 # Trade Markers
#                 fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['EntryPrice'], mode='markers', name='Buy Signal', marker=dict(color='lime', size=10, symbol='triangle-up')))
#                 fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['EntryPrice'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

#                 fig.update_layout(
#                     title_text=f"{ticker} Backtest: EMA Crossover ({fast_period}/{slow_period})",
#                     xaxis_rangeslider_visible=False,
#                     yaxis=dict(title="Price ($)"),
#                     yaxis2=dict(title="Equity ($)", overlaying='y', side='right', showgrid=False)
#                 )
#                 st.plotly_chart(fig, use_container_width=True)
#             else:
#                 st.warning("Backtest ran but did not produce any data.")
#     else:
#         st.info("Configure your backtest parameters in the sidebar and click 'Run Backtest'.")



        # --- IGNORE ---
# import yfinance as yf
# import pandas as pd
# import streamlit as st
# import plotly.graph_objects as go
# from backtesting import Backtest, Strategy
# from backtesting.lib import crossover


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

# # --- Backtesting Engine and Strategy Definition ---

# def run(ticker, start_date, end_date, initial_capital=100000, fast=20, slow=50, **kwargs):
#     """
#     This function orchestrates the EMA Crossover backtest.
#     It is designed to be called by another module (like a portfolio engine) and requires
#     'fast' and 'slow' periods to be passed as arguments.
#     """
    
#     # 1. Define the Strategy Class dynamically to use the input parameters
#     class EmaCross(Strategy):
#         # Assign the dynamic parameters passed from the function call
#         n1 = fast
#         n2 = slow

#         def init(self):
#             self.ema1 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), self.data.Close, self.n1)
#             self.ema2 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), self.data.Close, self.n2)

#         def next(self):
#             if crossover(self.ema1, self.ema2):
#                 self.buy()
#             elif crossover(self.ema2, self.ema1):
#                 self.sell()

#     # 2. Fetch data and run the backtest
#     hist_df = yf.download(ticker, start=start_date, end=end_date, progress=False)
#     if hist_df.empty:
#         return {"summary": {"Error": "Could not fetch data for the given ticker and date range."}, "data": pd.DataFrame()}
    
#     bt = Backtest(hist_df, EmaCross, cash=initial_capital, commission=.002)
#     stats = bt.run()

#     # 3. Prepare results for the frontend
#     summary = {
#         "Total Return %": f"{stats['Return [%]']:.2f}",
#         "Sharpe Ratio": f"{stats['Sharpe Ratio']:.2f}",
#         "Max Drawdown %": f"{stats['Max. Drawdown [%]']:.2f}",
#         "Number of Trades": stats['# Trades']
#     }

#     plot_df = hist_df.copy()
#     plot_df['Equity_Curve'] = stats._equity_curve['Equity']
#     plot_df['EMA_Fast'] = plot_df['Close'].ewm(span=fast, adjust=False).mean()
#     plot_df['EMA_Slow'] = plot_df['Close'].ewm(span=slow, adjust=False).mean()
    
#     trades = stats._trades
#     buy_signals = trades[trades['Size'] > 0]
#     sell_signals = trades[trades['Size'] < 0]
    
#     return {
#         "summary": summary, 
#         "data": plot_df,
#         "buy_signals": buy_signals,
#         "sell_signals": sell_signals
#     }
#             bt = Backtest(hist_df, EmaCross, cash=initial_capital, commission=.002)
#             stats = bt.run()

#             # 3. Prepare results for the frontend (Summary, Data for Plotting, and Trade Signals)
#             summary = {
#                 "Total Return %": f"{stats['Return [%]']:.2f}",
#                 "Sharpe Ratio": f"{stats['Sharpe Ratio']:.2f}",
#                 "Max Drawdown %": f"{stats['Max. Drawdown [%]']:.2f}",
#                 "Number of Trades": stats['# Trades']
#             }

#             plot_df = hist_df.copy()
#             plot_df['Equity_Curve'] = stats._equity_curve['Equity']
#             plot_df['EMA_Fast'] = plot_df['Close'].ewm(span=fast_period, adjust=False).mean()
#             plot_df['EMA_Slow'] = plot_df['Close'].ewm(span=slow_period, adjust=False).mean()
            
#             trades = stats._trades
#             buy_signals = trades[trades['Size'] > 0]
#             sell_signals = trades[trades['Size'] < 0]
            
#             return {
#                 "summary": summary, 
#                 "data": plot_df,
#                 "buy_signals": buy_signals,
#                 "sell_signals": sell_signals
#             }

# # --- Streamlit Frontend (The User Interface) ---

# # This part only runs when you execute the script directly (e.g., "streamlit run ema_app.py")
# if __name__ == "__main__":
#     st.set_page_config(page_title="EMA Crossover Backtester", layout="wide")
#     st.title("📈 EMA Crossover Strategy Backtester")

#     # Sidebar for user inputs
#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "AAPL")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         fast_period = st.slider("Fast EMA Period", 5, 100, 20, help="The shorter-term trend line.")
#         slow_period = st.slider("Slow EMA Period", 20, 300, 50, help="The longer-term trend line.")
#         initial_capital = st.number_input("Initial Capital", 1000, 1000000, 100000)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     # Main content area
#     if run_button:
#         # Input validation
#         if fast_period >= slow_period:
#             st.error("Error: Fast EMA period must be less than Slow EMA period.")
#         else:
#             st.header(f"Results for {ticker}")
            
#             with st.spinner("Fetching data and running backtest..."):
#                 # Call the backtesting function with the inputs from the UI
#                 results = run(
#                     ticker=ticker, 
#                     start_date=start_date, 
#                     end_date=end_date, 
#                     initial_capital=initial_capital,
#                     fast_period=fast_period, 
#                     slow_period=slow_period
#                 )
#                 summary = results.get("summary", {})
#                 backtest_df = results.get("data", pd.DataFrame())
#                 buy_signals = results.get("buy_signals", pd.DataFrame())
#                 sell_signals = results.get("sell_signals", pd.DataFrame())

#             # Display results
#             if "Error" in summary:
#                 st.error(summary["Error"])
#             elif not backtest_df.empty:
#                 st.subheader("Performance Summary")
#                 cols = st.columns(4)
#                 cols[0].metric("Total Return", f"{summary.get('Total Return %', '0.00')}%")
#                 cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', '0.00'))
#                 cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', '0.00')}%")
#                 cols[3].metric("Trades", summary.get('Number of Trades', 0))

#                 st.subheader("Price Chart with Signals & Equity Curve")
#                 fig = go.Figure()

#                 # Main Price and Equity Curve
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))
                
#                 # EMAs
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Fast'], name=f'EMA {fast_period}', line=dict(color='green', dash='dash')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Slow'], name=f'EMA {slow_period}', line=dict(color='red', dash='dash')))
                
#                 # Trade Markers
#                 fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['EntryPrice'], mode='markers', name='Buy Signal', marker=dict(color='lime', size=10, symbol='triangle-up')))
#                 fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['EntryPrice'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

#                 fig.update_layout(
#                     title_text=f"{ticker} Backtest: EMA Crossover ({fast_period}/{slow_period})",
#                     xaxis_rangeslider_visible=False,
#                     yaxis=dict(title="Price ($)"),
#                     yaxis2=dict(title="Equity ($)", overlaying='y', side='right', showgrid=False)
#                 )
#                 st.plotly_chart(fig, use_container_width=True)
#             else:
#                 st.warning("Backtest ran but did not produce any data.")
#     else:
#         st.info("Configure your backtest parameters in the sidebar and click 'Run Backtest'.")

# import yfinance as yf
# import pandas as pd
# import streamlit as st
# import plotly.graph_objects as go
# from backtesting import Backtest, Strategy
# from backtesting.lib import crossover

# # --- Combined Orchestrator & Backtesting Engine ---

# def run(ticker, start_date, end_date, initial_capital=100000, fast=20, slow=50, **kwargs):
#     """
#     This function orchestrates the entire backtesting process using the backtesting.py library,
#     prepares the results for the Streamlit frontend, and accepts dynamic EMA parameters.
    
#     MODIFICATION: The function signature was changed from using **kwargs.get('fast')
#     to explicitly defining 'fast' and 'slow' as keyword arguments with default values.
#     This resolves the TypeError from external calls and makes the function's expected inputs clearer.
#     """
    
#     # 1. Define the Strategy Class within the run function to capture the parameters
#     class EmaCross(Strategy):
#         # Assign the dynamic parameters directly from the function arguments
#         n1 = fast
#         n2 = slow

#         def init(self):
#             # Pre-calculate the two moving averages
#             self.ema1 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), self.data.Close, self.n1)
#             self.ema2 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), self.data.Close, self.n2)

#         def next(self):
#             # If fast EMA crosses above slow EMA, buy
#             if crossover(self.ema1, self.ema2):
#                 self.buy()
#             # Else, if slow EMA crosses above fast EMA, sell
#             elif crossover(self.ema2, self.ema1):
#                 self.sell()

#     # 2. Fetch data and run the backtest
#     hist_df = yf.download(ticker, start=start_date, end=end_date, progress=False)
#     if hist_df.empty:
#         return {"summary": {"Error": "Could not fetch data."}, "data": pd.DataFrame()}
    
#     bt = Backtest(hist_df, EmaCross, cash=initial_capital, commission=.002)
#     stats = bt.run()

#     # 3. Prepare results for the frontend (Summary and Data for Plotting)
#     summary = {
#         "Total Return %": f"{stats['Return [%]']:.2f}",
#         "Sharpe Ratio": f"{stats['Sharpe Ratio']:.2f}",
#         "Max Drawdown %": f"{stats['Max. Drawdown [%]']:.2f}",
#         "Number of Trades": stats['# Trades']
#     }

#     # Reconstruct a DataFrame for Plotly visualization
#     plot_df = hist_df.copy()
#     plot_df['Equity_Curve'] = stats._equity_curve['Equity']
    
#     # Recalculate EMAs for plotting on the main price chart
#     plot_df['EMA_Fast'] = plot_df['Close'].ewm(span=fast, adjust=False).mean()
#     plot_df['EMA_Slow'] = plot_df['Close'].ewm(span=slow, adjust=False).mean()
    
#     # Extract trade signals for plotting markers
#     trades = stats._trades
#     buy_signals = trades[trades['Size'] > 0]
#     sell_signals = trades[trades['Size'] < 0]
    
#     # We return the data in three parts: summary, data for the chart, and trade markers
#     return {
#         "summary": summary, 
#         "data": plot_df,
#         "buy_signals": buy_signals,
#         "sell_signals": sell_signals
#     }

# # --- Streamlit Visualization (Frontend Part) ---

# if __name__ == "__main__":
#     st.set_page_config(page_title="EMA Crossover Strategy", layout="wide")
#     st.title("📈 EMA Crossover Strategy Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "TSLA")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         fast_period = st.slider("Fast EMA Period", 5, 100, 20)
#         slow_period = st.slider("Slow EMA Period", 20, 300, 50)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         if fast_period >= slow_period:
#             st.error("Error: Fast EMA period must be less than Slow EMA period.")
#         else:
#             st.header(f"Results for {ticker}")
            
#             with st.spinner("Running backtest..."):
#                 # The UI calls the unified 'run' function with the dynamic parameters
#                 # This call remains unchanged and works with the new function signature
#                 results = run(
#                     ticker=ticker, 
#                     start_date=str(start_date.date()), 
#                     end_date=str(end_date.date()), 
#                     fast=fast_period, 
#                     slow=slow_period
#                 )
#                 summary = results.get("summary", {})
#                 backtest_df = results.get("data", pd.DataFrame())
#                 buy_signals = results.get("buy_signals", pd.DataFrame())
#                 sell_signals = results.get("sell_signals", pd.DataFrame())

#             if "Error" in summary:
#                 st.error(summary["Error"])
#             elif not backtest_df.empty:
#                 st.subheader("Performance Summary")
#                 cols = st.columns(4)
#                 cols[0].metric("Total Return", f"{summary.get('Total Return %', '0.00')}%")
#                 cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', '0.00'))
#                 cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', '0.00')}%")
#                 cols[3].metric("Trades", summary.get('Number of Trades', 0))

#                 st.subheader("Price Chart with Signals & Equity Curve")
#                 fig = go.Figure()

#                 # Main Price and Equity Curve
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))
                
#                 # EMAs
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Fast'], name=f'EMA {fast_period}', line=dict(color='green', dash='dash')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Slow'], name=f'EMA {slow_period}', line=dict(color='red', dash='dash')))
                
#                 # Trade Markers
#                 fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['EntryPrice'], mode='markers', name='Buy Signal', marker=dict(color='lime', size=10, symbol='triangle-up')))
#                 fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['EntryPrice'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

#                 fig.update_layout(
#                     title_text=f"{ticker} Backtest: EMA Crossover ({fast_period}/{slow_period})",
#                     xaxis_rangeslider_visible=False,
#                     yaxis=dict(title="Price ($)"),
#                     yaxis2=dict(title="Equity ($)", overlaying='y', side='right', showgrid=False)
#                 )
#                 st.plotly_chart(fig, use_container_width=True)
#             else:
#                 st.warning("Backtest ran but did not produce any data.")

# # import yfinance as yf
# # import pandas as pd
# # import streamlit as st
# # import plotly.graph_objects as go
# # from backtesting import Backtest, Strategy
# # from backtesting.lib import crossover

# # # --- Combined Orchestrator & Backtesting Engine ---

# # def run(ticker, start_date, end_date, initial_capital=100000, **kwargs):
# #     """
# #     This function orchestrates the entire backtesting process using the backtesting.py library,
# #     prepares the results for the Streamlit frontend, and accepts dynamic EMA parameters.
# #     """
# #     # 1. Get dynamic EMA parameters from kwargs, with defaults
# #     fast_period = kwargs.get('fast', 20)
# #     slow_period = kwargs.get('slow', 50)

# #     # 2. Define the Strategy Class within the run function to capture the parameters
# #     class EmaCross(Strategy):
# #         # Assign the dynamic parameters to the class
# #         n1 = fast_period
# #         n2 = slow_period

# #         def init(self):
# #             # Pre-calculate the two moving averages
# #             self.ema1 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), self.data.Close, self.n1)
# #             self.ema2 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), self.data.Close, self.n2)

# #         def next(self):
# #             # If fast EMA crosses above slow EMA, buy
# #             if crossover(self.ema1, self.ema2):
# #                 self.buy()
# #             # Else, if slow EMA crosses above fast EMA, sell
# #             elif crossover(self.ema2, self.ema1):
# #                 self.sell()

# #     # 3. Fetch data and run the backtest
# #     hist_df = yf.download(ticker, start=start_date, end=end_date, progress=False)
# #     if hist_df.empty:
# #         return {"summary": {"Error": "Could not fetch data."}, "data": pd.DataFrame()}
    
# #     bt = Backtest(hist_df, EmaCross, cash=initial_capital, commission=.002)
# #     stats = bt.run()

# #     # 4. Prepare results for the frontend (Summary and Data for Plotting)
# #     summary = {
# #         "Total Return %": f"{stats['Return [%]']:.2f}",
# #         "Sharpe Ratio": f"{stats['Sharpe Ratio']:.2f}",
# #         "Max Drawdown %": f"{stats['Max. Drawdown [%]']:.2f}",
# #         "Number of Trades": stats['# Trades']
# #     }

# #     # Reconstruct a DataFrame for Plotly visualization
# #     plot_df = hist_df.copy()
# #     plot_df['Equity_Curve'] = stats._equity_curve['Equity']
    
# #     # Recalculate EMAs for plotting on the main price chart
# #     plot_df['EMA_Fast'] = plot_df['Close'].ewm(span=fast_period, adjust=False).mean()
# #     plot_df['EMA_Slow'] = plot_df['Close'].ewm(span=slow_period, adjust=False).mean()
    
# #     # Extract trade signals for plotting markers
# #     trades = stats._trades
# #     buy_signals = trades[trades['Size'] > 0]
# #     sell_signals = trades[trades['Size'] < 0]
    
# #     # We return the data in three parts: summary, data for the chart, and trade markers
# #     return {
# #         "summary": summary, 
# #         "data": plot_df,
# #         "buy_signals": buy_signals,
# #         "sell_signals": sell_signals
# #     }

# # --- Streamlit Visualization (Frontend Part) ---

# if __name__ == "__main__":
#     st.set_page_config(page_title="EMA Crossover Strategy", layout="wide")
#     st.title("📈 EMA Crossover Strategy Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "TSLA")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         fast_period = st.slider("Fast EMA Period", 5, 100, 20)
#         slow_period = st.slider("Slow EMA Period", 20, 300, 50)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         if fast_period >= slow_period:
#             st.error("Error: Fast EMA period must be less than Slow EMA period.")
#         else:
#             st.header(f"Results for {ticker}")
            
#             with st.spinner("Running backtest..."):
#                 # The UI calls the unified 'run' function with the dynamic parameters
#                 results = run(
#                     ticker=ticker, 
#                     start_date=str(start_date.date()), 
#                     end_date=str(end_date.date()), 
#                     fast=fast_period, 
#                     slow=slow_period
#                 )
#                 summary = results.get("summary", {})
#                 backtest_df = results.get("data", pd.DataFrame())
#                 buy_signals = results.get("buy_signals", pd.DataFrame())
#                 sell_signals = results.get("sell_signals", pd.DataFrame())


#             if "Error" in summary:
#                 st.error(summary["Error"])
#             elif not backtest_df.empty:
#                 st.subheader("Performance Summary")
#                 cols = st.columns(4)
#                 cols[0].metric("Total Return", f"{summary.get('Total Return %', '0.00')}%")
#                 cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', '0.00'))
#                 cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', '0.00')}%")
#                 cols[3].metric("Trades", summary.get('Number of Trades', 0))

#                 st.subheader("Price Chart with Signals & Equity Curve")
#                 fig = go.Figure()

#                 # Main Price and Equity Curve
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))
                
#                 # EMAs
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Fast'], name=f'EMA {fast_period}', line=dict(color='green', dash='dash')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Slow'], name=f'EMA {slow_period}', line=dict(color='red', dash='dash')))
                
#                 # Trade Markers
#                 fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['EntryPrice'], mode='markers', name='Buy Signal', marker=dict(color='lime', size=10, symbol='triangle-up')))
#                 fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['EntryPrice'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

#                 fig.update_layout(
#                     title_text=f"{ticker} Backtest: EMA Crossover ({fast_period}/{slow_period})",
#                     xaxis_rangeslider_visible=False,
#                     yaxis=dict(title="Price ($)"),
#                     yaxis2=dict(title="Equity ($)", overlaying='y', side='right', showgrid=False)
#                 )
#                 st.plotly_chart(fig, use_container_width=True)
#             else:
#                 st.warning("Backtest ran but did not produce any data.")


# ----------------------------------------------------
#  import yfinance as yf
# import pandas as pd
# import numpy as np
# import streamlit as st
# import plotly.graph_objects as go

# # --- Core Strategy & Backtesting Logic ---

# def run_backtest(ticker, start_date, end_date, fast=20, slow=50, initial_capital=100000):
#     """Runs the full vectorized backtest for the EMA Crossover strategy."""
#     df = yf.download(ticker, start=start_date, end=end_date, progress=False)
#     if df.empty:
#         return pd.DataFrame()
        
#     df.dropna(inplace=True)

#     df['EMA_Fast'] = df['Close'].ewm(span=fast, adjust=False).mean()
#     df['EMA_Slow'] = df['Close'].ewm(span=slow, adjust=False).mean()

#     # Determine the signal: 1 for long, 0 for cash
#     df['Signal'] = 0
#     df.loc[df['EMA_Fast'] > df['EMA_Slow'], 'Signal'] = 1
    
#     # Determine the position based on the previous day's signal to avoid lookahead bias
#     df['Position'] = df['Signal'].shift(1).fillna(0)

#     # Calculate strategy returns and the equity curve
#     df['Strategy_Returns'] = df['Position'] * df['Close'].pct_change()
#     df['Equity_Curve'] = (1 + df['Strategy_Returns']).cumprod() * initial_capital
#     return df

# def calculate_performance_metrics(backtest_df, initial_capital):
#     """Calculates a dictionary of key trading metrics."""
#     if backtest_df.empty or 'Equity_Curve' not in backtest_df:
#         return {}

#     final_equity = backtest_df['Equity_Curve'].iloc[-1]
#     total_return_pct = (final_equity / initial_capital - 1) * 100
    
#     daily_returns = backtest_df['Strategy_Returns'].dropna()
#     sharpe_ratio = np.sqrt(252) * daily_returns.mean() / daily_returns.std() if daily_returns.std() != 0 else 0
    
#     peak = backtest_df['Equity_Curve'].cummax()
#     drawdown = (backtest_df['Equity_Curve'] - peak) / peak
#     max_drawdown_pct = drawdown.min() * 100

#     # A trade occurs every time the position changes
#     trades = backtest_df[backtest_df['Position'] != backtest_df['Position'].shift(1)]
#     num_trades = len(trades)
    
#     return {
#         "Total Return %": f"{total_return_pct:.2f}",
#         "Sharpe Ratio": f"{sharpe_ratio:.2f}",
#         "Max Drawdown %": f"{max_drawdown_pct:.2f}",
#         "Number of Trades": num_trades
#     }

# # --- Orchestrator/API Entry Point ---

# def run(ticker, start_date, end_date, fast, slow, initial_capital=100000):
#     """
#     This function orchestrates the entire backtesting process and prepares
#     the results for the Streamlit frontend.
#     """
#     backtest_df = run_backtest(ticker, start_date, end_date, fast, slow, initial_capital)
    
#     if backtest_df.empty:
#         return {"summary": {"Error": "Could not fetch data."}, "data": pd.DataFrame()}

#     summary = calculate_performance_metrics(backtest_df, initial_capital)
    
#     return {"summary": summary, "data": backtest_df}

# # --- Streamlit Visualization (Frontend Part) ---

# if __name__ == "__main__":
#     st.set_page_config(page_title="EMA Crossover Strategy", layout="wide")
#     st.title("📈 EMA Crossover Strategy Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "TSLA")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         fast_period = st.slider("Fast EMA Period", 5, 100, 20)
#         slow_period = st.slider("Slow EMA Period", 20, 300, 50)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         if fast_period >= slow_period:
#             st.error("Error: Fast EMA period must be less than Slow EMA period.")
#         else:
#             st.header(f"Results for {ticker}")
            
#             with st.spinner("Running backtest..."):
#                 # The UI now calls the correct, unified 'run' function
#                 results = run(
#                     ticker=ticker, 
#                     start_date=str(start_date.date()), 
#                     end_date=str(end_date.date()), 
#                     fast=fast_period, 
#                     slow=slow_period
#                 )
#                 summary = results.get("summary", {})
#                 backtest_df = results.get("data", pd.DataFrame())

#             if "Error" in summary:
#                 st.error(summary["Error"])
#             elif not backtest_df.empty:
#                 st.subheader("Performance Summary")
#                 cols = st.columns(4)
#                 cols[0].metric("Total Return", f"{summary.get('Total Return %', '0.00')}%")
#                 cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', '0.00'))
#                 cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', '0.00')}%")
#                 cols[3].metric("Trades", summary.get('Number of Trades', 0))

#                 st.subheader("Price Chart with Signals & Equity Curve")
#                 fig = go.Figure()

#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Fast'], name=f'EMA {fast_period}', line=dict(color='green', dash='dash')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Slow'], name=f'EMA {slow_period}', line=dict(color='red', dash='dash')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))

#                 # Correctly identify trade execution points for plotting
#                 buy_signals = backtest_df[(backtest_df['Position'] == 1) & (backtest_df['Position'].shift(1) == 0)]
#                 sell_signals = backtest_df[(backtest_df['Position'] == 0) & (backtest_df['Position'].shift(1) == 1)]
                
#                 fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'], mode='markers', name='Buy Signal', marker=dict(color='lime', size=10, symbol='triangle-up')))
#                 fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['Close'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

#                 fig.update_layout(
#                     title_text=f"{ticker} Backtest: EMA Crossover",
#                     xaxis_rangeslider_visible=False,
#                     yaxis=dict(title="Price ($)"),
#                     yaxis2=dict(title="Equity ($)", overlaying='y', side='right', showgrid=False)
#                 )
#                 st.plotly_chart(fig, use_container_width=True)
#             else:
#                 st.warning("Backtest ran but did not produce any data.")
# import yfinance as yf
# import pandas as pd
# import numpy as np
# import streamlit as st
# import plotly.graph_objects as go
# from utils.data_loader import get_history
# from backtesting import Backtest, Strategy
# from backtesting.lib import crossover
# # --- Core Strategy & Backtesting Logic ---

# def run_backtest(ticker, start_date, end_date, fast=20, slow=50, initial_capital=100000):
#     """Runs the full vectorized backtest for the EMA Crossover strategy."""
#     df = yf.download(ticker, start=start_date, end=end_date, progress=False)
#     if df.empty:
#         return pd.DataFrame()
        
#     df.dropna(inplace=True)

#     df['EMA_Fast'] = df['Close'].ewm(span=fast, adjust=False).mean()
#     df['EMA_Slow'] = df['Close'].ewm(span=slow, adjust=False).mean()

#     df['Signal'] = 0
#     df.loc[df['EMA_Fast'] > df['EMA_Slow'], 'Signal'] = 1
#     df['Position'] = df['Signal'].shift(1).fillna(0)

#     df['Strategy_Returns'] = df['Position'] * df['Close'].pct_change()
#     df['Equity_Curve'] = (1 + df['Strategy_Returns']).cumprod() * initial_capital
#     return df

# def calculate_performance_metrics(backtest_df, initial_capital):
#     """Calculates a dictionary of professional trading metrics."""
#     if backtest_df.empty:
#         return {}

#     final_equity = backtest_df['Equity_Curve'].iloc[-1]
#     total_return_pct = (final_equity / initial_capital - 1) * 100
    
#     daily_returns = backtest_df['Strategy_Returns'].dropna()
#     sharpe_ratio = np.sqrt(252) * daily_returns.mean() / daily_returns.std() if daily_returns.std() != 0 else 0
    
#     peak = backtest_df['Equity_Curve'].cummax()
#     drawdown = (backtest_df['Equity_Curve'] - peak) / peak
#     max_drawdown_pct = drawdown.min() * 100

#     trades = backtest_df[backtest_df['Signal'] != backtest_df['Signal'].shift(1)]
    
#     return {
#         "Total Return %": f"{total_return_pct:.2f}",
#         "Sharpe Ratio": f"{sharpe_ratio:.2f}",
#         "Max Drawdown %": f"{max_drawdown_pct:.2f}",
#         "Number of Trades": len(trades)
#     }

# # --- Orchestrator/API Entry Point ---


# def run(ticker, start_date, end_date, cash=10_000, commission=.002):
#     class EmaCross(Strategy):
#         n1 = 20
#         n2 = 50

#         def init(self):
#             close = self.data.Close
#             self.ema1 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), close, self.n1)
#             self.ema2 = self.I(lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean(), close, self.n2)

#         def next(self):
#             if crossover(self.ema1, self.ema2):
#                 self.buy()
#             elif crossover(self.ema2, self.ema1):
#                 self.sell()

#     hist_df = get_history(ticker, start_date, end_date)
#     if hist_df.empty: return {"error": "Could not fetch data."}
#     bt = Backtest(hist_df, EmaCross, cash=cash, commission=commission)
#     stats = bt.run()
#     return {"summary": stats.to_dict(), "plot": bt.plot(open_browser=False)}

# # --- Streamlit Visualization (Frontend Part) ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="EMA Crossover Strategy", layout="wide")
#     st.title("📈 EMA Crossover Strategy Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "TSLA")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         fast_period = st.slider("Fast EMA Period", 5, 100, 20)
#         slow_period = st.slider("Slow EMA Period", 20, 300, 50)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         if fast_period >= slow_period:
#             st.error("Error: Fast EMA period must be less than Slow EMA period.")
#         else:
#             st.header(f"Results for {ticker}")
            
#             with st.spinner("Running backtest..."):
#                 results = run(ticker, str(start_date), str(end_date), fast=fast_period, slow=slow_period)
#                 summary = results.get("summary", {})
#                 backtest_df = results.get("data", pd.DataFrame())

#                 if "Error" in summary:
#                     st.error(summary["Error"])
#                 else:
#                     st.subheader("Performance Summary")
#                     cols = st.columns(4)
#                     cols[0].metric("Total Return", f"{summary.get('Total Return %', 0)}%")
#                     cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', 0))
#                     cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', 0)}%")
#                     cols[3].metric("Trades", summary.get('Number of Trades', 0))

#                     st.subheader("Price Chart with Signals & Equity Curve")
#                     fig = go.Figure()

#                     fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
#                     fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Fast'], name=f'EMA {fast_period}', line=dict(color='green', dash='dash')))
#                     fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['EMA_Slow'], name=f'EMA {slow_period}', line=dict(color='red', dash='dash')))
#                     fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))

#                     buy_signals = backtest_df[(backtest_df['Signal'] == 1) & (backtest_df['Signal'].shift(1) == 0)]
#                     sell_signals = backtest_df[(backtest_df['Signal'] == 0) & (backtest_df['Signal'].shift(1) == 1)]
#                     fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'], mode='markers', name='Buy Signal', marker=dict(color='green', size=10, symbol='triangle-up')))
#                     fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['Close'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

#                     fig.update_layout(
#                         title_text=f"{ticker} Backtest: EMA Crossover",
#                         xaxis_rangeslider_visible=False,
#                         yaxis=dict(title="Price ($)"),
#                         yaxis2=dict(title="Equity ($)", overlaying='y', side='right')
#                     )
#                     st.plotly_chart(fig, use_container_width=True)