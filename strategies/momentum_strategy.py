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
    """ Main orchestrator function for the Momentum strategy. """
    
    # Get strategy-specific parameters from kwargs
    lookback_period = kwargs.get("lookback", 20)
    
    class Momentum(Strategy):
        lookback = lookback_period

        def init(self):
            # Calculate the n-day return series.
            self.returns = self.I(lambda x, n: pd.Series(x).pct_change(n), self.data.Close, self.lookback)

        def next(self):
            # Buy if the momentum is positive (price has increased over the lookback period)
            if not self.position and self.returns[-1] > 0:
                self.buy()
            # Sell if the momentum turns negative
            elif self.position and self.returns[-1] < 0:
                self.position.close()

    hist_df = get_data(ticker, start_date, end_date)
    if hist_df.empty:
        return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}
            
    bt = Backtest(hist_df, Momentum, cash=initial_capital, commission=.002)
    stats = bt.run(finalize_trades=True)
    
    summary = {
        "Total Return %": f"{stats['Return [%]']:.2f}",
        "Sharpe Ratio": f"{stats['Sharpe Ratio']:.2f}",
        "Max Drawdown %": f"{stats['Max. Drawdown [%]']:.2f}",
        "Number of Trades": stats['# Trades']
    }

    # Standardize the output DataFrame
    plot_df = pd.DataFrame({'Equity_Curve': stats._equity_curve['Equity']})
    
    return {"summary": summary, "data": plot_df}

# --- Streamlit Visualization for Standalone Testing ---
if __name__ == "__main__":
    st.set_page_config(page_title="Momentum Strategy", layout="wide")
    st.title("📈 Momentum Strategy (Standalone)")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "TSLA")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        
        st.header("Strategy Parameters")
        lookback = st.slider("Lookback Period (days)", 5, 100, 20)
        
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
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity', line=dict(color='purple')))
                fig.update_layout(
                    title_text=f"{ticker} Momentum Strategy Equity Curve",
                    xaxis_title="Date",
                    yaxis_title="Portfolio Value ($)"
                )
                st.plotly_chart(fig, use_container_width=True)
# import pandas as pd
# from utils.data_loader import get_history
# from backtesting import Backtest, Strategy
# import streamlit as st
# import plotly.graph_objects as go

# class Momentum(Strategy):
#     lookback = 20

#     def init(self):
#         self.returns = self.I(lambda x, n: pd.Series(x).pct_change(n), self.data.Close, self.lookback)

#     def next(self):
#         if not self.position and self.returns[-1] > 0:
#             self.buy()
#         elif self.position and self.returns[-1] < 0:
#             self.position.close()

# def run(ticker: str, start_date: str, end_date: str, cash=10_000, commission=.002, **kwargs) -> dict:
#     hist_df = get_history(ticker, start_date, end_date)
#     if hist_df.empty:
#         return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}
            
#     if isinstance(hist_df.columns, pd.MultiIndex):
#         hist_df.columns = hist_df.columns.get_level_values(0)
#     hist_df.columns = [col.title() for col in hist_df.columns]
            
#     Momentum.lookback = kwargs.get("lookback", 20)

#     bt = Backtest(hist_df, Momentum, cash=cash, commission=commission)
#     # --- FIX: Ensure final open trades are included in stats ---
#     stats = bt.run(finalize_trades=True)
#     # --- END OF FIX ---
    
#     return {"summary": stats.to_dict(), "data": stats._equity_curve}

# # ... (Streamlit UI remains unchanged) ...

# # --- Streamlit Visualization ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="Momentum Strategy", layout="wide")
#     st.title("📈 Momentum Strategy Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "TSLA")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         lookback = st.slider("Lookback Period (days)", 5, 100, 20)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker}")
#         with st.spinner("Running backtest..."):
#             results = run(ticker, str(start_date.date()), str(end_date.date()), lookback=lookback)
#             summary = results.get("summary", {})
#             equity_curve = results.get("data", pd.DataFrame())

#             if "Error" in summary:
#                 st.error(summary["Error"])
#             elif not equity_curve.empty:
#                 st.subheader("Performance Summary")
#                 cols = st.columns(4)
#                 cols[0].metric("Return [%]", f"{summary.get('Return [%]', 0):.2f}")
#                 cols[1].metric("Sharpe Ratio", f"{summary.get('Sharpe Ratio', 0):.2f}")
#                 cols[2].metric("Max Drawdown [%]", f"{summary.get('Max. Drawdown [%]', 0):.2f}")
#                 cols[3].metric("# Trades", summary.get('# Trades', 0))

#                 st.subheader("Equity Curve")
#                 fig = go.Figure(go.Scatter(x=equity_curve.index, y=equity_curve['Equity'], name='Equity Curve'))
#                 st.plotly_chart(fig, use_container_width=True)
# import yfinance as yf
# import pandas as pd
# import numpy as np
# import streamlit as st
# import plotly.graph_objects as go

# # --- Core Strategy & Backtesting Logic ---

# def run_backtest(ticker, start_date, end_date, lookback=20, initial_capital=100000):
#     """Runs the full vectorized backtest for the Momentum strategy."""
#     df = yf.download(ticker, start=start_date, end=end_date, progress=False)
#     if df.empty:
#         return pd.DataFrame()
        
#     df.dropna(inplace=True)

#     df['Return_Lookback'] = df['Close'].pct_change(lookback)
#     df['Signal'] = 0
#     df.loc[df['Return_Lookback'] > 0, 'Signal'] = 1
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
# def run(ticker: str, start_date: str, end_date: str, **kwargs) -> dict:
#     """
#     Runs the full backtest and returns both the summary and the full data for plotting.
#     """
#     try:
#         lookback = kwargs.get("lookback", 20)
        
#         df_backtest = run_backtest(ticker, start_date, end_date, lookback=lookback)
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
#     st.set_page_config(page_title="Momentum Strategy", layout="wide")
#     st.title("📈 Momentum Strategy Showcase")

#     with st.sidebar:
#         st.header("⚙️ Configuration")
#         ticker = st.text_input("Ticker Symbol", "TSLA")
#         start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
#         end_date = st.date_input("End Date", pd.to_datetime("today"))
#         lookback = st.slider("Lookback Period (days)", 5, 100, 20)
#         run_button = st.button("🔬 Run Backtest", use_container_width=True)

#     if run_button:
#         st.header(f"Results for {ticker}")
        
#         with st.spinner("Running backtest..."):
#             results = run(ticker, str(start_date), str(end_date), lookback=lookback)
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

#                 st.subheader("Price Chart & Equity Curve")
#                 fig = go.Figure()

#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
#                 fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))

#                 buy_signals = backtest_df[(backtest_df['Signal'] == 1) & (backtest_df['Signal'].shift(1) == 0)]
#                 fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'], mode='markers', name='Go Long', marker=dict(color='green', size=10, symbol='triangle-up')))

#                 fig.update_layout(
#                     title_text=f"{ticker} Backtest: Momentum Strategy",
#                     xaxis_rangeslider_visible=False,
#                     yaxis=dict(title="Price ($)"),
#                     yaxis2=dict(title="Equity ($)", overlaying='y', side='right')
#                 )
#                 st.plotly_chart(fig, use_container_width=True)