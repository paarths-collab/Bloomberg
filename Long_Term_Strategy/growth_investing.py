import yfinance as yf
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# --- Core Logic ---
def analyze(stock_symbol: str) -> dict:
    try:
        stock = yf.Ticker(stock_symbol)
        info = stock.info
        
        current_metrics = {
            "Current Revenue Growth (Quarterly YoY)": info.get("revenueGrowth"),
            "Current Earnings Growth (Quarterly YoY)": info.get("earningsGrowth"),
        }

        financials = stock.financials
        hist_prices = stock.history(period="11y")

        if hist_prices.empty or financials.empty:
             return {"current_metrics": current_metrics, "historical_performance": []}
        
        if hist_prices.index.tz is not None:
            hist_prices.index = hist_prices.index.tz_localize(None)

        historical_performance = []
        
        for i in range(len(financials.columns) - 1):
            try:
                current_year_date, prior_year_date = financials.columns[i], financials.columns[i+1]
                year = current_year_date.year

                current_revenue = financials.loc['Total Revenue', current_year_date]
                prior_revenue = financials.loc['Total Revenue', prior_year_date]
                revenue_growth_yoy = ((current_revenue - prior_revenue) / prior_revenue) * 100 if prior_revenue != 0 else None

                price_current = hist_prices["Close"].asof(current_year_date)
                price_prior = hist_prices["Close"].asof(prior_year_date)
                price_growth_yoy = ((price_current - price_prior) / price_prior) * 100 if price_prior is not None and price_prior != 0 else None

                historical_performance.append({
                    "Year": year,
                    "Revenue Growth YoY %": revenue_growth_yoy,
                    "Price Growth YoY %": price_growth_yoy,
                })
            except (KeyError, IndexError):
                continue
                
        historical_performance.reverse()

        return {"current_metrics": current_metrics, "historical_performance": historical_performance}
    except Exception as e:
        return {"Error": f"Could not fetch growth metrics for {stock_symbol}: {e}"}

# --- Streamlit Visualization ---
if __name__ == "__main__":
    st.set_page_config(page_title="Growth Investing Analysis", layout="wide")
    st.title("🚀 Growth Investing Deep Dive")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "NVDA")
        run_button = st.button("🔬 Analyze", use_container_width=True)

    if run_button:
        st.header(f"Results for {ticker}")
        
        with st.spinner("Fetching and analyzing historical data..."):
            results = analyze(ticker)
            if "Error" in results:
                st.error(results["Error"])
            else:
                current = results.get("current_metrics", {})
                historical_df = pd.DataFrame(results.get("historical_performance", []))

                st.subheader("Current Growth Rates (Quarterly YoY)")
                cols = st.columns(2)
                rev_growth = current.get("Current Revenue Growth (Quarterly YoY)")
                earn_growth = current.get("Current Earnings Growth (Quarterly YoY)")
                cols[0].metric("Revenue Growth", f"{rev_growth*100:.2f}%" if rev_growth else "N/A")
                cols[1].metric("Earnings Growth", f"{earn_growth*100:.2f}%" if earn_growth else "N/A")

                if not historical_df.empty:
                    st.subheader("Historical Growth vs. Price Performance")
                    st.dataframe(historical_df.set_index("Year"))
                    
                    fig = go.Figure()
                    fig.add_trace(go.Bar(x=historical_df['Year'], y=historical_df['Revenue Growth YoY %'], name='Revenue Growth %'))
                    fig.add_trace(go.Scatter(x=historical_df['Year'], y=historical_df['Price Growth YoY %'], name='Stock Price Growth %', yaxis='y2', line=dict(color='purple', dash='dot')))
                    
                    fig.update_layout(
                        title_text=f"{ticker}: Revenue Growth vs. Stock Price Growth",
                        barmode='group',
                        yaxis=dict(title="Revenue Growth (%)"),
                        yaxis2=dict(title="Stock Price Growth (%)", overlaying='y', side='right')
                    )
                    st.plotly_chart(fig, use_container_width=True)
# import yfinance as yf
# import pandas as pd

# def analyze(stock_symbol: str) -> dict:
#     """
#     Analyzes a stock's historical growth metrics (revenue and price) over the last 10 years.
#     Returns a dictionary with current metrics and a list of historical data
#     suitable for charts and tables.
#     """
#     try:
#         stock = yf.Ticker(stock_symbol)
#         info = stock.info
        
#         # --- Get Current Metrics ---
#         # Analyst estimates for future growth are a key part of growth investing
#         current_growth_rate = info.get("revenueGrowth") # This is quarterly
#         earnings_growth_rate = info.get("earningsGrowth") # This is quarterly
        
#         current_metrics = {
#             "Current Revenue Growth (Quarterly YoY)": f"{current_growth_rate * 100:.2f}%" if current_growth_rate else "N/A",
#             "Current Earnings Growth (Quarterly YoY)": f"{earnings_growth_rate * 100:.2f}%" if earnings_growth_rate else "N/A",
#         }

#         # --- Calculate Historical Performance ---
#         financials = stock.financials # Annual financials
#         hist_prices = stock.history(period="11y") # Get 11 years to calculate 10 years of growth

#         if hist_prices.empty or financials.empty:
#              return {"current_metrics": current_metrics, "historical_performance": []}

#         historical_performance = []
        
#         # We will calculate the YoY growth for the end of each of the last 10 fiscal years
#         for i in range(len(financials.columns) - 1):
#             try:
#                 # Dates from financial statements
#                 current_year_date = financials.columns[i]
#                 prior_year_date = financials.columns[i+1]
#                 year = current_year_date.year

#                 # --- Calculate historical metrics ---
                
#                 # Revenue Growth (YoY)
#                 current_revenue = financials.loc['Total Revenue', current_year_date]
#                 prior_revenue = financials.loc['Total Revenue', prior_year_date]
#                 revenue_growth_yoy = ((current_revenue - prior_revenue) / prior_revenue) * 100 if prior_revenue != 0 else None

#                 # Price Growth (YoY)
#                 price_current = hist_prices["Close"].asof(current_year_date)
#                 price_prior = hist_prices["Close"].asof(prior_year_date)
#                 price_growth_yoy = ((price_current - price_prior) / price_prior) * 100 if price_prior != 0 else None

#                 historical_performance.append({
#                     "Year": year,
#                     "Revenue Growth YoY %": round(revenue_growth_yoy, 2) if revenue_growth_yoy is not None else None,
#                     "Price Growth YoY %": round(price_growth_yoy, 2) if price_growth_yoy is not None else None,
#                     "Total Revenue": f"${current_revenue/1e6:,.2f}M" # In millions
#                 })
#             except (KeyError, IndexError):
#                 # Happens if data is missing for a specific year
#                 continue
                
#         # The list is built backwards, so reverse it for chronological order
#         historical_performance.reverse()

#         return {
#             "current_metrics": current_metrics,
#             "historical_performance": historical_performance
#         }
        
#     except Exception as e:
#         return {"Error": f"Could not fetch growth metrics for {stock_symbol}: {e}"}

# # Example of the expected output format:
# # {
# #   "current_metrics": {
# #     "Current Revenue Growth (Quarterly YoY)": "15.50%", ...
# #   },
# #   "historical_performance": [
# #     {"Year": 2015, "Revenue Growth YoY %": 27.8, "Price Growth YoY %": -4.6, "Total Revenue": "$233,715.00M"},
# #     {"Year": 2016, "Revenue Growth YoY %": -7.7, "Price Growth YoY %": 10.0, "Total Revenue": "$215,639.00M"},
# #     ...
# #   ]
# # }