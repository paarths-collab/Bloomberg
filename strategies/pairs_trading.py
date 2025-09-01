import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
from typing import List

# --- Core Strategy & Backtesting Logic ---
def run_backtest(ticker1, ticker2, start_date, end_date, lookback=30, entry_z=2.0, initial_capital=100000):
    data = yf.download([ticker1, ticker2], start=start_date, end=end_date, progress=False)['Close']
    if data.empty or data.isnull().all().any() or len(data) < lookback:
        return pd.DataFrame(), 0
    data.dropna(inplace=True)
    beta = np.polyfit(data[ticker2], data[ticker1], 1)[0]
    data['Spread'] = data[ticker1] - beta * data[ticker2]
    data['Mean'] = data['Spread'].rolling(lookback).mean()
    data['STD'] = data['Spread'].rolling(lookback).std()
    data['Zscore'] = (data['Spread'] - data['Mean']) / data['STD']
    data['Signal'] = 0
    data.loc[data['Zscore'] > entry_z, 'Signal'] = -1
    data.loc[data['Zscore'] < -entry_z, 'Signal'] = 1
    data['Position'] = data['Signal'].shift(1).ffill().fillna(0)
    data['Strategy_Returns'] = data['Spread'].pct_change() * data['Position']
    data['Equity_Curve'] = (1 + data['Strategy_Returns']).cumprod() * initial_capital
    return data, beta

def calculate_performance_metrics(backtest_df, initial_capital):
    if backtest_df.empty: return {}
    final_equity = backtest_df['Equity_Curve'].iloc[-1]
    total_return_pct = (final_equity / initial_capital - 1) * 100
    daily_returns = backtest_df['Strategy_Returns'].dropna()
    sharpe_ratio = np.sqrt(252) * daily_returns.mean() / daily_returns.std() if daily_returns.std() != 0 else 0
    peak = backtest_df['Equity_Curve'].cummax()
    drawdown = (backtest_df['Equity_Curve'] - peak) / peak
    max_drawdown_pct = drawdown.min() * 100
    trades = backtest_df[backtest_df['Signal'] != backtest_df['Signal'].shift(1)]
    return {
        "Total Return %": f"{total_return_pct:.2f}", "Sharpe Ratio": f"{sharpe_ratio:.2f}",
        "Max Drawdown %": f"{max_drawdown_pct:.2f}", "Number of Trades": len(trades)
    }

# --- Orchestrator/API Entry Point ---
def run(tickers: List[str], start_date: str, end_date: str, **kwargs) -> dict:
    if not isinstance(tickers, list) or len(tickers) != 2:
        return {"summary": {"Error": "Pairs Trading requires exactly two tickers."}, "data": pd.DataFrame()}
    ticker1, ticker2 = tickers[0], tickers[1]
    try:
        lookback = kwargs.get("lookback", 30)
        entry_z = kwargs.get("entry_z", 2.0)
        df_backtest, beta = run_backtest(ticker1, ticker2, start_date, end_date, lookback=lookback, entry_z=entry_z)
        if df_backtest.empty:
            return {"summary": {"Error": "No data found for the pair."}, "data": pd.DataFrame()}
        summary_metrics = calculate_performance_metrics(df_backtest, 100000)
        summary_metrics["Hedge Ratio (Beta)"] = f"{beta:.2f}"
        return {"summary": summary_metrics, "data": df_backtest}
    except Exception as e:
        return {"summary": {"Error": str(e)}, "data": pd.DataFrame()}

# --- Streamlit Visualization ---
if __name__ == "__main__":
    st.set_page_config(page_title="Pairs Trading Strategy", layout="wide")
    st.title("📈 Pairs Trading (Statistical Arbitrage) Showcase")
    with st.sidebar:
        st.header("⚙️ Configuration")
        tickers_input = st.text_input("Enter Ticker Pair (comma-separated)", "PEP,KO")
        start_date = st.date_input("Start Date", pd.to_datetime("2022-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        lookback = st.slider("Lookback Period (days)", 10, 100, 30)
        entry_z = st.slider("Entry Z-Score Threshold", 1.0, 3.0, 2.0, 0.1)
        run_button = st.button("🔬 Run Backtest", use_container_width=True)
    if run_button:
        tickers = [t.strip().upper() for t in tickers_input.split(",")]
        if len(tickers) != 2:
            st.error("Please enter exactly two tickers for Pairs Trading.")
        else:
            st.header(f"Results for {tickers[0]} / {tickers[1]}")
            with st.spinner("Running backtest..."):
                results = run(tickers, str(start_date), str(end_date), lookback=lookback, entry_z=entry_z)
                summary = results.get("summary", {})
                backtest_df = results.get("data", pd.DataFrame())
                if "Error" in summary:
                    st.error(summary["Error"])
                else:
                    st.subheader("Performance Summary")
                    cols = st.columns(5)
                    cols[0].metric("Total Return", f"{summary.get('Total Return %', 0)}%")
                    cols[1].metric("Sharpe Ratio", summary.get('Sharpe Ratio', 0))
                    cols[2].metric("Max Drawdown", f"{summary.get('Max Drawdown %', 0)}%")
                    cols[3].metric("Trades", summary.get('Number of Trades', 0))
                    cols[4].metric("Hedge Ratio", summary.get('Hedge Ratio (Beta)', 0))
                    st.subheader("Spread, Z-Score & Equity Curve")
                    fig1 = px.line(backtest_df, x=backtest_df.index, y='Spread', title='Price Spread')
                    st.plotly_chart(fig1, use_container_width=True)
                    fig2 = px.line(backtest_df, x=backtest_df.index, y='Zscore', title='Spread Z-Score')
                    fig2.add_hline(y=entry_z, line_dash="dash", line_color="red", annotation_text="Short Spread")
                    fig2.add_hline(y=-entry_z, line_dash="dash", line_color="green", annotation_text="Long Spread")
                    st.plotly_chart(fig2, use_container_width=True)
                    fig3 = px.line(backtest_df, x=backtest_df.index, y='Equity_Curve', title='Strategy Equity Curve')
                    st.plotly_chart(fig3, use_container_width=True)