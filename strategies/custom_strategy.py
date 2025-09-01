import pandas as pd
import ta  # Corrected: Using the 'ta' library to avoid the conflict
from utils.data_loader import get_history
from backtesting import Backtest, Strategy
import streamlit as st
import plotly.graph_objects as go

# --- Core Strategy Logic for backtesting.py ---

def run(ticker, start_date, end_date, cash=10_000, commission=.002, rsi_lower=30, rsi_upper=70):
    """
    This function is the main entry point called by the orchestrator.
    It runs the backtest using the backtesting.py library.
    """
    class CustomSmaRsi(Strategy):
        # Pass the user-defined parameters to the strategy
        rsi_lower_threshold = rsi_lower
        rsi_upper_threshold = rsi_upper
        sma_period = 50
        rsi_period = 14

        def init(self):
            close = self.data.Close
            # Use self.I to correctly define indicators for backtesting.py
            self.sma = self.I(lambda x, n: pd.Series(x).rolling(n).mean(), close, self.sma_period)
            # Use the correct function from the 'ta' library
            self.rsi = self.I(ta.momentum.rsi, pd.Series(close), window=self.rsi_period)

        def next(self):
            price = self.data.Close[-1]
            if not self.position:
                # Buy signal
                if self.rsi[-1] < self.rsi_lower_threshold and price > self.sma[-1]:
                    self.buy()
            # Sell signal
            elif self.rsi[-1] > self.rsi_upper_threshold:
                self.position.close()

    hist_df = get_history(ticker, start_date, end_date)
    if hist_df.empty:
        return {"summary": {"Error": "Could not fetch historical data."}, "data": pd.DataFrame()}
    
    bt = Backtest(hist_df, CustomSmaRsi, cash=cash, commission=commission)
    stats = bt.run()
    
    # Return both the statistics and the backtest data for plotting
    return {"summary": stats.to_dict(), "data": stats._equity_curve}

# --- Streamlit Visualization (for standalone testing) ---
if __name__ == "__main__":
    st.set_page_config(page_title="Custom Strategy Showcase", layout="wide")
    st.title("📊 Custom Strategy (RSI + SMA) Showcase")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "NVDA")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        rsi_lower = st.slider("RSI Lower (Buy) Threshold", 10, 50, 30)
        rsi_upper = st.slider("RSI Upper (Sell) Threshold", 50, 90, 70)
        run_button = st.button("🔬 Run Backtest", use_container_width=True)

    if run_button:
        st.header(f"Results for {ticker}")
        
        with st.spinner("Running backtest..."):
            results = run(
                ticker=ticker,
                start_date=str(start_date.date()),
                end_date=str(end_date.date()),
                rsi_lower=rsi_lower,
                rsi_upper=rsi_upper
            )
            summary = results.get("summary", {})
            equity_curve = results.get("data", pd.DataFrame())

        if "Error" in summary:
            st.error(summary["Error"])
        elif not equity_curve.empty:
            st.subheader("Performance Summary")
            cols = st.columns(4)
            cols[0].metric("Return [%]", f"{summary.get('Return [%]', 0):.2f}")
            cols[1].metric("Sharpe Ratio", f"{summary.get('Sharpe Ratio', 0):.2f}")
            cols[2].metric("Max Drawdown [%]", f"{summary.get('Max. Drawdown [%]', 0):.2f}")
            cols[3].metric("# Trades", summary.get('# Trades', 0))

            st.subheader("Equity Curve")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=equity_curve.index, y=equity_curve['Equity'], name='Equity Curve', line=dict(color='purple')))
            fig.update_layout(
                title_text=f"{ticker} Equity Curve",
                xaxis_title="Date",
                yaxis_title="Equity ($)"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Backtest did not produce any results.")


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