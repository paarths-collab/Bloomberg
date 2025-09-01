import yfinance as yf
import pandas as pd
import streamlit as st
import plotly.express as px

# --- Core Strategy Logic ---
def analyze(stock_symbol: str) -> dict:
    """
    Analyzes a stock's historical value metrics over multiple periods.
    """
    try:
        stock = yf.Ticker(stock_symbol)
        info = stock.info
        
        current_metrics = {
            "Current P/E Ratio": info.get("trailingPE"),
            "Current P/B Ratio": info.get("priceToBook"),
            "Current Return on Equity (ROE)": info.get("returnOnEquity"),
            "Current Debt-to-Equity": info.get("debtToEquity")
        }

        quarterly_financials = stock.quarterly_financials
        quarterly_balance_sheet = stock.quarterly_balance_sheet
        hist_prices = stock.history(period="11y")

        if hist_prices.empty or quarterly_financials.empty or quarterly_balance_sheet.empty:
             return {"current_metrics": current_metrics, "historical_performance": []}

        historical_performance = []
        
        for year in range(pd.Timestamp.now().year - 1, pd.Timestamp.now().year - 12, -1):
            try:
                date = f"{year}-12-31"
                price_date = hist_prices.index.asof(date)
                if pd.isna(price_date): continue
                price = hist_prices.loc[price_date]["Close"]

                financials_date = quarterly_financials.columns.asof(date)
                balance_sheet_date = quarterly_balance_sheet.columns.asof(date)
                if pd.isna(financials_date) or pd.isna(balance_sheet_date): continue
                
                # Use Trailing-Twelve-Months (TTM) for more accurate Net Income
                net_income_ttm = quarterly_financials.loc['Net Income', financials_date-pd.DateOffset(months=9):financials_date].sum()
                shares_outstanding = info.get("sharesOutstanding")
                if not shares_outstanding: continue
                eps_ttm = net_income_ttm / shares_outstanding
                pe_ratio = price / eps_ttm if eps_ttm > 0 else None

                book_value = quarterly_balance_sheet.loc['Total Stockholder Equity', balance_sheet_date]
                pb_ratio = price / (book_value / shares_outstanding) if book_value > 0 else None
                
                roe = net_income_ttm / book_value if book_value > 0 else None

                historical_performance.append({
                    "Year": year,
                    "P/E Ratio": pe_ratio,
                    "P/B Ratio": pb_ratio,
                    "Return on Equity (ROE) %": roe * 100 if roe is not None else None,
                })
            except (KeyError, IndexError):
                continue
                
        historical_performance.reverse()

        return {
            "current_metrics": current_metrics,
            "historical_performance": historical_performance
        }
    except Exception as e:
        return {"Error": f"Could not fetch value metrics for {stock_symbol}: {e}"}

# --- Streamlit Visualization ---
if __name__ == "__main__":
    st.set_page_config(page_title="Value Investing Analysis", layout="wide")
    st.title("📊 Value Investing Deep Dive")

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "MSFT")
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

                st.subheader("Current Valuation Metrics")
                cols = st.columns(4)
                cols[0].metric("P/E Ratio", f"{current.get('Current P/E Ratio'):.2f}" if current.get('Current P/E Ratio') else "N/A")
                cols[1].metric("P/B Ratio", f"{current.get('Current P/B Ratio'):.2f}" if current.get('Current P/B Ratio') else "N/A")
                cols[2].metric("ROE", f"{current.get('Current Return on Equity (ROE)', 0)*100:.2f}%" if current.get('Current Return on Equity (ROE)') else "N/A")
                cols[3].metric("Debt/Equity", f"{current.get('Current Debt-to-Equity'):.2f}" if current.get('Current Debt-to-Equity') else "N/A")

                if not historical_df.empty:
                    st.subheader("Historical Performance Trends")
                    st.dataframe(historical_df.set_index("Year"))
                    
                    fig = px.bar(historical_df, x='Year', y=['P/E Ratio', 'P/B Ratio'],
                                 title='Historical P/E and P/B Ratios', barmode='group')
                    st.plotly_chart(fig, use_container_width=True)
                    
                    fig2 = px.line(historical_df, x='Year', y='Return on Equity (ROE) %',
                                   title='Historical Return on Equity (ROE)', markers=True)
                    st.plotly_chart(fig2, use_container_width=True)