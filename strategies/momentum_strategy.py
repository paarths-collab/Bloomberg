import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from backtesting import Backtest, Strategy

# --- CORRECT: Import the single, centralized get_data function ---
from utils.data_loader import get_data

class Momentum(Strategy):
    """
    Momentum Strategy implementation for backtesting.py library.
    
    This strategy buys when the momentum (price change over lookback period) is positive
    and sells when the momentum turns negative.
    """
    
    def init(self):
        # Calculate the n-day return series.
        self.returns = self.I(lambda x, n: pd.Series(x).pct_change(n), self.data.Close, self.lookback_period)

    def next(self):
        # Buy if the momentum is positive (price has increased over the lookback period)
        if not self.position and self.returns[-1] > 0:
            self.buy()
        # Sell if the momentum turns negative
        elif self.position and self.returns[-1] < 0:
            self.position.close()

# --- Main Run Function (Callable by Portfolio Builder) ---
def run(ticker: str, start_date: str, end_date: str, market, initial_capital=100000, **kwargs) -> dict:
    """ Main orchestrator function for the Momentum strategy. """
    
    # Get strategy-specific parameters from kwargs
    lookback_period = kwargs.get("lookback", 20)
    
    # Set the lookback period for the strategy class
    Momentum.lookback_period = lookback_period

    hist_df = get_data(ticker, start_date, end_date, market)
    if hist_df.empty:
        return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}
            
    bt = Backtest(hist_df, Momentum, cash=initial_capital, commission=.002, finalize_trades=True)
    stats = bt.run()
    
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
                market="USA",  # Default market for standalone testing
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
