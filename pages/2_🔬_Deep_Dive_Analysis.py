import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date
import sys
from pathlib import Path

# --- Path setup to allow importing from the 'agents' directory ---
sys.path.append(str(Path(__file__).parent.parent))
from agents.orchestrator import Orchestrator

# --- Page Configuration ---
st.set_page_config(page_title="Deep Dive Analysis", layout="wide")
st.title("🔬 Single-Stock Deep Dive Analysis")

# --- Cached Functions for Performance ---
@st.cache_resource
def load_orchestrator():
    """Loads the orchestrator once and caches the resource for the entire session."""
    config_path = "quant-company-insights-agent/config.yaml"
    return Orchestrator.from_file(config_path)

@st.cache_data
def load_us_stock_list():
    """
    Loads and prepares the US stock list from us_stocks.csv
    for the searchable selectbox.
    """
    try:
        project_root = Path(__file__).parent.parent
        us_file_path = project_root / "data" / "us_stocks.csv"
        df = pd.read_csv(us_file_path)

        company_col = 'Company Name'
        symbol_col = 'Symbol'

        if company_col not in df.columns or symbol_col not in df.columns:
            st.error(f"CRITICAL ERROR: '{company_col}' or '{symbol_col}' not found in us_stocks.csv.")
            return None

        df['Display'] = df[company_col] + " (" + df[symbol_col] + ")"
        
        return df[[symbol_col, 'Display']].sort_values("Display")

    except FileNotFoundError:
        st.error("CRITICAL ERROR: 'us_stocks.csv' not found. Please ensure it is in the 'data/' folder.")
        return None

@st.cache_data
def load_nse_stock_list():
    """
    Loads and prepares the Nifty 500 stock list from nifty500.csv
    for the searchable selectbox.
    """
    try:
        project_root = Path(__file__).parent.parent
        # --- THIS IS THE FIX (PART 1): Point to the correct file ---
        nse_file_path = project_root / "data" / "nifty500.csv"
        df = pd.read_csv(nse_file_path)

        # --- THIS IS THE FIX (PART 2): Use the correct column names ---
        company_col = 'Company Name'
        symbol_col = 'Symbol'

        if company_col not in df.columns or symbol_col not in df.columns:
            st.error(f"CRITICAL ERROR: '{company_col}' or '{symbol_col}' not found in nifty500.csv.")
            return None

        df['Display'] = df[company_col] + " (" + df[symbol_col] + ")"
        # --- END OF FIX ---
        
        return df[[symbol_col, 'Display']].sort_values("Display")

    except FileNotFoundError:
        st.error("CRITICAL ERROR: 'nifty500.csv' not found. Please ensure it is in the 'quant-company-insights-agent/data/' folder.")
        return None

# --- Load necessary resources ---
orchestrator = load_orchestrator()
us_stocks_df = load_us_stock_list()
nse_stocks_df = load_nse_stock_list()

# --- Helper Functions for Display ---
def format_large_number(num):
    if pd.isna(num) or not isinstance(num, (int, float)): return "N/A"
    if abs(num) >= 1_000_000_000_000: return f"{num / 1_000_000_000_000:,.2f} T"
    if abs(num) >= 1_000_000_000: return f"{num / 1_000_000_000:,.2f} B"
    if abs(num) >= 1_000_000: return f"{num / 1_000_000:,.2f} M"
    return f"{num:,.0f}"

def create_price_chart(df, stock_name, currency_symbol="$"):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'))
    
    # Safely add indicators if they exist
    if 'trend_sma_fast' in df.columns: 
        fig.add_trace(go.Scatter(x=df.index, y=df['trend_sma_fast'], name='Fast SMA', line=dict(color='orange', width=1.5)))
    if 'trend_sma_slow' in df.columns: 
        fig.add_trace(go.Scatter(x=df.index, y=df['trend_sma_slow'], name='Slow SMA', line=dict(color='purple', width=1.5)))
        
    fig.update_layout(title_text=f'<b>{stock_name} Price Chart & Indicators</b>', yaxis_title=f'Price ({currency_symbol})', xaxis_rangeslider_visible=False, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    return fig

# --- Sidebar for User Input ---
with st.sidebar:
    st.header("⚙️ Configuration")
    analysis_market = st.radio("Select Market", ["🇺🇸 US", "🇮🇳 India"], horizontal=True)
    
    ticker = None
    if analysis_market == "🇮🇳 India" and nse_stocks_df is not None:
        selected_display = st.selectbox("Search for an NSE Stock", options=nse_stocks_df['Display'])
        if selected_display:
            ticker = nse_stocks_df[nse_stocks_df['Display'] == selected_display]['Symbol'].iloc[0]
    elif analysis_market == "🇺🇸 US" and us_stocks_df is not None:
        try:
            # Find the default index for AAPL
            default_index = int(us_stocks_df[us_stocks_df['Symbol'] == 'AAPL'].index[0])
        except (IndexError, TypeError):
            default_index = 0  # fallback to first row if AAPL missing
        selected_display = st.selectbox(
            "Search for a US Stock",
            options=us_stocks_df['Display'],
            index=default_index
        )
        if selected_display:
            ticker = us_stocks_df[us_stocks_df['Display'] == selected_display]['Symbol'].iloc[0]
    else:
        ticker = st.text_input("Enter a US Ticker Symbol", "AAPL")
        
    start_date = st.date_input("Start Date", pd.to_datetime("2023-01-01"))
    end_date = st.date_input("End Date", pd.to_datetime(date.today()))
    run_button = st.button("🔬 Run Deep Dive", use_container_width=True)

# --- Main Page Display Logic ---
# --- Main Page Display Logic ---
if run_button and ticker:
    # Convert the emoji-based market to text for the orchestrator
    market_for_orchestrator = "India" if analysis_market == "🇮🇳 India" else "USA"
    
    with st.spinner(f"Running full multi-agent analysis for {ticker}..."):
        results = orchestrator.run_deep_dive_analysis(
            ticker=ticker, 
            start_date=str(start_date), 
            end_date=str(end_date),
            market=market_for_orchestrator
        )

    snapshot = results.get("snapshot", {})
    stock_name = snapshot.get('longName', ticker)
    st.header(f"Deep Dive for {stock_name} ({snapshot.get('symbol', ticker)})")

    # Check for an error FIRST
    if "error" in results and results["error"]:
        st.error(f"Analysis failed. Reason: {results['error']}")
    else:
        # ALL THE DISPLAY LOGIC NOW GOES INSIDE THIS 'ELSE' BLOCK
        quote = results.get("live_quote", {})
        # Use a consistent variable name, e.g., hist_df
        hist_df = results.get("historical_data", pd.DataFrame()) 
        insider = results.get("insider_analysis", {})
        news = results.get("news_sentiment", {})
        social = results.get("social_sentiment", {})
        
        currency_symbol = "₹" if snapshot.get("currency") == "INR" else "$"
        
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "📈 Price Chart & Technicals", "🏢 Ownership & Insider", "💬 Sentiment"])

        with tab1:
            st.subheader("Key Metrics")
            cols = st.columns(4)
            cols[0].metric("Live Price", f"{currency_symbol}{quote.get('c', 0):,.2f}", f"{quote.get('d', 0):,.2f} ({quote.get('dp', 0):,.2f}%)")
            cols[1].metric("Market Cap", format_large_number(snapshot.get('marketCap')))
            cols[2].metric("Trailing P/E", f"{snapshot.get('trailingPE'):.2f}" if snapshot.get('trailingPE') else "N/A")
            cols[3].metric("Div. Yield", f"{snapshot.get('dividendYield', 0) * 100:.2f}%")
            
            st.subheader("Company Profile")
            st.markdown(f"**Sector:** {snapshot.get('sector', 'N/A')} | **Industry:** {snapshot.get('industry', 'N/A')}")
            st.markdown(snapshot.get('longBusinessSummary', 'No summary available.'))

        with tab2:
            st.subheader("Price Chart with Moving Averages")
            # Use the correct, consistent variable name 'hist_df'
            if not hist_df.empty:
                st.plotly_chart(create_price_chart(hist_df, stock_name, currency_symbol), use_container_width=True)
            
            st.subheader("Latest Technical Indicator Values")
            if not hist_df.empty:
                # Display the last row of the DataFrame, which contains the latest indicator values
                st.dataframe(hist_df.tail(1))

        with tab3:
            st.subheader("Insider Analysis")
            insider_summary = insider.get("summary", {})
            insider_cols = st.columns(3)
            insider_cols[0].metric("Recent Buys", insider_summary.get("Recent Buys (Count)", 0))
            insider_cols[1].metric("Recent Sells", insider_summary.get("Recent Sells (Count)", 0))
            insider_cols[2].metric("Net Sentiment", insider_summary.get("Net Sentiment", "N/A"))
            with st.expander("Recent Insider Transactions"):
                st.dataframe(insider.get("transactions", pd.DataFrame()))
                st.dataframe(insider.get("roster", pd.DataFrame()))

        with tab4:
            st.subheader("News & Social Media Sentiment")
            sentiment_cols = st.columns(2)
            sentiment_cols[0].metric("News Sentiment Score", f"{news.get('avg_score', 0):.3f}")
            sentiment_cols[1].metric("Reddit Sentiment", social.get("Overall Social Sentiment", "N/A"))
            with st.expander("Top News Headlines"):
                for headline in news.get("headlines", []):
                    st.markdown(f"- {headline}")
### **Summary of Changes and Improvements**
### **Summary of Changes and Improvements**

# 1.  **`TypeError` Fixed:** The `orchestrator.run_deep_dive_analysis` call now correctly includes the `market=analysis_market` argument, which permanently solves the `TypeError` you were seeing.

# 2.  **Cleaner UI Logic:**
#     *   The `load_orchestrator` and `load_nse_stock_list` functions are now properly cached, which will improve performance.
#     *   The user interface is more intuitive. The `st.radio` button for the market is cleaner than a dropdown.
#     *   The code correctly extracts the ticker symbol from the user-friendly display string in the NSE `selectbox`.

# 3.  **Improved Data Display:**
#     *   The main "Overview" tab now uses a `format_large_number` helper to display Market Cap in a more readable format (e.g., "$2.84 T" instead of a long number).
#     *   The price metric now shows the daily change and percentage change, which is standard for any financial dashboard.
#     *   The tabs are reorganized slightly to group related information (e.g., putting Insider Activity under an "Ownership" tab).

# 4.  **More Robust Code:**
#     *   The `load_nse_stock_list` function now has better error handling in case the CSV file is not found.
#     *   The code that extracts data from the `results` dictionary now uses `.get()` more consistently to prevent crashes if a piece of data is missing.
#     *   The path to the NSE stock list is now constructed more robustly using `pathlib`.

# This revised file is now fully aligned with your upgraded Orchestrator and provides a much richer and more stable user experience for deep-dive analysis.

# import streamlit as st
# import pandas as pd
# import plotly.graph_objects as go
# from datetime import date
# import sys
# from pathlib import Path

# # Ensure custom modules are importable
# sys.path.append(str(Path(__file__).parent.parent))
# from agents.orchestrator import Orchestrator

# st.set_page_config(page_title="Deep Dive Analysis", layout="wide")
# st.title("🔬 Single-Stock Deep Dive Analysis")

# @st.cache_resource
# def load_orchestrator():
#     config_path = "quant-company-insights-agent\config.yaml"
#     return Orchestrator.from_file(config_path)

# @st.cache_data
# def load_nse_stock_list():
#     try:
#         project_root = Path(__file__).parent.parent
#         nse_file_path = project_root / "data" / "nifty500.csv"
#         df = pd.read_csv(nse_file_path)
#         df['Display'] = df['Company Name'] + " (" + df['Symbol'] + ")"
#         return df.sort_values("Company Name")
#     except FileNotFoundError:
#         st.error("CRITICAL ERROR: 'nifty500.csv' not found.")
#         return None

# orchestrator = load_orchestrator()
# nse_stocks_df = load_nse_stock_list()

# def format_large_number(num):
#     if pd.isna(num) or not isinstance(num, (int, float)): return "N/A"
#     if abs(num) >= 1_000_000_000: return f"{num / 1_000_000_000:,.2f} B"
#     if abs(num) >= 1_000_000: return f"{num / 1_000_000:,.2f} M"
#     return f"{num:,.0f}"

# def create_price_chart(df, stock_name, currency_symbol="$"):
#     fig = go.Figure()
#     fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'))
#     fig.add_trace(go.Scatter(x=df.index, y=df['trend_sma_fast'], name='50-Day SMA', line=dict(color='orange', width=1.5)))
#     fig.add_trace(go.Scatter(x=df.index, y=df['trend_sma_slow'], name='200-Day SMA', line=dict(color='purple', width=1.5)))
#     fig.update_layout(title_text=f'<b>{stock_name} Price Chart</b>', yaxis_title=f'Price ({currency_symbol})', xaxis_rangeslider_visible=False, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
#     return fig

# # --- Sidebar ---
# with st.sidebar:
#     st.header("⚙️ Configuration")
#     analysis_region = st.radio("Select Market", ["US", "India (NSE)"], key="market_selector")
#     ticker = None
#     if analysis_region == "India (NSE)" and nse_stocks_df is not None:
#         selected_stock = st.selectbox("Search for an NSE Stock", options=nse_stocks_df['Display'])
#         ticker = nse_stocks_df[nse_stocks_df['Display'] == selected_stock]['Symbol'].iloc[0]
#     else:
#         ticker = st.text_input("Enter a US Ticker Symbol", "AAPL")
#     start_date = st.date_input("Start Date", pd.to_datetime("2023-01-01"))
#     end_date = st.date_input("End Date", pd.to_datetime(date.today()))
#     run_button = st.button("🔬 Run Deep Dive")

# # --- Main Page ---
# if run_button and ticker:
#     with st.spinner(f"Running full analysis for {ticker}..."):
#         results = orchestrator.run_deep_dive_analysis(ticker, str(start_date), str(end_date))

#     stock_name = results.get("stock_name", ticker)
#     st.header(f"Deep Dive for {stock_name} ({ticker})")

#     if "error" in results:
#         st.error(f"Analysis failed. Reason: {results['error']}")
#     else:
#         snapshot, quote, hist, financials, ownership, actions, recommendations = (
#             results.get(k, {}) for k in ["snapshot", "live_quote", "historical_data", "financials", "ownership", "corporate_actions", "analyst_recommendations"]
#         )
#         currency_symbol = "₹" if snapshot.get("currency") == "INR" else "$"
        
#         tab_list = ["📊 Overview", "📈 Price Chart", "⚖️ Valuation", "💰 Financials", "🏢 Ownership"]  #"⭐ Analyst Ratings"
#         tab1, tab2, tab3, tab4, tab5 = st.tabs(tab_list)

#         with tab1:
#             st.subheader("Key Metrics")
#             cols = st.columns(4); cols[0].metric("Live Price", f"{currency_symbol}{quote.get('c', 0):,.2f}"); cols[1].metric("Market Cap", f"{currency_symbol}{snapshot.get('marketCap', 0)/1e9:,.2f}B"); cols[2].metric("Trailing P/E", f"{snapshot.get('trailingPE', 0):.2f}"); cols[3].metric("Div. Yield", f"{snapshot.get('dividendYield', 0) * 100:.2f}%")
#             st.subheader("Company Profile"); st.markdown(f"**Sector:** {snapshot.get('industry', 'N/A')} | **Country:** {snapshot.get('country', 'N/A')}"); st.markdown(snapshot.get('longBusinessSummary', 'No summary available.'))
#             st.divider(); st.subheader("Dividends & Splits"); d_cols = st.columns(2)
#             div_df = actions.get("dividends", pd.DataFrame())
#             if not div_df.empty: d_cols[0].write("Recent Dividends:"); d_cols[0].dataframe(div_df.head(), hide_index=True)
#             splits_df = actions.get("splits", pd.DataFrame())
#             if not splits_df.empty: d_cols[1].write("Stock Splits:"); d_cols[1].dataframe(splits_df)

#         with tab2:
#             if not hist.empty: st.plotly_chart(create_price_chart(hist, stock_name, currency_symbol), use_container_width=True)

#         with tab3:
#             st.subheader(f"Valuation vs. {snapshot.get('industry', 'N/A')} Sector Average")
#             pe, sector_pe = snapshot.get('trailingPE', 0), results.get("sector_comparison", {}).get('sector_pe', 0)
#             pb, sector_pb = snapshot.get('priceToBook', 0), results.get("sector_comparison", {}).get('sector_pb', 0)
#             div_yield, sector_div_yield = snapshot.get('dividendYield', 0), results.get("sector_comparison", {}).get('sector_div_yield', 0)
#             cols = st.columns(3)
#             cols[0].metric("P/E Ratio", f"{pe:.2f}", f"{pe - sector_pe:.2f} vs. Sector ({sector_pe:.2f})", delta_color="inverse")
#             cols[1].metric("P/B Ratio", f"{pb:.2f}", f"{pb - sector_pb:.2f} vs. Sector ({sector_pb:.2f})", delta_color="inverse")
#             cols[2].metric("Dividend Yield", f"{div_yield*100:.2f}%", f"{(div_yield - sector_div_yield)*100:.2f}% vs. Sector", delta_color="normal")
#             st.caption("Note: For P/E and P/B, a negative delta can suggest undervaluation.")

#         with tab4:
#             st.subheader("Financial Statements (Annual)")
#             income_df, balance_df, cash_df = financials.get("income_statement"), financials.get("balance_sheet"), financials.get("cash_flow")
#             if not income_df.empty: st.write("Income Statement"); st.dataframe(income_df.map(format_large_number))
#             if not balance_df.empty: st.write("Balance Sheet"); st.dataframe(balance_df.map(format_large_number))
#             if not cash_df.empty: st.write("Cash Flow"); st.dataframe(cash_df.map(format_large_number))

#         with tab5:
#             st.subheader("Share Ownership")
#             major_df, inst_df = ownership.get("major_holders"), ownership.get("institutional_holders")
#             if major_df is not None and not major_df.empty: st.write("Major Holders:"); st.dataframe(major_df)
#             else: st.info("Major Holders: Data not available.")
#             st.divider()
#             if inst_df is not None and not inst_df.empty:
#                 st.write("Top 10 Institutional Holders:")
#                 display_df = inst_df.copy(); rename_map = {'Holder': 'Firm', 'Shares': 'Shares Held', '% Out': 'Stake (%)'}; cols_to_rename = {k: v for k, v in rename_map.items() if k in display_df.columns}; display_df.rename(columns=cols_to_rename, inplace=True)
#                 if 'Shares Held' in display_df.columns: display_df['Shares Held'] = display_df['Shares Held'].apply(lambda x: f"{x:,}")
#                 if 'Stake (%)' in display_df.columns: display_df['Stake (%)'] = display_df['Stake (%)'].apply(lambda x: f"{x*100:.2f}%")
#                 final_cols = [col for col in ['Firm', 'Shares Held', 'Stake (%)', 'Value'] if col in display_df.columns]
#                 st.dataframe(display_df[final_cols].head(10), hide_index=True)
#             else: st.info("Institutional Holders: Data not available.")

    

# import streamlit as st
# import pandas as pd
# import plotly.graph_objects as go
# from datetime import date
# import sys
# from pathlib import Path

# # Ensure custom modules are importable
# sys.path.append(str(Path(__file__).parent.parent))
# from agents.orchestrator import Orchestrator

# # --- Page Config ---
# st.set_page_config(page_title="Deep Dive Analysis", layout="wide")
# st.title("🔬 Single-Stock Deep Dive Analysis")

# # --- Load Orchestrator & NSE Stock List (Cached) ---
# @st.cache_resource
# def load_orchestrator():
#     config_path = "quant-company-insights-agent\config.yaml"
#     return Orchestrator.from_file(config_path)

# @st.cache_data
# def load_nse_stock_list():
#     try:
#         project_root = Path(__file__).parent.parent
#         nse_file_path = project_root / "data" / "nifty500.csv"
#         df = pd.read_csv(nse_file_path)
#         df['Display'] = df['Company Name'] + " (" + df['Symbol'] + ")"
#         return df.sort_values("Company Name")
#     except FileNotFoundError:
#         st.error("CRITICAL ERROR: 'nifty500.csv' not found.")
#         return None

# orchestrator = load_orchestrator()
# nse_stocks_df = load_nse_stock_list()

# # --- Helper Functions for Readability and Plotting ---
# def format_large_number(num):
#     if pd.isna(num) or not isinstance(num, (int, float)): return "N/A"
#     if abs(num) >= 1_000_000_000: return f"{num / 1_000_000_000:,.2f} B"
#     if abs(num) >= 1_000_000: return f"{num / 1_000_000:,.2f} M"
#     return f"{num:,.0f}"

# def create_price_chart(df, stock_name, currency_symbol="$"):
#     fig = go.Figure()
#     fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'))
#     fig.add_trace(go.Scatter(x=df.index, y=df['trend_sma_fast'], name='50-Day SMA', line=dict(color='orange', width=1.5)))
#     fig.add_trace(go.Scatter(x=df.index, y=df['trend_sma_slow'], name='200-Day SMA', line=dict(color='purple', width=1.5)))
#     fig.update_layout(title_text=f'<b>{stock_name} Price Chart with Key Moving Averages</b>', yaxis_title=f'Price ({currency_symbol})', xaxis_rangeslider_visible=False, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
#     return fig

# # --- Sidebar ---
# with st.sidebar:
#     st.header("⚙️ Configuration")
#     analysis_region = st.radio("Select Market", ["🇺🇸 US", "🇮🇳 India (NSE)"], key="market_selector")
    
#     ticker = None
#     if analysis_region == "🇮🇳 India (NSE)" and nse_stocks_df is not None:
#         selected_stock = st.selectbox("Search for an NSE Stock", options=nse_stocks_df['Display'])
#         ticker = nse_stocks_df[nse_stocks_df['Display'] == selected_stock]['Symbol'].iloc[0]
#     else:
#         ticker = st.text_input("Enter a US Ticker Symbol", "AAPL")

#     start_date = st.date_input("Start Date", pd.to_datetime("2023-01-01"))
#     end_date = st.date_input("End Date", pd.to_datetime(date.today()))
#     run_button = st.button("🔬 Run Deep Dive", use_container_width=True)

# # --- Main Page ---
# if run_button and ticker:
#     with st.spinner(f"Running full analysis for {ticker}..."):
#         results = orchestrator.run_deep_dive_analysis(ticker, str(start_date), str(end_date))

#     stock_name = results.get("stock_name", ticker)
#     st.header(f"Deep Dive for {stock_name} ({ticker})")

#     if "error" in results:
#         st.error(f"Analysis failed. Reason: {results['error']}")
#     else:
#         snapshot = results.get("snapshot", {})
#         quote = results.get("live_quote", {})
#         hist = results.get("historical_data", pd.DataFrame())
#         financials = results.get("financials", {})
#         ownership = results.get("ownership", {})
#         actions = results.get("corporate_actions", {})
#         recommendations = results.get("analyst_recommendations", pd.DataFrame())
#         currency_symbol = "₹" if snapshot.get("currency") == "INR" else "$"

#         tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Overview", "📈 Price Chart", "💰 Financials", "🏢 Ownership", "⭐ Analyst Ratings"])

#         with tab1:
#             st.subheader("Key Metrics")
#             cols = st.columns(4); cols[0].metric("Live Price", f"{currency_symbol}{quote.get('c', 0):,.2f}"); cols[1].metric("Market Cap", f"{currency_symbol}{snapshot.get('marketCap', 0)/1e9:,.2f}B"); cols[2].metric("Trailing P/E", f"{snapshot.get('trailingPE', 0):.2f}"); cols[3].metric("Div. Yield", f"{snapshot.get('dividendYield', 0) * 100:.2f}%")
            
#             st.subheader("Company Profile")
#             st.markdown(f"**Sector:** {snapshot.get('sector', 'N/A')} | **Industry:** {snapshot.get('industry', 'N/A')} | **Country:** {snapshot.get('country', 'N/A')}")
#             st.markdown(snapshot.get('longBusinessSummary', 'No business summary available.'))
#             st.divider()

#             st.subheader("Dividends & Splits")
#             d_cols = st.columns(2)
#             div_df = actions.get("dividends", pd.DataFrame())
#             if not div_df.empty:
#                 div_df['Date'] = pd.to_datetime(div_df['Date']).dt.strftime('%Y-%m-%d')
#                 d_cols[0].write("Recent Dividends:")
#                 d_cols[0].dataframe(div_df.head(), hide_index=True, use_container_width=True)
#             splits_df = actions.get("splits", pd.DataFrame())
#             if not splits_df.empty:
#                 d_cols[1].write("Stock Splits:")
#                 d_cols[1].dataframe(splits_df, use_container_width=True)

#         with tab2:
#             if not hist.empty: st.plotly_chart(create_price_chart(hist, stock_name, currency_symbol), use_container_width=True)
#             else: st.warning("Historical price data not available.")

#         with tab3:
#             st.subheader("Financial Statements (Annual)")
#             income_df, balance_df, cash_df = financials.get("income_statement"), financials.get("balance_sheet"), financials.get("cash_flow")
#             if not income_df.empty:
#                 st.write("Income Statement")
#                 st.dataframe(income_df.map(format_large_number), use_container_width=True)
#             if not balance_df.empty:
#                 st.write("Balance Sheet")
#                 st.dataframe(balance_df.map(format_large_number), use_container_width=True)
#             if not cash_df.empty:
#                 st.write("Cash Flow")
#                 st.dataframe(cash_df.map(format_large_number), use_container_width=True)

#         with tab4:
#             st.subheader("Share Ownership")
#             major_df, inst_df = ownership.get("major_holders"), ownership.get("institutional_holders")
#             if major_df is not None and not major_df.empty:
#                 st.write("Major Holders:")
#                 st.dataframe(major_df, use_container_width=True)
#             else: st.info("Major Holders: Data not available.")
            
#             st.divider()

#             if inst_df is not None and not inst_df.empty:
#                 st.write("Top 10 Institutional Holders:")
#                 display_df = inst_df.copy()
#                 rename_map = {'Holder': 'Firm', 'Shares': 'Shares Held', '% Out': 'Stake (%)'}
#                 cols_to_rename = {k: v for k, v in rename_map.items() if k in display_df.columns}
#                 display_df.rename(columns=cols_to_rename, inplace=True)
#                 if 'Shares Held' in display_df.columns: display_df['Shares Held'] = display_df['Shares Held'].apply(lambda x: f"{x:,}")
#                 if 'Stake (%)' in display_df.columns: display_df['Stake (%)'] = display_df['Stake (%)'].apply(lambda x: f"{x*100:.2f}%")
#                 final_cols = [col for col in ['Firm', 'Shares Held', 'Stake (%)', 'Value'] if col in display_df.columns]
#                 st.dataframe(display_df[final_cols].head(10), use_container_width=True, hide_index=True)
#             else: st.info("Institutional Holders: Data not available.")

#         with tab5:
#             st.subheader("Recent Analyst Ratings")

#             if recommendations is not None and not recommendations.empty:
#                 try:
#                     # Use the clean 'Date' column from YFinanceAgent
#                     rec_df = recommendations.copy()

#                     # Select only the relevant columns if they exist
#                     desired_cols_map = {
#                         'Date': 'Date',
#                         'Firm': 'Firm',
#                         'To Grade': 'Rating',
#                         'Action': 'Change Type'
#                     }
#                     available_cols = [col for col in desired_cols_map.keys() if col in rec_df.columns]
#                     display_df = rec_df[available_cols].rename(columns=desired_cols_map)

#                     # Format Date for display
#                     display_df['Date'] = display_df['Date'].dt.strftime('%Y-%m-%d')

#                     # Display top 20 most recent recommendations
#                     st.dataframe(display_df.head(20), width='stretch', hide_index=True)

#                 except Exception as e:
#                     st.error(f"An error occurred while processing analyst ratings: {e}")
#                     st.dataframe(recommendations)
#             else:
#                 st.info("Analyst Ratings: Data not available for this stock.")


# import streamlit as st
# import pandas as pd
# import plotly.graph_objects as go
# from datetime import date
# import sys
# from pathlib import Path

# # Ensure custom modules are importable
# sys.path.append(str(Path(__file__).parent.parent))
# from agents.orchestrator import Orchestrator

# st.set_page_config(page_title="Deep Dive Analysis", layout="wide")
# st.title("🔬 Single-Stock Deep Dive Analysis")

# @st.cache_resource
# def load_orchestrator():
#     """Loads the orchestrator instance using a robust, relative path."""
#     # --- THIS IS THE FIX ---
#     # This path goes up one level from the 'pages' directory to the project root
#     # to find the config file. It uses forward slashes for compatibility.
#     config_path = "quant-company-insights-agent\config.yaml"
#     return Orchestrator.from_file(config_path)

# @st.cache_data
# def load_nse_stock_list():
#     """Loads the Nifty 500 stock list for the dropdown selector."""
#     try:
#         project_root = Path(__file__).parent.parent
#         nse_file_path = project_root / "data" / "nifty500.csv"
#         df = pd.read_csv(nse_file_path)
#         df['Display'] = df['Company Name'] + " (" + df['Symbol'] + ")"
#         return df.sort_values("Company Name")
#     except FileNotFoundError:
#         st.error("CRITICAL ERROR: 'nifty500.csv' not found.")
#         return None

# orchestrator = load_orchestrator()
# nse_stocks_df = load_nse_stock_list()

# def format_large_number(num):
#     if num is None or not isinstance(num, (int, float)): return "N/A"
#     if abs(num) >= 1_000_000_000: return f"{num / 1_000_000_000:,.2f} B"
#     if abs(num) >= 1_000_000: return f"{num / 1_000_000:,.2f} M"
#     return f"{num:,.2f}"

# def create_price_chart(df, stock_name, currency_symbol="$"):
#     fig = go.Figure()
#     fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'))
#     fig.add_trace(go.Scatter(x=df.index, y=df['trend_sma_fast'], name='50-Day SMA', line=dict(color='orange', width=1.5)))
#     fig.add_trace(go.Scatter(x=df.index, y=df['trend_sma_slow'], name='200-Day SMA', line=dict(color='purple', width=1.5)))
#     fig.update_layout(title=f'{stock_name} Price Chart', yaxis_title=f'Price ({currency_symbol})', xaxis_rangeslider_visible=False, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
#     return fig

# # --- Sidebar ---
# with st.sidebar:
#     st.header("⚙️ Configuration")
#     analysis_region = st.radio("Select Market", ["🇺🇸 US", "🇮🇳 India (NSE)"], key="market_selector")
    
#     ticker = None
#     if analysis_region == "🇮🇳 India (NSE)" and nse_stocks_df is not None:
#         selected_stock = st.selectbox("Search for an NSE Stock", options=nse_stocks_df['Display'])
#         ticker = nse_stocks_df[nse_stocks_df['Display'] == selected_stock]['Symbol'].iloc[0]
#     else:
#         ticker = st.text_input("Enter a US Ticker Symbol", "AAPL")

#     start_date = st.date_input("Start Date", pd.to_datetime("2023-01-01"))
#     end_date = st.date_input("End Date", pd.to_datetime(date.today()))
#     run_button = st.button("🔬 Run Deep Dive", use_container_width=True)

# # --- Main Page ---
# if run_button and ticker:
#     with st.spinner(f"Running full analysis for {ticker}..."):
#         results = orchestrator.run_deep_dive_analysis(ticker, str(start_date), str(end_date))

#     stock_name = results.get("stock_name", ticker)
#     st.header(f"Deep Dive for {stock_name} ({ticker})")

#     if "error" in results:
#         st.error(f"Analysis failed. Reason: {results['error']}")
#     else:
#         snapshot = results.get("snapshot", {})
#         quote = results.get("live_quote", {})
#         hist = results.get("historical_data", pd.DataFrame())
#         financials = results.get("financials", {})
#         ownership = results.get("ownership", {})
#         actions = results.get("corporate_actions", {})
#         recommendations = results.get("analyst_recommendations", pd.DataFrame())
#         currency_symbol = "₹" if snapshot.get("currency") == "INR" else "$"

#         tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Overview", "📈 Price Chart", "💰 Financials", "🏢 Ownership", "⭐ Analyst Ratings"])

#         with tab1:
#             st.subheader("Key Metrics")
#             cols = st.columns(4)
#             cols[0].metric("Live Price", f"{currency_symbol}{quote.get('c', 0):,.2f}")
#             cols[1].metric("Market Cap", f"{currency_symbol}{snapshot.get('marketCap', 0)/1e9:,.2f}B")
#             cols[2].metric("Trailing P/E", f"{snapshot.get('trailingPE', 0):.2f}")
#             cols[3].metric("Div. Yield", f"{snapshot.get('dividendYield', 0) * 100:.2f}%")
#             st.subheader("Dividends & Splits")
#             d_cols = st.columns(2)
#             div_df = actions.get("dividends", pd.DataFrame())
#             if not div_df.empty:
#                 div_df['Date'] = pd.to_datetime(div_df['Date']).dt.strftime('%Y-%m-%d')
#                 d_cols[0].write("Recent Dividends:")
#                 d_cols[0].dataframe(div_df.head(), hide_index=True)
#             d_cols[1].write("Stock Splits:")
#             d_cols[1].dataframe(actions.get("splits", pd.DataFrame()))

#         with tab2:
#             if not hist.empty: st.plotly_chart(create_price_chart(hist, stock_name, currency_symbol), use_container_width=True)

#         with tab3:
#             st.subheader("Financial Statements")
#             income_df, balance_df, cash_df = financials.get("income_statement"), financials.get("balance_sheet"), financials.get("cash_flow")
            
#             # --- FIX: Use .map instead of the deprecated .applymap ---
#             if not income_df.empty:
#                 st.write("Income Statement (Annual)")
#                 st.dataframe(income_df.map(format_large_number))
#             if not balance_df.empty:
#                 st.write("Balance Sheet (Annual)")
#                 st.dataframe(balance_df.map(format_large_number))
#             if not cash_df.empty:
#                 st.write("Cash Flow (Annual)")
#                 st.dataframe(cash_df.map(format_large_number))

#         with tab4:
#             st.subheader("Share Ownership")
#             major_df = ownership.get("major_holders")
#             inst_df = ownership.get("institutional_holders")
            
#             if major_df is not None and not major_df.empty:
#                 st.write("Major Holders:")
#                 st.dataframe(major_df, use_container_width=True)
#             else:
#                 st.write("Major Holders: Data not available.")

#             st.divider()

#             if inst_df is not None and not inst_df.empty:
#                 st.write("Top 10 Institutional Holders:")
                
#                 # --- THIS IS THE FIX: Check for columns before using them ---
#                 display_df = inst_df.copy()
                
#                 # Define the columns we want to rename and format
#                 rename_map = {'Holder': 'Firm', 'Shares': 'Shares Held', '% Out': 'Stake (%)'}
                
#                 # Find which of the columns to be renamed actually exist
#                 columns_to_rename = {k: v for k, v in rename_map.items() if k in display_df.columns}
#                 display_df.rename(columns=columns_to_rename, inplace=True)

#                 # Format the 'Shares Held' column only if it exists
#                 if 'Shares Held' in display_df.columns:
#                     display_df['Shares Held'] = display_df['Shares Held'].apply(lambda x: f"{x:,}")

#                 # Format the 'Stake (%)' column only if it exists
#                 if 'Stake (%)' in display_df.columns:
#                     display_df['Stake (%)'] = display_df['Stake (%)'].apply(lambda x: f"{x*100:.2f}%")

#                 # Define the final list of columns to show, based on what's available
#                 final_columns_to_show = [col for col in ['Firm', 'Shares Held', 'Stake (%)', 'Value'] if col in display_df.columns]
                
#                 st.dataframe(display_df[final_columns_to_show].head(10), use_container_width=True, hide_index=True)
#             else:
#                 st.write("Top 10 Institutional Holders: Data not available.")
#         with tab5:
#             st.subheader("Recent Analyst Ratings")
#             if not recommendations.empty:
#                 # --- THIS IS THE FIX ---
#                 # Turn the index (which contains the dates) into a regular column
#                 rec_df = recommendations.copy().reset_index()

#                 # Get the name of the first column, which is our date column
#                 # This works even if yfinance changes the index name from 'Date' to something else
#                 date_column_name = rec_df.columns[0]
                
#                 # Format the date column to be more readable
#                 rec_df[date_column_name] = pd.to_datetime(rec_df[date_column_name]).dt.strftime('%Y-%m-%d')

#                 # Rename the date column to 'Date' for consistent display
#                 rec_df.rename(columns={date_column_name: 'Date'}, inplace=True)

#                 # Select and rename the other important columns
#                 display_df = rec_df[['Date', 'Firm', 'To Grade', 'Action']].rename(columns={
#                     'To Grade': 'Rating',
#                     'Action': 'Change Type'
#                 })

#                 # Sort by the most recent recommendations first and display
#                 st.dataframe(display_df.sort_values(by='Date', ascending=False).head(20), use_container_width=True, hide_index=True)
#             else:
#                 st.write("No analyst recommendations were found for this stock.")