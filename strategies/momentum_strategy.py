import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go

# --- Core Strategy & Backtesting Logic ---

def run_backtest(ticker, start_date, end_date, lookback=20, initial_capital=100000):
    """Runs the full vectorized backtest for the Momentum strategy."""
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if df.empty:
        return pd.DataFrame()
        
    df.dropna(inplace=True)

    df['Return_Lookback'] = df['Close'].pct_change(lookback)
    df['Signal'] = 0
    df.loc[df['Return_Lookback'] > 0, 'Signal'] = 1
    df['Position'] = df['Signal'].shift(1).fillna(0)

    df['Strategy_Returns'] = df['Position'] * df['Close'].pct_change()
    df['Equity_Curve'] = (1 + df['Strategy_Returns']).cumprod() * initial_capital
    return df

def calculate_performance_metrics(backtest_df, initial_capital):
    """Calculates a dictionary of professional trading metrics."""
    if backtest_df.empty:
        return {}

    final_equity = backtest_df['Equity_Curve'].iloc[-1]
    total_return_pct = (final_equity / initial_capital - 1) * 100
    
    daily_returns = backtest_df['Strategy_Returns'].dropna()
    sharpe_ratio = np.sqrt(252) * daily_returns.mean() / daily_returns.std() if daily_returns.std() != 0 else 0
    
    peak = backtest_df['Equity_Curve'].cummax()
    drawdown = (backtest_df['Equity_Curve'] - peak) / peak
    max_drawdown_pct = drawdown.min() * 100

    trades = backtest_df[backtest_df['Signal'] != backtest_df['Signal'].shift(1)]
    
    return {
        "Total Return %": f"{total_return_pct:.2f}",
        "Sharpe Ratio": f"{sharpe_ratio:.2f}",
        "Max Drawdown %": f"{max_drawdown_pct:.2f}",
        "Number of Trades": len(trades)
    }

# --- Orchestrator/API Entry Point ---
def run(ticker: str, start_date: str, end_date: str, **kwargs) -> dict:
    """
    Runs the full backtest and returns both the summary and the full data for plotting.
    """
    try:
        lookback = kwargs.get("lookback", 20)
        
        df_backtest = run_backtest(ticker, start_date, end_date, lookback=lookback)
        if df_backtest.empty:
            return {"summary": {"Error": "No data found."}, "data": pd.DataFrame()}
            
        summary_metrics = calculate_performance_metrics(df_backtest, 100000)
        
        return {
            "summary": summary_metrics,
            "data": df_backtest
        }
    except Exception as e:
        return {"summary": {"Error": str(e)}, "data": pd.DataFrame()}

# --- Streamlit Visualization (Frontend Part) ---
if __name__ == "__main__":
    st.set_page_config(page_title="Momentum Strategy", layout="wide")
    st.title("📈 Momentum Strategy Showcase")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "TSLA")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        lookback = st.slider("Lookback Period (days)", 5, 100, 20)
        run_button = st.button("🔬 Run Backtest", use_container_width=True)

    if run_button:
        st.header(f"Results for {ticker}")
        
        with st.spinner("Running backtest..."):
            results = run(ticker, str(start_date), str(end_date), lookback=lookback)
            summary = results.get("summary", {})
            backtest_df = results.get("data", pd.DataFrame())

            if "Error" in summary:
                st.error(summary["Error"])
            else:
                st.subheader("Performance Summary")
                cols = st.columns(4)
                cols[0].metric("Total Return", f"{summary.get('Total Return %', 0)}%")
                cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', 0))
                cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', 0)}%")
                cols[3].metric("Trades", summary.get('Number of Trades', 0))

                st.subheader("Price Chart & Equity Curve")
                fig = go.Figure()

                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Close'], name='Price', line=dict(color='skyblue')))
                fig.add_trace(go.Scatter(x=backtest_df.index, y=backtest_df['Equity_Curve'], name='Equity Curve', yaxis='y2', line=dict(color='purple', dash='dot')))

                buy_signals = backtest_df[(backtest_df['Signal'] == 1) & (backtest_df['Signal'].shift(1) == 0)]
                fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'], mode='markers', name='Go Long', marker=dict(color='green', size=10, symbol='triangle-up')))

                fig.update_layout(
                    title_text=f"{ticker} Backtest: Momentum Strategy",
                    xaxis_rangeslider_visible=False,
                    yaxis=dict(title="Price ($)"),
                    yaxis2=dict(title="Equity ($)", overlaying='y', side='right')
                )
                st.plotly_chart(fig, use_container_width=True)