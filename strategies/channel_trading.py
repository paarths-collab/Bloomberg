
import yfinance as yf
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from backtesting import Backtest, Strategy

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
def run(ticker: str, start_date: str, end_date: str, initial_capital=100000, **kwargs) -> dict:
    """ Main orchestrator function for the Channel Trading strategy. """
    
    channel_period = kwargs.get('period', 20)

    class ChannelTrading(Strategy):
        period = channel_period

        def init(self):
            # Donchian Channels: Highest high and lowest low over the lookback period.
            self.upper_band = self.I(lambda x: pd.Series(x).rolling(self.period).max(), self.data.High)
            self.lower_band = self.I(lambda x: pd.Series(x).rolling(self.period).min(), self.data.Low)

        def next(self):
            # If the price breaks above the previous bar's upper band, close any short and go long.
            if self.data.Close[-1] > self.upper_band[-2]:
                self.position.close()
                self.buy()
            # If the price breaks below the previous bar's lower band, close any long and go short.
            elif self.data.Close[-1] < self.lower_band[-2]:
                self.position.close()
                self.sell()

    hist_df = get_data(ticker, start_date, end_date)
    if hist_df.empty:
        return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}

    # CORRECT CODE:
    bt = Backtest(hist_df, ChannelTrading, cash=initial_capital, commission=.002, finalize_trades=True) # <-- CORRECT PLACE
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
    # Recalculate channels using a shift to align with the strategy logic for plotting
    plot_df['Upper_Band'] = plot_df['High'].rolling(channel_period).max().shift(1)
    plot_df['Lower_Band'] = plot_df['Low'].rolling(channel_period).min().shift(1)
    
    trades = stats._trades
    
    return {"summary": summary, "data": plot_df, "trades": trades}

# --- Streamlit Visualization for Standalone Testing ---
if __name__ == "__main__":
    st.set_page_config(page_title="Channel Trading Strategy", layout="wide")
    st.title("📈 Channel Trading Strategy (Standalone)")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "MSFT")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        
        st.header("Strategy Parameters")
        period = st.slider("Channel Period (days)", 10, 100, 20)
        
        run_button = st.button("🔬 Run Backtest", use_container_width=True)

    if run_button:
        st.header(f"Results for {ticker}")
        with st.spinner("Running backtest..."):
            results = run(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                period=period
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
            st.subheader("Price Chart with Donchian Channels, Trades & Equity")
            fig = go.Figure()

            # Price, Channels, and Equity Curve
            fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
            fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Upper_Band'], name='Upper Channel', line=dict(color='lightcoral', dash='dash')))
            fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Lower_Band'], name='Lower Channel', line=dict(color='lightgreen', dash='dash')))
            fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))
            
            # Trade Markers
            buy_signals = trades_df[trades_df['Size'] > 0]
            sell_signals = trades_df[trades_df['Size'] < 0]
            fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['EntryPrice'], mode='markers', name='Go Long', marker=dict(color='lime', size=10, symbol='triangle-up')))
            fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['EntryPrice'], mode='markers', name='Go Short', marker=dict(color='red', size=10, symbol='triangle-down')))

            fig.update_layout(
                title_text=f"{ticker} Donchian Channel Backtest",
                xaxis_rangeslider_visible=False,
                yaxis=dict(title="Price ($)"),
                yaxis2=dict(title="Equity ($)", overlaying='y', side='right', showgrid=False)
            )
            st.plotly_chart(fig, use_container_width=True)
# import pandas as pd
# from utils.data_loader import get_history
# from backtesting import Backtest, Strategy
# import streamlit as st
# import plotly.graph_objects as go
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

# def run(ticker, start_date, end_date, cash=10_000, commission=.002, **kwargs):
#     """
#     The main entry point called by the orchestrator to run the backtest.
#     """
#     df = get_data(ticker, start_date, end_date)
#         # --- END OF FIX ---
#     if df.empty:
#             return {"summary": {"Error": "Could not fetch historical data."}}
#     # Sanitize DataFrame columns to prevent errors with backtesting.py
#     if isinstance(df.columns, pd.MultiIndex):
#         df.columns = df.columns.get_level_values(0)
#     df.columns = [col.title() for col in df.columns]

#     # Update the strategy's period parameter if provided in the config
#     ChannelTrading.period = kwargs.get('period', 20)

#     # Instantiate and run the backtest, ensuring final trades are included
#     bt = Backtest(df, ChannelTrading, cash=cash, commission=commission, finalize_trades=True)
#     stats = bt.run()
    
#     # Prepare data for plotting
#     plot_data = stats._equity_curve.copy()
#     if 'Close' in df.columns:
#         plot_data = plot_data.join(df['Close'])
        
#     return {"summary": stats.to_dict(), "data": plot_data}

# # --- Streamlit Visualization (for standalone testing) ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="Channel Trading Strategy", layout="wide")
#     st.title("📈 Channel Trading (Donchian) Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "MSFT")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         period = st.slider("Channel Period (days)", 10, 100, 20)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker}")
#         with st.spinner("Running backtest..."):
#             results = run(
#                 ticker=ticker, start_date=str(start_date.date()),
#                 end_date=str(end_date.date()), period=period
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
# # import pandas as pd
# from utils.data_loader import get_history
# from backtesting import Backtest, Strategy
# import streamlit as st
# import plotly.graph_objects as go

# class ChannelTrading(Strategy):
#     period = 20

#     def init(self):
#         self.upper_band = self.I(lambda x: pd.Series(x).rolling(self.period).max(), self.data.High)
#         self.lower_band = self.I(lambda x: pd.Series(x).rolling(self.period).min(), self.data.Low)

#     def next(self):
#         if self.data.Close[-1] > self.upper_band[-2]:
#             self.position.close()
#             self.buy()
#         elif self.data.Close[-1] < self.lower_band[-2]:
#             self.position.close()
#             self.sell()

# def run(ticker, start_date, end_date, cash=10_000, commission=.002, **kwargs):
#     hist_df = get_history(ticker, start_date, end_date)
#     if hist_df.empty:
#         return {"summary": {"Error": "Could not fetch historical data."}}
    
#     if isinstance(hist_df.columns, pd.MultiIndex):
#         hist_df.columns = hist_df.columns.get_level_values(0)
#     hist_df.columns = [col.title() for col in hist_df.columns]

#     ChannelTrading.period = kwargs.get('period', 20)
#     bt = Backtest(hist_df, ChannelTrading, cash=cash, commission=commission, finalize_trades=True)
#     stats = bt.run()
    
#     return {"summary": stats.to_dict()}

# # --- Streamlit Visualization (for standalone testing) ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="Channel Trading Strategy", layout="wide")
#     st.title("📈 Channel Trading (Donchian) Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "MSFT")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         period = st.slider("Channel Period (days)", 10, 100, 20)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker}")
#         with st.spinner("Running backtest..."):
#             results = run(
#                 ticker=ticker, start_date=str(start_date.date()),
#                 end_date=str(end_date.date()), period=period
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
#             fig.update_layout(title_text=f"{ticker} Equity Curve and Price")
#             st.plotly_chart(fig, use_container_width=True)
#         else:
#             st.warning("Backtest completed, but no trades were made or data could not be plotted.")
# import yfinance as yf
# import pandas as pd
# import numpy as np
# import streamlit as st
# import plotly.graph_objects as g
# from utils.data_loader import get_history
# from backtesting import Backtest, Strategy

# # --- Core Strategy & Backtesting Logic ---
# # This is the "backend" part of the module.

# def get_data(ticker, start, end, interval='1d'):
#     """Fetches historical price data."""
#     df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
#     if df.empty:
#         return pd.DataFrame()
#     return df[['Open','High','Low','Close','Volume']]

# def generate_signals(df, period=20, entry_buffer=0.002):
#     """Generates buy/sell signals based on Donchian Channels."""
#     df = df.copy()
#     df['upper'] = df['High'].rolling(window=period).max().shift(1)
#     df['lower'] = df['Low'].rolling(window=period).min().shift(1)
#     df['trade'] = 0
    
#     position = 0
#     for i in range(period, len(df)):
#         if df.iloc[i]['Close'] <= df.iloc[i]['lower'] * (1 + entry_buffer) and position == 0:
#             position = 1
#             df.iloc[i, df.columns.get_loc('trade')] = 1 # Buy signal
#         elif df.iloc[i]['Close'] >= df.iloc[i]['upper'] * (1 - entry_buffer) and position == 1:
#             position = 0
#             df.iloc[i, df.columns.get_loc('trade')] = -1 # Sell signal
#     return df

# def run_backtest(df, hold_days=7, init_cash=100000):
#     """Event-driven backtester for the channel trading strategy."""
#     df = df.copy().reset_index()
#     cash = init_cash
#     position = 0
#     shares = 0
#     trades = []
#     entry_idx = None
#     df['equity'] = init_cash

#     if df.empty:
#         return pd.DataFrame(), []

#     for i in range(len(df)-1):
#         trade_signal = df.loc[i, 'trade']
#         next_day_open = df.loc[i+1, 'Open']
        
#         if trade_signal == 1 and position == 0:
#             shares_to_buy = cash // next_day_open
#             if shares_to_buy > 0:
#                 cash -= shares_to_buy * next_day_open
#                 position = 1
#                 shares = shares_to_buy
#                 entry_idx = i + 1
#                 trades.append({'date': df.loc[i+1, 'Date'], 'type': 'BUY', 'price': next_day_open, 'shares': shares})
        
#         if (trade_signal == -1 and position == 1) or \
#            (position == 1 and entry_idx is not None and (i + 1 - entry_idx) >= hold_days):
#             cash += shares * next_day_open
#             trades.append({'date': df.loc[i+1, 'Date'], 'type': 'SELL', 'price': next_day_open, 'shares': shares})
#             shares, position, entry_idx = 0, 0, None
            
#         df.loc[i, 'equity'] = cash + (shares * df.loc[i, 'Close'])
        
#     df.loc[len(df)-1, 'equity'] = cash + (shares * df.loc[len(df)-1, 'Close'])

#     return df.set_index('Date'), trades

# def calculate_performance_metrics(backtest_df, trades_list, initial_capital):
#     """Calculates a dictionary of professional trading metrics."""
#     if backtest_df.empty or not trades_list:
#         return {}

#     final_equity = backtest_df['equity'].iloc[-1]
#     total_return_pct = (final_equity / initial_capital - 1) * 100
    
#     daily_returns = backtest_df['equity'].pct_change().dropna()
#     sharpe_ratio = np.sqrt(252) * daily_returns.mean() / daily_returns.std() if daily_returns.std() != 0 else 0
    
#     peak = backtest_df['equity'].cummax()
#     drawdown = (backtest_df['equity'] - peak) / peak
#     max_drawdown_pct = drawdown.min() * 100

#     trades_df = pd.DataFrame(trades_list)
#     buy_prices = trades_df[trades_df['type'] == 'BUY']['price']
#     sell_prices = trades_df[trades_df['type'] == 'SELL']['price']
    
#     min_len = min(len(buy_prices), len(sell_prices))
#     trade_returns = (sell_prices.values[:min_len] - buy_prices.values[:min_len]) / buy_prices.values[:min_len]
    
#     win_rate = (trade_returns > 0).mean() * 100 if len(trade_returns) > 0 else 0
    
#     return {
#         "Total Return %": f"{total_return_pct:.2f}",
#         "Sharpe Ratio": f"{sharpe_ratio:.2f}",
#         "Max Drawdown %": f"{max_drawdown_pct:.2f}",
#         "Win Rate %": f"{win_rate:.2f}",
#         "Number of Trades": len(trades_list) // 2
#     }

# # --- Orchestrator/API Entry Point ---


# def run(ticker, start_date, end_date, cash=10_000, commission=.002):
#     """
#     Runs a backtest for the Channel Trading strategy.
#     """
#     class ChannelTrading(Strategy):
#         n1 = 20  # Channel period

#         def init(self):
#             # Use the self.I method to ensure indicators are correctly aligned
#             self.upper_band = self.I(lambda x: pd.Series(x).rolling(self.n1).max(), self.data.High)
#             self.lower_band = self.I(lambda x: pd.Series(x).rolling(self.n1).min(), self.data.Low)

#         def next(self):
#             if self.data.Close[-1] > self.upper_band[-2]:
#                 self.buy()
#             elif self.data.Close[-1] < self.lower_band[-2]:
#                 self.sell()

#     hist_df = get_history(ticker, start_date, end_date)
#     if hist_df.empty:
#         return {"error": "Could not fetch historical data."}

#     bt = Backtest(hist_df, ChannelTrading, cash=cash, commission=commission)
#     stats = bt.run()
    
#     return {
#         "summary": stats.to_dict(),
#         "plot": bt.plot(open_browser=False)
#     }

# # --- Streamlit Visualization (Frontend Part) ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="Channel Trading Strategy", layout="wide")
#     st.title("📈 Channel Trading (Donchian) Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "MSFT")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         period = st.slider("Channel Period (days)", 10, 100, 20)
#         hold_days = st.slider("Max Holding Period (days)", 3, 30, 7)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker}")
        
#         with st.spinner("Running backtest..."):
#             results = run(ticker, str(start_date), str(end_date), period=period, hold_days=hold_days)
#             summary = results.get("summary", {})
#             backtest_df = results.get("data", pd.DataFrame())
#             trades_list = results.get("trades", [])

#             if "Error" in summary:
#                 st.error(summary["Error"])
#             else:
#                 st.subheader("Performance Summary")
#                 cols = st.columns(5)
#                 cols[0].metric("Total Return", f"{summary.get('Total Return %', 0)}%")
#                 cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', 0))
#                 cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', 0)}%")
#                 cols[3].metric("Win Rate", f"{summary.get('Win Rate %', 0)}%")
#                 cols[4].metric("Trades", summary.get('Number of Trades', 0))

#                 st.subheader("Price Chart with Signals, Channels & Equity Curve")
#                 fig = go.Figure()

#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='blue')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['upper'], name='Upper Channel', line=dict(color='orange', dash='dash')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['lower'], name='Lower Channel', line=dict(color='orange', dash='dash')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['equity'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))

#                 trades_df = pd.DataFrame(trades_list)
#                 if not trades_df.empty:
#                     buy_signals = trades_df[trades_df['type'] == 'BUY']
#                     sell_signals = trades_df[trades_df['type'] == 'SELL']
#                     fig.add_trace(go.Scatter(x=buy_signals['date'], y=buy_signals['price'], mode='markers', name='Buy Signal', marker=dict(color='green', size=10, symbol='triangle-up')))
#                     fig.add_trace(go.Scatter(x=sell_signals['date'], y=sell_signals['price'], mode='markers', name='Sell Signal', marker=dict(color='red', size=10, symbol='triangle-down')))

#                 fig.update_layout(
#                     title_text=f"{ticker} Backtest: Channel Trading",
#                     xaxis_rangeslider_visible=False,
#                     yaxis=dict(title="Price ($)"),
#                     yaxis2=dict(title="Equity ($)", overlaying='y', side='right')
#                 )
#                 st.plotly_chart(fig, use_container_width=True)