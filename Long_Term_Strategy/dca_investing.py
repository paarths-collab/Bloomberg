import yfinance as yf
import pandas as pd
import streamlit as st
import plotly.express as px

# --- Core Simulation Logic ---
def run_simulation(stock_symbol: str, monthly_investment: float, start_date: str) -> dict:
    """
    Simulates a Dollar-Cost Averaging (DCA) strategy and returns the results.
    """
    try:
        hist = yf.Ticker(stock_symbol).history(start=start_date, auto_adjust=True)
        if hist.empty:
            return {"summary": {"Error": "No data found for this period."}, "data": pd.DataFrame()}

        # Resample to get the first trading day's price of each month
        monthly_prices = hist['Close'].resample('MS').first() # 'MS' for Month Start
        
        # Simulate the investment
        units_bought = monthly_investment / monthly_prices
        total_units = units_bought.cumsum()
        
        # Create a results DataFrame
        sim_df = pd.DataFrame(index=monthly_prices.index)
        sim_df['Invested This Month'] = monthly_investment
        sim_df['Monthly Price'] = monthly_prices
        sim_df['Units Bought'] = units_bought
        sim_df['Total Units Owned'] = total_units
        sim_df['Total Capital Invested'] = sim_df['Invested This Month'].cumsum()
        sim_df['Portfolio Value'] = sim_df['Total Units Owned'] * sim_df['Monthly Price']
        
        # --- Calculate Final Summary Metrics ---
        final_value = sim_df['Portfolio Value'].iloc[-1]
        total_invested = sim_df['Total Capital Invested'].iloc[-1]
        total_return_pct = (final_value / total_invested - 1) * 100
        
        summary = {
            "Total Invested": f"${total_invested:,.2f}",
            "Final Portfolio Value": f"${final_value:,.2f}",
            "Total Return %": f"{total_return_pct:.2f}",
            "Number of Monthly Investments": len(sim_df),
        }

        return {"summary": summary, "data": sim_df}

    except Exception as e:
        return {"summary": {"Error": str(e)}, "data": pd.DataFrame()}

# --- Streamlit Visualization (Frontend Part) ---
if __name__ == "__main__":
    st.set_page_config(page_title="DCA Simulator", layout="wide")
    st.title("📈 Dollar-Cost Averaging (DCA/SIP) Simulator")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "VOO") # VOO is a good ETF for DCA
        start_date = st.date_input("Start Date of Investment", pd.to_datetime("2015-01-01"))
        monthly_investment = st.number_input("Monthly Investment Amount ($)", min_value=1, value=100)
        run_button = st.button("🔬 Run Simulation", use_container_width=True)

    if run_button:
        st.header(f"DCA Simulation Results for {ticker}")
        
        with st.spinner("Running simulation..."):
            results = run_simulation(ticker, str(start_date))
            summary = results.get("summary", {})
            sim_df = results.get("data", pd.DataFrame())

            if "Error" in summary:
                st.error(summary["Error"])
            else:
                st.subheader("Performance Summary")
                cols = st.columns(4)
                cols[0].metric("Total Invested", summary.get("Total Invested", "$0"))
                cols[1].metric("Final Portfolio Value", summary.get("Final Portfolio Value", "$0"))
                cols[2].metric("Total Return", f"{summary.get('Total Return %', 0)}%")
                cols[3].metric("Months Invested", summary.get("Number of Monthly Investments", 0))

                st.subheader("Portfolio Growth Over Time")
                fig = px.line(sim_df, x=sim_df.index, y=['Portfolio Value', 'Total Capital Invested'],
                              title=f"DCA Growth for {ticker}")
                fig.update_layout(yaxis_title="Value ($)")
                st.plotly_chart(fig, use_container_width=True)
                
                st.subheader("Monthly Investment Data")
                st.dataframe(sim_df)