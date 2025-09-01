import streamlit as st

# --- Page Configuration ---
# This should be the first Streamlit command in your script.
st.set_page_config(
    page_title="QuantInsights - Home",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://github.com/your_repo/issues', # Optional: Add a link to your repo
        'About': "# QuantInsights Financial Analysis Platform"
    }
)

# --- Main Homepage Content ---

st.title("Welcome to the QuantInsights Financial Analysis Platform 🚀")

st.markdown("""
This platform integrates a suite of powerful, AI-enhanced tools designed for both professional analysts and aspiring investors. It provides a comprehensive market overview, deep stock analysis, robust strategy backtesting, and personalized AI-driven advice.

---

### **Navigation Guide:**

Use the sidebar on the left to navigate to the different analysis modules available in your toolkit.

-   **📈 Market Overview:**
    Get a high-level snapshot of global, US, and Indian market health to understand the current economic environment.

-   **🔬 Deep Dive Analysis:**
    Perform a comprehensive, multi-agent analysis on a single stock, covering fundamentals, technicals, news sentiment, insider activity, and more.

-   **📊 Strategy Backtester:**
    Test and compare the performance of over a dozen quantitative trading strategies on any stock with your custom parameters.

-   **🤖 AI Consultant:**
    Receive a personalized investment plan based on your unique financial profile and goals, synthesized by a powerful Large Language Model.

-   **💸 Paper Trading:**
    Connect to your Alpaca paper trading account to view your live portfolio and simulate trades in a risk-free environment.

**Select a page from the sidebar to begin your analysis!**
""")

# You can add more to your homepage later, like a "Featured Stock of the Day" or a summary of the market overview.
# For now, this serves as a clean and professional landing page.