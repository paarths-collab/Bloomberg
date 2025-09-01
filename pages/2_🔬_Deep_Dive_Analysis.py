import streamlit as st
import sys
import pathlib
import pandas as pd
import plotly.express as px

# Ensure the app can find the custom modules
sys.path.append(str(pathlib.Path(__file__).parent.parent))
from agents.orchestrator import Orchestrator
from utils.data_loader import get_company_snapshot # Import the function to get the symbol

st.set_page_config(page_title="Deep Dive Analysis", layout="wide")
st.title("🔬 Single-Stock Deep Dive Analysis")

@st.cache_resource
def load_orchestrator():
    config_path = "quant-company-insights-agent/config.yaml"
    return Orchestrator.from_file(config_path)

orchestrator = load_orchestrator()

with st.sidebar:
    st.header("⚙️ Configuration")
    ticker = st.text_input("Enter Ticker Symbol", "AAPL")
    start_date = st.date_input("Start Date", pd.to_datetime("2023-01-01"))
    end_date = st.date_input("End Date", pd.to_datetime("today"))
    run_button = st.button("🔬 Run Deep Dive", use_container_width=True)

if run_button:
    st.header(f"Deep Dive Analysis for {ticker}")
    with st.spinner(f"Running multi-agent analysis for {ticker}..."):
        # Corrected: Removed the redundant .date() calls
        results = orchestrator.run_deep_dive_analysis(ticker, str(start_date), str(end_date))

        if "error" in results.get("snapshot", {}):
            st.error(f"Could not retrieve data for {ticker}. Reason: {results['snapshot']['error']}")
        else:
            # Display all the different analysis sections
            snapshot = results.get("snapshot", {})
            quote = results.get("live_quote", {})
            news = results.get("news_sentiment", {})
            social = results.get("social_sentiment", {})
            insider = results.get("insider_analysis", {})
            
            # --- Get the correct currency symbol ---
            currency_symbol = snapshot.get("currencySymbol", "$")

            # --- Header ---
            st.subheader(f"{snapshot.get('longName', ticker)}")
            cols = st.columns(4)
            # Use the dynamic currency symbol in the metrics
            cols[0].metric("Live Price", f"{currency_symbol}{quote.get('c', 0):.2f}")
            cols[1].metric("Previous Close", f"{currency_symbol}{quote.get('pc', 0):.2f}")
            cols[2].metric("Sector", snapshot.get('sector', 'N/A'))
            cols[3].metric("Market Cap", f"{currency_symbol}{snapshot.get('marketCap', 0)/1e9:.2f}B")

            # --- Sentiment Tab ---
            st.subheader("Sentiment Analysis")
            sentiment_cols = st.columns(2)
            sentiment_cols[0].metric("News Sentiment Score", f"{news.get('avg_score', 0):.3f}")
            sentiment_cols[1].metric("Reddit Sentiment", social.get("Overall Social Sentiment", "N/A"))
            
            with st.expander("Top News Headlines"):
                for headline in news.get("headlines", []):
                    st.markdown(f"- {headline}")

            # --- Insider Tab ---
            st.subheader("Insider Analysis")
            insider_summary = insider.get("summary", {})
            insider_cols = st.columns(3)
            insider_cols[0].metric("Recent Buys", insider_summary.get("Recent Buys (Count)", 0))
            insider_cols[1].metric("Recent Sells", insider_summary.get("Recent Sells (Count)", 0))
            insider_cols[2].metric("Net Sentiment", insider_summary.get("Net Sentiment", "N/A"))

            with st.expander("Recent Insider Transactions"):
                st.dataframe(insider.get("transactions", pd.DataFrame()))




# import streamlit as st
# import sys
# import pathlib
# import pandas as pd
# import plotly.express as px

# sys.path.append(str(pathlib.Path(__file__).parent.parent))
# from agents.orchestrator import Orchestrator

# st.set_page_config(page_title="Deep Dive Analysis", layout="wide")
# st.title("🔬 Single-Stock Deep Dive Analysis")

# @st.cache_resource
# def load_orchestrator():
#     config_path = "quant-company-insights-agent/config.yaml"
#     return Orchestrator.from_file(config_path)

# orchestrator = load_orchestrator()

# with st.sidebar:
#     st.header("⚙️ Configuration")
#     ticker = st.text_input("Enter Ticker Symbol", "AAPL")
#     start_date = st.date_input("Start Date", pd.to_datetime("2023-01-01"))
#     end_date = st.date_input("End Date", pd.to_datetime("today"))
#     run_button = st.button("🔬 Run Deep Dive", use_container_width=True)

# if run_button:
#     st.header(f"Deep Dive Analysis for {ticker}")
#     with st.spinner(f"Running multi-agent analysis for {ticker}..."):
#         results = orchestrator.run_deep_dive_analysis(ticker, str(start_date), str(end_date))

#         if "error" in results:
#             st.error(results["error"])
#         else:
#             # Display all the different analysis sections
#             snapshot = results.get("snapshot", {})
#             quote = results.get("live_quote", {})
#             news = results.get("news_sentiment", {})
#             social = results.get("social_sentiment", {})
#             insider = results.get("insider_analysis", {})

#             # --- Header ---
#             st.subheader(f"{snapshot.get('longName', ticker)}")
#             cols = st.columns(4)
#             cols[0].metric("Live Price", f"${quote.get('c', 0):.2f}")
#             cols[1].metric("Previous Close", f"${quote.get('pc', 0):.2f}")
#             cols[2].metric("Sector", snapshot.get('sector', 'N/A'))
#             cols[3].metric("Market Cap", f"${snapshot.get('marketCap', 0)/1e9:.2f}B")

#             # --- Sentiment Tab ---
#             st.subheader("Sentiment Analysis")
#             sentiment_cols = st.columns(2)
#             sentiment_cols[0].metric("News Sentiment Score", f"{news.get('avg_score', 0):.3f}")
#             sentiment_cols[1].metric("Reddit Sentiment", social.get("Overall Social Sentiment", "N/A"))
            
#             with st.expander("Top News Headlines"):
#                 for headline in news.get("headlines", []):
#                     st.markdown(f"- {headline}")

#             # --- Insider Tab ---
#             st.subheader("Insider Analysis")
#             insider_summary = insider.get("summary", {})
#             insider_cols = st.columns(3)
#             insider_cols[0].metric("Recent Buys", insider_summary.get("Recent Buys (Count)", 0))
#             insider_cols[1].metric("Recent Sells", insider_summary.get("Recent Sells (Count)", 0))
#             insider_cols[2].metric("Net Sentiment", insider_summary.get("Net Sentiment", "N/A"))

#             with st.expander("Recent Insider Transactions"):
#                 st.dataframe(insider.get("transactions", pd.DataFrame()))