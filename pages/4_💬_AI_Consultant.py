import streamlit as st
import pandas as pd
import yaml
from pathlib import Path

# --- Must be at the top of the script ---
st.set_page_config(
    page_title="AI Financial Consultant",
    page_icon="💬",
    layout="wide"
)

# --- Imports from your project ---
# Ensure your project's root is in the Python path
from agents.orchestrator import Orchestrator

# --- Load Orchestrator ---
# This is a simplified way to cache the orchestrator instance
@st.cache_resource
def load_orchestrator():
    """Loads the orchestrator from the config file."""
    try:
        # Use a relative path that works from the project's root
        config_path = Path("quant-company-insights-agent/config.yaml")
        if not config_path.exists():
            # Fallback for different execution environments
            config_path = "config.yaml"
        
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        return Orchestrator(config)
    except Exception as e:
        st.error(f"Failed to initialize the application: {e}")
        return None

orchestrator = load_orchestrator()

st.title("💬 AI Financial Consultant")
st.markdown("Your personal AI-powered financial advisor. Ask anything about markets, strategies, or your portfolio.")

# --- THIS IS THE FIX ---
# Check if the LLM agent and its client were successfully initialized.
# This is the new, correct way to check if the AI is ready.
llm_available = orchestrator and orchestrator.llm_agent and orchestrator.llm_agent.llm and orchestrator.llm_agent.llm.client is not None

if not orchestrator:
    st.warning("Could not load the main application. Please check the logs.")
elif not llm_available:
    st.error("The AI Consultant is unavailable. Please ensure your `openrouter` API key is correctly set in the `config.yaml` file.")
else:
    # --- User Profile Input ---
    st.sidebar.header("Your Investor Profile")
    investment_goals = st.sidebar.selectbox(
        "Primary Investment Goal",
        ["Capital Growth", "Regular Income", "Wealth Preservation", "Speculation"]
    )
    risk_tolerance = st.sidebar.slider(
        "Risk Tolerance", 1, 5, 3,
        help="1: Very Low Risk, 5: Very High Risk"
    )
    investment_horizon = st.sidebar.select_slider(
        "Investment Horizon",
        ["Short-term (< 1 year)", "Medium-term (1-5 years)", "Long-term (5+ years)"]
    )

    user_profile_text = f"""
    - **Primary Goal:** {investment_goals}
    - **Risk Tolerance:** {risk_tolerance}/5
    - **Investment Horizon:** {investment_horizon}
    """
    
    with st.expander("View Your Profile"):
        st.markdown(user_profile_text)

    # --- AI Discovery Workflow ---
    st.header("Automated AI Discovery & Planning")
    st.markdown("Let the AI analyze the market, find a top-performing sector and stock, run backtests, and generate a personalized plan for you based on your profile.")
    
    market_choice = st.selectbox("Select a market to analyze:", ["USA", "India"], key="discovery_market")
    
    if st.button("🚀 Run Automated Discovery", use_container_width=True):
        with st.spinner("The AI is performing a deep analysis. This may take a few minutes..."):
            try:
                final_report = orchestrator.run_automated_ai_discovery_and_plan(
                    user_profile_text=user_profile_text,
                    market=market_choice.lower()
                )
                st.markdown("### 🤖 AI-Generated Investment Plan")
                st.markdown(final_report)
            except Exception as e:
                st.error(f"An error occurred during the discovery process: {e}")

    # --- General AI Chat ---
    st.header("Ask a Question")
    st.markdown("You can also ask general financial questions.")
    
    user_query = st.text_area("Your question for the AI:", "What are the current main risks in the global economy?")

    if st.button("Consult AI", use_container_width=True):
        with st.spinner("The AI is thinking..."):
            try:
                # We can create a simple prompt for general questions
                general_prompt = f"""
                You are a helpful financial assistant. Please answer the following question based on your general knowledge.
                Question: {user_query}
                """
                response = orchestrator.llm_agent.run(general_prompt)
                st.markdown("### 🤖 AI Response")
                st.markdown(response)
            except Exception as e:
                st.error(f"An error occurred while consulting the AI: {e}")

    st.info("Please describe your profile in the sidebar, select a market, and click 'Discover & Generate My Plan' to get started.")
# import streamlit as st
# import sys
# import pathlib
# import json
# import pandas as pd # Add pandas for date calculation

# # --- Path setup ---
# sys.path.append(str(pathlib.Path(__file__).parent.parent))
# from agents.orchestrator import Orchestrator

# # --- Page Configuration ---
# st.set_page_config(page_title="AI Consultant", layout="wide")
# st.title("🤖 Your Personal AI Investment Consultant")
# st.markdown("Get a comprehensive, synthesized investment plan from multiple AI analysts based on a full market and stock analysis.")

# # --- Load the Orchestrator ---
# @st.cache_resource
# def load_orchestrator():
#     config_path = "quant-company-insights-agent/config.yaml"
#     print("--- LOADING ORCHESTRATOR FOR AI CONSULTANT PAGE ---")
#     return Orchestrator.from_file(config_path)

# orchestrator = load_orchestrator()

# # --- User Profile & Analysis Input ---
# with st.sidebar:
#     st.header("👤 Your Profile")
    
#     profession = st.selectbox(
#         "Your Profession", 
#         ["Student", "Salaried Professional", "Business Owner"]
#     )
#     # --- NEW: Annual Income Input ---
#     income = st.number_input("Your Annual Income (USD)", min_value=0, value=75000, step=5000)
    
#     goal = st.selectbox(
#         "Your Primary Goal", 
#         ["Maximum Savings (Long-Term Growth)", "Steady Income (Dividends)", "Funding a Startup (Aggressive Growth)"]
#     )
#     risk = st.selectbox(
#         "Your Risk Tolerance", 
#         ["Low", "Medium", "High (Aggressive)"]
#     )
    
#     st.markdown("---")
#     st.header("🔍 Analysis Parameters")

#     market = st.radio("Select Market", ["USA", "India"], horizontal=True)
    
#     # --- NEW: Ticker input for Deep Dive ---
#     analysis_ticker = st.text_input("Stock Ticker to Analyze", "AAPL" if market == "USA" else "RELIANCE")
    
#     # --- NEW: Strategy selection for Combination Builder ---
#     available_strategies = sorted(list(orchestrator.short_term_modules.keys()))
#     default_strategies = ["Momentum", "Mean Reversion (Bollinger Bands)"] if "Momentum" in available_strategies else available_strategies[:2]
#     portfolio_strategies = st.multiselect(
#         "Strategies to Backtest", 
#         options=available_strategies, 
#         default=default_strategies
#     )
    
#     run_button = st.button("💡 Generate My Plan", use_container_width=True)

# # --- Main Panel Execution ---
# if run_button:
#     # Check if the Ollama server is actually available
#     if not orchestrator.llm_agent.ollama_available:
#         st.error("Ollama server not detected. Please ensure Ollama is running on your machine to use the AI Consultant.")
#     elif not analysis_ticker or not portfolio_strategies:
#         st.warning("Please provide a ticker to analyze and select at least one strategy.")
#     else:
#         st.header("Here is Your Personalized & Synthesized Investment Plan")
#         st.info("This report was generated by running a full analysis, getting opinions from both **Llama 3** and **Mistral**, and having a senior AI analyst synthesize the results into a single plan.")

#         # 1. Assemble the complete user profile
#         user_profile = {
#             "profession": profession,
#             "annual_income": income,
#             "goal": goal, 
#             "risk": risk
#         }
        
#         # Define a date range for the analysis (e.g., past 2 years)
#         end_date_str = pd.Timestamp.now().strftime('%Y-%m-%d')
#         start_date_str = (pd.Timestamp.now() - pd.DateOffset(years=2)).strftime('%Y-%m-%d')
        
#         with st.spinner("Performing comprehensive analysis and consulting with AI analysts... This may take a few minutes."):
#             # 2. Call the new Orchestrator method
#             final_recommendation = orchestrator.run_comprehensive_ai_analysis(
#                 user_profile=user_profile,
#                 analysis_ticker=analysis_ticker,
#                 portfolio_strategies=portfolio_strategies,
#                 market=market,
#                 start_date=start_date_str,
#                 end_date=end_date_str
#             )
            
#             # 3. Display the final result
#             st.markdown(final_recommendation)

# else:
#     st.info("Please configure your profile and analysis parameters in the sidebar, then click 'Generate My Plan' to get started.")

# import streamlit as st
# import sys
# import pathlib
# import json

# # --- Path setup to allow importing from the 'agents' directory ---
# sys.path.append(str(pathlib.Path(__file__).parent.parent))
# from agents.orchestrator import Orchestrator

# # --- Page Configuration ---
# st.set_page_config(page_title="AI Consultant", layout="wide")
# st.title("🤖 Your Personal AI Investment Consultant")
# st.markdown("Get a personalized investment plan based on your profile and live market data.")

# # --- Cached Functions for Performance ---

# @st.cache_resource
# def load_orchestrator():
#     """
#     Loads the orchestrator once and caches the resource for the entire session.
#     """
#     config_path = "quant-company-insights-agent/config.yaml"
#     print("--- LOADING ORCHESTRATOR (this should only run once) ---")
#     return Orchestrator.from_file(config_path)

# @st.cache_data(ttl=600) # Cache the AI's response for 10 minutes
# def get_cached_recommendation(_orchestrator, user_profile_json: str):
#     """
#     This wrapper function allows Streamlit to cache the AI's response.
#     We pass the user_profile as a JSON string to make it hashable for the cache.
#     The underscore on _orchestrator tells Streamlit not to hash the complex object.
#     """
#     print(f"--- CACHE MISS: Calling real get_personalized_recommendation for profile: {user_profile_json} ---")
#     # Convert the JSON string back to a dictionary before passing to the orchestrator
#     user_profile = json.loads(user_profile_json)
#     return _orchestrator.get_personalized_recommendation(user_profile)

# # --- Load the Orchestrator ---
# orchestrator = load_orchestrator()

# # --- Sidebar for User Input ---
# # This section is now defined only ONCE.
# with st.sidebar:
#     st.header("👤 Tell Us About Yourself")
    
#     profession = st.selectbox(
#         "Your Profession", 
#         ["Student", "Salaried Professional", "Business Owner"]
#     )
#     goal = st.selectbox(
#         "Your Primary Goal", 
#         ["Maximum Savings (Long-Term Growth)", "Steady Income (Dividends)", "Funding a Startup (Aggressive Growth)"]
#     )
#     risk = st.selectbox(
#         "Your Risk Tolerance", 
#         ["Low", "Medium", "High (Aggressive)"]
#     )
#     horizon = st.selectbox(
#         "Your Time Horizon", 
#         ["Short-Term (< 2 years)", "Medium-Term (2-5 years)", "Long-Term (5+ years)"]
#     )
    
#     # The "Generate My Plan" button is also here.
#     run_button = st.button("💡 Generate My Plan", use_container_width=True)


# # --- Main Panel Execution ---
# # This block runs ONLY when the button in the sidebar is clicked.
# if run_button:
#     st.header("Here is Your Personalized Investment Plan")
    
#     # 1. Assemble the user profile into a dictionary
#     user_profile = {
#         "profession": profession, 
#         "goal": goal, 
#         "risk": risk, 
#         "horizon": horizon
#     }
    
#     with st.spinner("Your AI consultant is analyzing the markets and tailoring a plan for you..."):
#         # 2. Convert profile to a JSON string to make it hashable for caching
#         user_profile_json_string = json.dumps(user_profile, sort_keys=True)
        
#         # 3. Call the cached function with the orchestrator and the hashable profile
#         recommendation_markdown = get_cached_recommendation(orchestrator, user_profile_json_string)
        
#         # 4. Display the result
#         st.markdown(recommendation_markdown)

# else:
#     st.info("Please configure your profile in the sidebar and click 'Generate My Plan' to get started.")