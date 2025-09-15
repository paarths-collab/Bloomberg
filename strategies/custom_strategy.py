import yfinance as yf
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
import ta

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
    plot_df['MACD_Line'] = ta.trend.macd(plot_df['Close'], window_fast=fast_period, window_slow=slow_period)
    plot_df['MACD_Signal'] = ta.trend.macd_signal(plot_df['Close'], window_fast=fast_period, window_slow=slow_period, window_sign=signal_period)
    plot_df['MACD_Hist'] = ta.trend.macd_diff(plot_df['Close'], window_fast=fast_period, window_slow=slow_period, window_sign=signal_period)
    
    trades = stats._trades
    
    return {"summary": summary, "data": plot_df, "trades": trades}

# --- Streamlit Visualization for Standalone Testing ---
if __name__ == "__main__":
    st.set_page_config(page_title="MACD Crossover Strategy", layout="wide")
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

                # --- Professional Charting with Subplots ---
                st.subheader("Price Chart with MACD, Trades & Equity")
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                    vertical_spacing=0.1, row_heights=[0.7, 0.3])

                # Top Panel: Price, Equity, and Trades
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')), row=1, col=1)
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')), row=1, col=1)
                
                buy_signals = trades_df[trades_df['Size'] > 0]
                sell_signals = trades_df[trades_df['Size'] < 0]
                fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['EntryPrice'], mode='markers', name='Buy Signal', marker=dict(color='lime', size=10, symbol='triangle-up')), row=1, col=1)
                fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['EntryPrice'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')), row=1, col=1)

                # Bottom Panel: MACD
                colors = ['green' if val >= 0 else 'red' for val in backtest_df['MACD_Hist']]
                fig.add_trace(go.Bar(x=backtest_df.index, y=backtest_df['MACD_Hist'], name='Histogram', marker_color=colors), row=2, col=1)
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['MACD_Line'], name='MACD Line', line=dict(color='blue')), row=2, col=1)
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['MACD_Signal'], name='Signal Line', line=dict(color='orange')), row=2, col=1)
                
                fig.update_layout(
                    title_text=f"{ticker} MACD Crossover Backtest",
                    xaxis_rangeslider_visible=False,
                    yaxis=dict(title="Price ($)"),
                    yaxis2=dict(title="Equity ($)", overlaying='y', side='right', showgrid=False)
                )
                fig.update_yaxes(title_text="MACD", row=2, col=1)
                st.plotly_chart(fig, use_container_width=True)
# import pandas as pd
# from utils.data_loader import get_history
# from backtesting import Backtest, Strategy
# from backtesting.lib import crossover
# import streamlit as st
# import plotly.graph_objects as go
# import ta

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
#         return {"summary": {"Error": "Could not fetch historical data."}, "data": pd.DataFrame()}

#     # Sanitize DataFrame columns to prevent errors with backtesting.py
#     if isinstance(hist_df.columns, pd.MultiIndex):
#         hist_df.columns = hist_df.columns.get_level_values(0)
#     hist_df.columns = [col.title() for col in hist_df.columns]

#     # Update strategy parameters from any provided kwargs
#     MacdCross.fast = kwargs.get('fast', 12)
#     MacdCross.slow = kwargs.get('slow', 26)
#     MacdCross.signal = kwargs.get('signal', 9)

#     # Instantiate and run the backtest, ensuring final trades are included
#     bt = Backtest(hist_df, MacdCross, cash=cash, commission=commission, finalize_trades=True)
#     stats = bt.run()
    
#     # Prepare data for plotting
#     plot_data = stats._equity_curve.copy()
#     if 'Close' in hist_df.columns:
#         plot_data = plot_data.join(hist_df['Close'])

#     return {"summary": stats.to_dict(), "data": plot_data}

# # --- Streamlit Visualization (for standalone testing) ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="MACD Crossover Strategy", layout="wide")
#     st.title("📈 MACD Crossover Strategy Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "GOOGL")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         fast_period = st.slider("Fast EMA Period", 5, 50, 12)
#         slow_period = st.slider("Slow EMA Period", 20, 100, 26)
#         signal_period = st.slider("Signal EMA Period", 5, 50, 9)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker}")
#         with st.spinner("Running backtest..."):
#             results = run(
#                 ticker=ticker, start_date=str(start_date.date()),
#                 end_date=str(end_date.date()), fast=fast_period,
#                 slow=slow_period, signal=signal_period
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
#             # Plot the equity curve on the primary y-axis
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
#             st.warning("Backtest completed, but no trades were made or data could not be plotted.")
# import pandas as pd
# import ta  # Corrected: Using the 'ta' library to avoid the conflict
# from utils.data_loader import get_history
# from backtesting import Backtest, Strategy
# import streamlit as st
# import plotly.graph_objects as go

# # --- Core Strategy Logic for backtesting.py ---

# def run(ticker, start_date, end_date, cash=10_000, commission=.002, rsi_lower=30, rsi_upper=70):
#     """
#     This function is the main entry point called by the orchestrator.
#     It runs the backtest using the backtesting.py library.
#     """
#     class CustomSmaRsi(Strategy):
#         # Pass the user-defined parameters to the strategy
#         rsi_lower_threshold = rsi_lower
#         rsi_upper_threshold = rsi_upper
#         sma_period = 50
#         rsi_period = 14

#         def init(self):
#             close = self.data.Close
#             # Use self.I to correctly define indicators for backtesting.py
#             self.sma = self.I(lambda x, n: pd.Series(x).rolling(n).mean(), close, self.sma_period)
#             # Use the correct function from the 'ta' library
#             self.rsi = self.I(ta.momentum.rsi, pd.Series(close), window=self.rsi_period)

#         def next(self):
#             price = self.data.Close[-1]
#             if not self.position:
#                 # Buy signal
#                 if self.rsi[-1] < self.rsi_lower_threshold and price > self.sma[-1]:
#                     self.buy()
#             # Sell signal
#             elif self.rsi[-1] > self.rsi_upper_threshold:
#                 self.position.close()

#     hist_df = get_history(ticker, start_date, end_date)
#     if hist_df.empty:
#         return {"summary": {"Error": "Could not fetch historical data."}, "data": pd.DataFrame()}
    
#     bt = Backtest(hist_df, CustomSmaRsi, cash=cash, commission=commission)
#     stats = bt.run()
    
#     # Return both the statistics and the backtest data for plotting
#     return {"summary": stats.to_dict(), "data": stats._equity_curve}

# # --- Streamlit Visualization (for standalone testing) ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="Custom Strategy Showcase", layout="wide")
#     st.title("📊 Custom Strategy (RSI + SMA) Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "NVDA")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         rsi_lower = st.slider("RSI Lower (Buy) Threshold", 10, 50, 30)
#         rsi_upper = st.slider("RSI Upper (Sell) Threshold", 50, 90, 70)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker}")
        
#         with st.spinner("Running backtest..."):
#             results = run(
#                 ticker=ticker,
#                 start_date=str(start_date.date()),
#                 end_date=str(end_date.date()),
#                 rsi_lower=rsi_lower,
#                 rsi_upper=rsi_upper
#             )
#             summary = results.get("summary", {})
#             equity_curve = results.get("data", pd.DataFrame())

#         if "Error" in summary:
#             st.error(summary["Error"])
#         elif not equity_curve.empty:
#             st.subheader("Performance Summary")
#             cols = st.columns(4)
#             cols[0].metric("Return [%]", f"{summary.get('Return [%]', 0):.2f}")
#             cols[1].metric("Sharpe Ratio", f"{summary.get('Sharpe Ratio', 0):.2f}")
#             cols[2].metric("Max Drawdown [%]", f"{summary.get('Max. Drawdown [%]', 0):.2f}")
#             cols[3].metric("# Trades", summary.get('# Trades', 0))

#             st.subheader("Equity Curve")
#             fig = go.Figure()
#             fig.add_trace(go.Scatter(x=equity_curve.index, y=equity_curve['Equity'], name='Equity Curve', line=dict(color='purple')))
#             fig.update_layout(
#                 title_text=f"{ticker} Equity Curve",
#                 xaxis_title="Date",
#                 yaxis_title="Equity ($)"
#             )
#             st.plotly_chart(fig, use_container_width=True)
#         else:
#             st.warning("Backtest did not produce any results.")


# import yfinance as yf
# import pandas as pd
# import numpy as np
# import streamlit as st
# import plotly.graph_objects as go
# from utils.data_loader import get_history, add_technical_indicators
# from backtesting import Backtest, Strategy
# import pandas_ta as ta

# # --- Core Strategy Logic ---
# def generate_signals(df, rsi_lower=40, rsi_upper=60):
#     """Define your custom entry/exit rules here: RSI + SMA filter."""
#     df['SMA_50'] = df['Close'].rolling(window=50).mean()
#     df['SMA_200'] = df['Close'].rolling(window=200).mean()

#     delta = df['Close'].diff()
#     gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
#     loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
#     rs = gain / loss
#     df['RSI'] = 100 - (100 / (1 + rs))

#     df['Signal'] = 0
#     df.loc[(df['RSI'] < rsi_lower) & (df['Close'] > df['SMA_50']), 'Signal'] = 1   # Buy
#     df.loc[(df['RSI'] > rsi_upper) & (df['Close'] < df['SMA_50']), 'Signal'] = -1  # Sell
#     return df

# def run_backtest(ticker, start_date, end_date, initial_capital=100000, rsi_lower=40, rsi_upper=60):
#     """Runs the full vectorized backtest and returns the DataFrame with all calculations."""
#     df = yf.download(ticker, start=start_date, end=end_date, progress=False)
#     if df.empty:
#         return pd.DataFrame()
        
#     df.dropna(inplace=True)
#     df = generate_signals(df, rsi_lower=rsi_lower, rsi_upper=rsi_upper)
    
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
#     class CustomSmaRsi(Strategy):
#         sma_period = 50
#         rsi_period = 14

#         def init(self):
#             close = self.data.Close
#             # Use self.I to define indicators
#             self.sma = self.I(lambda x, n: pd.Series(x).rolling(n).mean(), close, self.sma_period)
#             self.rsi = self.I(ta.rsi, pd.Series(close), length=self.rsi_period)

#         def next(self):
#             price = self.data.Close[-1]
#             if not self.position:
#                 if self.rsi[-1] < 30 and price > self.sma[-1]:
#                     self.buy()
#             elif self.rsi[-1] > 70:
#                 self.position.close()

#     hist_df = get_history(ticker, start_date, end_date)
#     if hist_df.empty: return {"error": "Could not fetch data."}
#     bt = Backtest(hist_df, CustomSmaRsi, cash=cash, commission=commission)
#     stats = bt.run()
#     return {"summary": stats.to_dict(), "plot": bt.plot(open_browser=False)}

# # --- Streamlit Visualization (Frontend Part) ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="Custom Strategy Showcase", layout="wide")
#     st.title("📊 Custom Strategy (RSI + SMA) Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "NVDA")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         rsi_lower = st.slider("RSI Lower Threshold", 10, 40, 40)
#         rsi_upper = st.slider("RSI Upper Threshold", 60, 90, 60)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker}")
        
#         with st.spinner("Running backtest..."):
#             results = run(ticker, str(start_date), str(end_date), rsi_lower=rsi_lower, rsi_upper=rsi_upper)
#             summary = results.get("summary", {})
#             backtest_df = results.get("data", pd.DataFrame())

#             if "Error" in summary:
#                 st.error(summary["Error"])
#             else:
#                 st.subheader("Performance Summary")
#                 cols = st.columns(4)
#                 cols[0].metric("Total Return", f"{summary.get('Total Return %', 0)}%")
#                 cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', 0))
#                 cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', 0)}%")
#                 cols[3].metric("Trades", summary.get('Number of Trades', 0))

#                 st.subheader("Price Chart with Signals & Equity Curve")
#                 fig = go.Figure()

#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='blue')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))

#                 buy_signals = backtest_df[backtest_df['Signal'] == 1]
#                 sell_signals = backtest_df[backtest_df['Signal'] == -1]
#                 fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'], mode='markers', name='Buy Signal', marker=dict(color='green', size=10, symbol='triangle-up')))
#                 fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['Close'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

#                 fig.update_layout(
#                     title_text=f"{ticker} Backtest: Custom Strategy",
#                     xaxis_rangeslider_visible=False,
#                     yaxis=dict(title="Price ($)"),
#                     yaxis2=dict(title="Equity ($)", overlaying='y', side='right')
#                 )
#                 st.plotly_chart(fig, use_container_width=True)