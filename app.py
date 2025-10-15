import streamlit as st

# --- Page Configuration ---
# This should be the first Streamlit command in your script.
st.set_page_config(
    page_title="QuantInsights - Home",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://github.com/your_repo/issues',  # Optional: Add a link to your repo
        'About': "# QuantInsights Financial Analysis Platform\n\nA comprehensive suite of AI-enhanced financial tools for investors and analysts."
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

# Add a section with strategy descriptions
st.divider()
st.markdown("### 🎯 Featured Strategies & Capabilities")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("#### 📈 Trend Following")
    st.markdown("""
    - **EMA Crossover**: Uses exponential moving averages to identify trend changes
    - **SMA Crossover**: Simple moving average crossover strategy for trend following
    - **MACD Strategy**: Momentum-based trend following using MACD indicators
    """)

with col2:
    st.markdown("#### 📉 Mean Reversion")
    st.markdown("""
    - **RSI Strategies**: Uses Relative Strength Index for overbought/oversold signals
    - **Bollinger Bands**: Mean reversion strategy using volatility bands
    - **Support/Resistance**: Trade at key price levels
    """)

with col3:
    st.markdown("#### ⚡ Breakout & Momentum")
    st.markdown("""
    - **Breakout Strategy**: Identifies price breakouts above resistance levels
    - **Channel Trading**: Uses Donchian channels to identify breakouts
    - **Momentum Strategy**: Captures momentum-driven price moves
    """)

# Add information about the platform's benefits
st.divider()
st.markdown("### 🌟 Key Features & Benefits")

info_cols = st.columns(2)

with info_cols[0]:
    st.markdown("#### 📊 Comprehensive Analysis")
    st.markdown("""
    - **Multi-timeframe Analysis**: Analyze securities across different timeframes
    - **Risk Metrics**: Understand your strategy's risk profile with detailed metrics
    - **Benchmark Comparison**: Compare your strategy against market indices
    - **Interactive Charts**: Engage with dynamic, interactive visualizations
    """)

with info_cols[1]:
    st.markdown("#### 🤖 AI-Powered Insights")
    st.markdown("""
    - **Automated Backtesting**: Test strategies across historical data
    - **Portfolio Optimization**: Optimize asset allocation based on risk tolerance
    - **Real-time Data**: Access latest market data for accurate analysis
    - **Customizable Workflows**: Adapt the platform to your specific needs
    """)

# Add a footer with more information
st.divider()
st.markdown("### 📚 Getting Started Tips")
tips = st.columns(3)

with tips[0]:
    st.markdown("**New User?**")
    st.markdown("""
    - Start with the Strategy Backtester to understand how different approaches work
    - Use sample tickers like AAPL, MSFT, or TSLA for initial testing
    - Explore the Market Overview to understand current conditions
    """)

with tips[1]:
    st.markdown("**Advanced User?**")
    st.markdown("""
    - Customize strategy parameters to match your trading style
    - Combine multiple strategies for portfolio diversification
    - Use the AI Consultant for personalized optimization
    """)

with tips[2]:
    st.markdown("**Questions?**")
    st.markdown("""
    - Check the individual tool documentation in each section
    - Review the metric explanations for deeper understanding
    - Contact support using the 'About' menu above
    """)