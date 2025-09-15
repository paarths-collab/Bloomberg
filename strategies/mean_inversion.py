# File: strategies/mean_inversion.py

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from backtesting import Backtest, Strategy
import ta

# --- CORRECT: Import the single, centralized get_data function ---
from utils.data_loader import get_data

# --- Main Run Function (Callable by Portfolio Builder) ---
def run(ticker: str, start_date: str, end_date: str, initial_capital=100000, **kwargs) -> dict:
    """ Main orchestrator function for the Mean Reversion strategy. """
    
    window_period = kwargs.get("window", 20)
    std_devs = kwargs.get("num_std", 2.0)
    
    class MeanReversion(Strategy):
        window = window_period
        num_std = std_devs

        def init(self):
            close = pd.Series(self.data.Close)
            self.ma = self.I(ta.trend.sma_indicator, close, window=self.window)
            rolling_std = self.I(lambda x, n: pd.Series(x).rolling(n).std(), close, self.window)
            self.upper_band = self.ma + (rolling_std * self.num_std)
            self.lower_band = self.ma - (rolling_std * self.num_std)

        def next(self):
            if not self.position and self.data.Close[-1] < self.lower_band[-1]:
                self.buy()
            elif self.position and self.data.Close[-1] > self.ma[-1]:
                self.position.close()

    # --- CORRECT: Call the centralized get_data function ---
    hist_df = get_data(ticker, start_date, end_date)
    if hist_df.empty:
        return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}

    bt = Backtest(hist_df, MeanReversion, cash=initial_capital, commission=.002)
    stats = bt.run(finalize_trades=True)
    
    summary = {
        "Total Return %": f"{stats['Return [%]']:.2f}",
        "Sharpe Ratio": f"{stats['Sharpe Ratio']:.2f}",
        "Max Drawdown %": f"{stats['Max. Drawdown [%]']:.2f}",
        "Number of Trades": stats['# Trades']
    }
    
    plot_df = hist_df.copy()
    plot_df['Equity_Curve'] = stats._equity_curve['Equity']
    plot_df['MA'] = plot_df['Close'].rolling(window_period).mean()
    plot_df['STD'] = plot_df['Close'].rolling(window_period).std()
    plot_df['Upper_Band'] = plot_df['MA'] + (plot_df['STD'] * std_devs)
    plot_df['Lower_Band'] = plot_df['MA'] - (plot_df['STD'] * std_devs)
    
    trades = stats._trades
    
    return {"summary": summary, "data": plot_df, "trades": trades}

# --- Streamlit UI for Standalone Testing ---
if __name__ == "__main__":
    st.set_page_config(page_title="Mean Reversion Strategy", layout="wide")
    st.title("📈 Mean Reversion Strategy (Standalone)")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "BTC-USD")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        
        st.header("Strategy Parameters")
        window = st.slider("Moving Average Window", 10, 100, 20)
        num_std = st.slider("Number of Standard Deviations", 1.0, 3.0, 2.0, 0.1)
        
        run_button = st.button("🔬 Run Backtest", use_container_width=True)

    if run_button:
        st.header(f"Results for {ticker}")
        with st.spinner("Running backtest..."):
            results = run(
                ticker=ticker, 
                start_date=start_date, 
                end_date=end_date, 
                window=window, 
                num_std=num_std
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

                st.subheader("Price Chart with Bollinger Bands, Trades & Equity")
                fig = go.Figure()

                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Upper_Band'], name='Upper Band', line=dict(color='orange', dash='dash')))
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Lower_Band'], name='Lower Band', line=dict(color='orange', dash='dash')))
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))
                
                buy_signals = trades_df[trades_df['Size'] > 0]
                sell_signals = trades_df[trades_df['Size'] < 0]
                fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['EntryPrice'], mode='markers', name='Buy Signal', marker=dict(color='lime', size=10, symbol='triangle-up')))
                fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['EntryPrice'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

                fig.update_layout(
                    title_text=f"{ticker} Mean Reversion Backtest",
                    yaxis=dict(title="Price ($)"),
                    yaxis2=dict(title="Equity ($)", overlaying='y', side='right', showgrid=False)
                )
                st.plotly_chart(fig, use_container_width=True)
# import yfinance as yf
# import pandas as pd
# import streamlit as st
# import plotly.graph_objects as go
# from backtesting import Backtest, Strategy
# import ta # Make sure you have the 'ta' library installed (pip install ta)
# from utils.data_loader import get_data

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
#     """ Main orchestrator function for the Mean Reversion strategy. """
    
#     window_period = kwargs.get("window", 20)
#     std_devs = kwargs.get("num_std", 2.0)
    
#     class MeanReversion(Strategy):
#         window = window_period
#         num_std = std_devs

#         def init(self):
#             close = pd.Series(self.data.Close)
#             self.ma = self.I(ta.trend.sma_indicator, close, window=self.window)
#             rolling_std = self.I(lambda x, n: pd.Series(x).rolling(n).std(), close, self.window)
#             self.upper_band = self.ma + (rolling_std * self.num_std)
#             self.lower_band = self.ma - (rolling_std * self.num_std)

#         def next(self):
#             if not self.position and self.data.Close[-1] < self.lower_band[-1]:
#                 self.buy()
#             elif self.position and self.data.Close[-1] > self.ma[-1]:
#                 self.position.close()

#     hist_df = get_data(ticker, start_date, end_date)
#     if hist_df.empty:
#         return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}

#     bt = Backtest(hist_df, MeanReversion, cash=initial_capital, commission=.002)
#     stats = bt.run(finalize_trades=True)
    
#     summary = {
#         "Total Return %": f"{stats['Return [%]']:.2f}",
#         "Sharpe Ratio": f"{stats['Sharpe Ratio']:.2f}",
#         "Max Drawdown %": f"{stats['Max. Drawdown [%]']:.2f}",
#         "Number of Trades": stats['# Trades']
#     }

#     # --- ENHANCEMENT: Return full data for professional plotting ---
#     plot_df = hist_df.copy()
#     plot_df['Equity_Curve'] = stats._equity_curve['Equity']
    
#     # Recalculate bands for plotting
#     plot_df['MA'] = plot_df['Close'].rolling(window_period).mean()
#     plot_df['STD'] = plot_df['Close'].rolling(window_period).std()
#     plot_df['Upper_Band'] = plot_df['MA'] + (plot_df['STD'] * std_devs)
#     plot_df['Lower_Band'] = plot_df['MA'] - (plot_df['STD'] * std_devs)
    
#     trades = stats._trades
    
#     return {"summary": summary, "data": plot_df, "trades": trades}

# # --- Streamlit Visualization for Standalone Testing ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="Mean Reversion Strategy", layout="wide")
#     st.title("📈 Mean Reversion Strategy (Standalone)")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "BTC-USD")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
        
#         st.header("Strategy Parameters")
#         window = st.slider("Moving Average Window", 10, 100, 20)
#         num_std = st.slider("Number of Standard Deviations", 1.0, 3.0, 2.0, 0.1)
        
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker}")
#         with st.spinner("Running backtest..."):
#             results = run(
#                 ticker=ticker, 
#                 start_date=start_date, 
#                 end_date=end_date, 
#                 window=window, 
#                 num_std=num_std
#             )
#             summary = results.get("summary", {})
#             backtest_df = results.get("data", pd.DataFrame())
#             trades_df = results.get("trades", pd.DataFrame())

#             if "Error" in summary:
#                 st.error(summary["Error"])
#             elif not backtest_df.empty:
#                 st.subheader("Performance Summary")
#                 cols = st.columns(4)
#                 cols[0].metric("Total Return", f"{summary.get('Total Return %', '0.00')}%")
#                 cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', '0.00'))
#                 cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', '0.00')}%")
#                 cols[3].metric("Trades", summary.get('Number of Trades', 0))

#                 # --- ENHANCEMENT: Professional chart with bands, signals, and equity curve ---
#                 st.subheader("Price Chart with Bollinger Bands, Trades & Equity")
#                 fig = go.Figure()

#                 # Price and Bollinger Bands
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Upper_Band'], name='Upper Band', line=dict(color='orange', dash='dash')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Lower_Band'], name='Lower Band', line=dict(color='orange', dash='dash')))
                
#                 # Equity Curve on secondary axis
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))
                
#                 # Trade Markers
#                 buy_signals = trades_df[trades_df['Size'] > 0]
#                 sell_signals = trades_df[trades_df['Size'] < 0]
#                 fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['EntryPrice'], mode='markers', name='Buy Signal', marker=dict(color='lime', size=10, symbol='triangle-up')))
#                 fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['EntryPrice'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

#                 fig.update_layout(
#                     title_text=f"{ticker} Mean Reversion Backtest",
#                     xaxis_rangeslider_visible=False,
#                     yaxis=dict(title="Price ($)"),
#                     yaxis2=dict(title="Equity ($)", overlaying='y', side='right', showgrid=False)
#                 )
#                 st.plotly_chart(fig, use_container_width=True)
# import pandas as pd
# import ta
# from utils.data_loader import get_history
# from backtesting import Backtest, Strategy
# import streamlit as st
# import plotly.graph_objects as go

# class MeanReversion(Strategy):
#     window = 20
#     num_std = 2.0

#     def init(self):
#         close = pd.Series(self.data.Close)
#         self.ma = self.I(ta.trend.sma_indicator, close, window=self.window)
#         rolling_std = self.I(lambda x, n: pd.Series(x).rolling(n).std(), close, self.window)
#         self.upper_band = self.ma + (rolling_std * self.num_std)
#         self.lower_band = self.ma - (rolling_std * self.num_std)

#     def next(self):
#         if not self.position and self.data.Close[-1] < self.lower_band[-1]:
#             self.buy()
#         elif self.position and self.data.Close[-1] > self.ma[-1]:
#             self.position.close()

# def run(ticker: str, start_date: str, end_date: str, cash=10_000, commission=.002, **kwargs) -> dict:
#     hist_df = get_history(ticker, start_date, end_date)
#     if hist_df.empty:
#         return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}
    
#     if isinstance(hist_df.columns, pd.MultiIndex):
#         hist_df.columns = hist_df.columns.get_level_values(0)
#     hist_df.columns = [col.title() for col in hist_df.columns]

#     MeanReversion.window = kwargs.get("window", 20)
#     MeanReversion.num_std = kwargs.get("num_std", 2.0)
    
#     bt = Backtest(hist_df, MeanReversion, cash=cash, commission=commission)
#     # --- FIX: Ensure final open trades are included in stats ---
#     stats = bt.run(finalize_trades=True)
#     # --- END OF FIX ---
    
#     return {"summary": stats.to_dict(), "data": stats._equity_curve.join(hist_df.Close)}

# # ... (Streamlit UI remains unchanged) ...

# # --- Streamlit Visualization ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="Mean Reversion Strategy", layout="wide")
#     st.title("📈 Mean Reversion (Bollinger Bands) Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "BTC-USD")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         window = st.slider("Moving Average Window", 10, 100, 20)
#         num_std = st.slider("Number of Standard Deviations", 1.0, 3.0, 2.0, 0.1)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker}")
#         with st.spinner("Running backtest..."):
#             results = run(ticker, str(start_date.date()), str(end_date.date()), window=window, num_std=num_std)
#             summary = results.get("summary", {})
#             backtest_df = results.get("data", pd.DataFrame())

#             if "Error" in summary:
#                 st.error(summary["Error"])
#             elif not backtest_df.empty:
#                 st.subheader("Performance Summary")
#                 cols = st.columns(4)
#                 cols[0].metric("Return [%]", f"{summary.get('Return [%]', 0):.2f}")
#                 cols[1].metric("Sharpe Ratio", f"{summary.get('Sharpe Ratio', 0):.2f}")
#                 cols[2].metric("Max Drawdown [%]", f"{summary.get('Max. Drawdown [%]', 0):.2f}")
#                 cols[3].metric("# Trades", summary.get('# Trades', 0))

#                 st.subheader("Equity Curve & Price")
#                 fig = go.Figure()
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity'], name='Equity Curve'))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Close Price', yaxis='y2'))
#                 st.plotly_chart(fig, use_container_width=True)

# import yfinance as yf
# import pandas as pd
# import numpy as np
# import streamlit as st
# import plotly.graph_objects as go

# # --- Core Strategy & Backtesting Logic ---

# def run_backtest(ticker, start_date, end_date, window=20, num_std=2, initial_capital=100000):
#     """Runs the full vectorized backtest for the Mean Reversion strategy."""
#     df = yf.download(ticker, start=start_date, end=end_date, progress=False)
#     if df.empty:
#         return pd.DataFrame()
        
#     df.dropna(inplace=True)

#     df['MA'] = df['Close'].rolling(window).mean()
#     df['STD'] = df['Close'].rolling(window).std()
#     df['Upper'] = df['MA'] + num_std * df['STD']
#     df['Lower'] = df['MA'] - num_std * df['STD']

#     df['Signal'] = 0
#     df.loc[df['Close'] < df['Lower'], 'Signal'] = 1   # Buy
#     df.loc[df['Close'] > df['Upper'], 'Signal'] = -1  # Sell (Go flat)
    
#     # Forward fill signals to hold positions until an opposite signal
#     df['Position'] = df['Signal'].replace(0, np.nan).ffill().fillna(0).shift(1)

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
# def run(ticker: str, start_date: str, end_date: str, **kwargs) -> dict:
#     """
#     Runs the full backtest and returns both the summary and the full data for plotting.
#     """
#     try:
#         window = kwargs.get("window", 20)
#         num_std = kwargs.get("num_std", 2.0)
        
#         df_backtest = run_backtest(ticker, start_date, end_date, window=window, num_std=num_std)
#         if df_backtest.empty:
#             return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}
            
#         summary_metrics = calculate_performance_metrics(df_backtest, 100000)
        
#         return {
#             "summary": summary_metrics,
#             "data": df_backtest
#         }
#     except Exception as e:
#         return {"summary": {"Error": str(e)}, "data": pd.DataFrame()}

# # --- Streamlit Visualization (Frontend Part) ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="Mean Reversion Strategy", layout="wide")
#     st.title("📈 Mean Reversion (Bollinger Bands) Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "BTC-USD")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         window = st.slider("Moving Average Window", 10, 100, 20)
#         num_std = st.slider("Number of Standard Deviations", 1.0, 3.0, 2.0, 0.1)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker}")
        
#         with st.spinner("Running backtest..."):
#             results = run(ticker, str(start_date), str(end_date), window=window, num_std=num_std)
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

#                 st.subheader("Price Chart with Bollinger Bands & Equity Curve")
#                 fig = go.Figure()

#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Upper'], name='Upper Band', line=dict(color='orange', dash='dash')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Lower'], name='Lower Band', line=dict(color='orange', dash='dash')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))

#                 buy_signals = backtest_df[backtest_df['Signal'] == 1]
#                 sell_signals = backtest_df[backtest_df['Signal'] == -1]
#                 fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'], mode='markers', name='Buy Signal', marker=dict(color='green', size=10, symbol='triangle-up')))
#                 fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['Close'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

#                 fig.update_layout(
#                     title_text=f"{ticker} Backtest: Mean Reversion",
#                     xaxis_rangeslider_visible=False,
#                     yaxis=dict(title="Price ($)"),
#                     yaxis2=dict(title="Equity ($)", overlaying='y', side='right')
#                 )
#                 st.plotly_chart(fig, use_container_width=True)