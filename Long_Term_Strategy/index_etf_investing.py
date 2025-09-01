import yfinance as yf
import pandas as pd
import streamlit as st
import plotly.express as px

# --- Core Logic ---
def analyze(symbol: str) -> dict:
    """
    Analyzes the historical performance of an Index/ETF over multiple periods.
    Returns a dictionary of performance data suitable for tables and charts.
    """
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period="11y", auto_adjust=False) # Get raw close for price, auto_adjust=False needed for Adj Close
        if hist.empty:
            return {"Error": f"No data found for symbol {symbol}"}

        periods = {
            "1-Year": 365, "3-Year": 365 * 3,
            "5-Year": 365 * 5, "10-Year": 365 * 10
        }
        
        performance_data = []
        today = hist.index[-1]

        for label, days in periods.items():
            start_date = today - pd.DateOffset(days=days)
            
            # Find the closest actual trading day to the start date
            actual_start_date = hist.index.asof(start_date)
            if pd.isna(actual_start_date):
                continue

            start_price = hist.loc[actual_start_date, "Close"]
            end_price = hist.loc[today, "Close"]
            start_adj = hist.loc[actual_start_date, "Adj Close"]
            end_adj = hist.loc[today, "Adj Close"]

            # Calculate metrics
            total_return = (end_adj / start_adj - 1) * 100
            years = days / 365.25
            cagr = ((end_adj / start_adj) ** (1 / years) - 1) * 100

            performance_data.append({
                "Period": label,
                "Total Return %": total_return,
                "Annualized Return (CAGR) %": cagr,
            })

        return {"performance_data": performance_data}

    except Exception as e:
        return {"Error": f"Could not fetch ETF/Index data for {symbol}: {e}"}

# --- Streamlit Visualization ---
if __name__ == "__main__":
    st.set_page_config(page_title="Index/ETF Analysis", layout="wide")
    st.title("📈 Index & ETF Performance Analyzer")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Enter Index/ETF Ticker", "SPY")
        run_button = st.button("🔬 Analyze Performance", use_container_width=True)

    if run_button:
        st.header(f"Results for {ticker}")
        
        with st.spinner("Fetching and analyzing historical data..."):
            results = analyze(ticker)

            if "Error" in results:
                st.error(results["Error"])
            else:
                df = pd.DataFrame(results.get("performance_data", []))
                
                if df.empty:
                    st.warning("Not enough historical data to generate a report.")
                else:
                    st.subheader("Long-Term Performance Summary")
                    
                    # Display metrics in columns
                    cols = st.columns(len(df))
                    for i, row in df.iterrows():
                        cols[i].metric(
                            label=f"{row['Period']} Total Return",
                            value=f"{row['Total Return %']:.2f}%"
                        )
                        cols[i].metric(
                            label=f"{row['Period']} CAGR",
                            value=f"{row['Annualized Return (CAGR) %']:.2f}%"
                        )
                    
                    st.subheader("Performance Comparison Chart")
                    fig = px.bar(df, x='Period', y=['Total Return %', 'Annualized Return (CAGR) %'],
                                 title=f'Long-Term Returns for {ticker}', barmode='group')
                    st.plotly_chart(fig, use_container_width=True)

                    st.subheader("Detailed Data")
                    st.dataframe(df.set_index("Period"))