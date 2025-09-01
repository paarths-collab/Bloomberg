import pandas as pd
from utils.data_loader import get_history
from backtesting import Backtest, Strategy
import streamlit as st
import plotly.graph_objects as go

# --- Core Strategy Logic for backtesting.py ---

import pandas as pd
from utils.data_loader import get_history
from backtesting import Backtest, Strategy

def run(ticker, start_date, end_date, cash=10_000, commission=.002, **kwargs):
    """
    Runs a backtest for the Breakout strategy.
    """
    class BreakoutStrategy(Strategy):
        n1 = 20  # Lookback period for the breakout high

        def init(self):
            # Pre-calculate the rolling high to use in the strategy
            self.highs = self.I(lambda x: pd.Series(x).rolling(self.n1).max(), self.data.High)

        def next(self):
            # Entry signal: Buy if not in a position and the price breaks above the recent high
            if not self.position and self.data.Close[-1] > self.highs[-2]:
                self.buy(size=0.2)  # Invest 20% of equity
            # Exit signal: Sell if in a position and the price falls back below the recent high
            elif self.position and self.data.Close[-1] < self.highs[-2]:
                self.position.close()

    # 1. Fetch historical data
    hist_df = get_history(ticker, start_date, end_date)
    if hist_df.empty:
        return {"summary": {"Error": "Could not fetch historical data."}, "data": pd.DataFrame()}
    
    # 2. Fix DataFrame column names for the backtesting library
    if isinstance(hist_df.columns, pd.MultiIndex):
        hist_df.columns = hist_df.columns.get_level_values(0)
    hist_df.columns = hist_df.columns.str.title()

    # 3. Run the backtest
    bt = Backtest(hist_df, BreakoutStrategy, cash=cash, commission=commission)
    stats = bt.run()
    
    # 4. Prepare the data for charting by merging price data with the equity curve
    backtest_data = hist_df.join(stats._equity_curve)

    # 5. Return the results
    return {"summary": stats.to_dict(), "data": backtest_data}



# --- Streamlit Visualization (for standalone testing) ---
if __name__ == "__main__":
    st.set_page_config(page_title="Volume Breakout Strategy", layout="wide")
    st.title("📈 Volume Breakout Strategy Showcase")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "NVDA")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        lookback_period = st.slider("Lookback Period (days)", 10, 100, 20)
        volume_multiplier = st.slider("Volume Multiplier", 1.0, 3.0, 1.5, 0.1)
        run_button = st.button("🔬 Run Backtest", use_container_width=True)

    if run_button:
        st.header(f"Results for {ticker}")
        
        with st.spinner("Running backtest..."):
            results = run(
                ticker=ticker,
                start_date=str(start_date.date()),
                end_date=str(end_date.date()),
                lookback_period=lookback_period,
                volume_multiplier=volume_multiplier
            )
            summary = results.get("summary", {})
            backtest_df = results.get("data", pd.DataFrame())

        if "Error" in summary:
            st.error(summary["Error"])
        elif not backtest_df.empty:
            st.subheader("Performance Summary")
            cols = st.columns(4)
            cols[0].metric("Return [%]", f"{summary.get('Return [%]', 0):.2f}")
            cols[1].metric("Sharpe Ratio", f"{summary.get('Sharpe Ratio', 0):.2f}")
            cols[2].metric("Max Drawdown [%]", f"{summary.get('Max. Drawdown [%]', 0):.2f}")
            cols[3].metric("# Trades", summary.get('# Trades', 0))

            st.subheader("Equity Curve & Price")
            fig = go.Figure()
            # Plot the equity curve
            fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity'], name='Equity Curve', line=dict(color='purple')))
            # Plot the closing price on a secondary y-axis
            fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Close Price', yaxis='y2', line=dict(color='blue', dash='dash')))
            
            fig.update_layout(
                title_text=f"{ticker} Equity Curve and Price",
                xaxis_title="Date",
                yaxis=dict(title="Equity ($)"),
                yaxis2=dict(title="Price ($)", overlaying='y', side='right')
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Backtest did not produce any results.")