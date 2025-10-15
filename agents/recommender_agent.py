import os
import json
import streamlit as st
from typing import Dict, Any

# --- Graceful Dependency Imports ---
try:
    import google.generativeai as genai
    _HAS_GEMINI = True
except ImportError:
    genai, _HAS_GEMINI = None, False

class RecommenderAgent:
    def __init__(self, gemini_api_key: str):
        """
        Initializes the AI Investment Consultant Agent using the Gemini API.
        """
        self.gemini_client = None
        if _HAS_GEMINI and gemini_api_key:
            try:
                genai.configure(api_key=gemini_api_key)
                # Use a powerful model for nuanced, personalized advice
                self.gemini_client = genai.GenerativeModel("gemini-1.5-pro-latest")
                print("[SUCCESS] RecommenderAgent: Initialized with Gemini 1.5 Pro.")
            except Exception as e:
                print(f"[WARNING] RecommenderAgent: Gemini client initialization failed: {e}")
        else:
            print("[WARNING] RecommenderAgent: Gemini API key not provided or google.generativeai not installed.")

    def generate_recommendation(self, user_profile: Dict[str, Any], market_context: Dict[str, Any]) -> str:
        """
        Generates a personalized investment recommendation.
        
        Args:
            user_profile (dict): A dictionary describing the user's financial situation and goals.
            market_context (dict): A dictionary containing all the data gathered by other agents.
        
        Returns:
            str: A formatted markdown report with personalized advice.
        """
        if not self.gemini_client:
            return "## AI Consultant Offline\n\nThe LLM client is not available."

        print("RecommenderAgent: Generating personalized investment plan...")
        
        # --- This is the Persona-Driven Master Prompt ---
        prompt = f"""
        You are "QuantVest AI," a world-class, certified financial advisor. Your primary goal is to provide safe, actionable, and personalized investment advice. You are a fiduciary, always acting in the best interest of your client.

        **CLIENT PROFILE:**
        - **Profession:** {user_profile.get("profession", "Not specified")}
        - **Investment Goal:** {user_profile.get("goal", "Not specified")}
        - **Risk Tolerance:** {user_profile.get("risk", "Not specified")}
        - **Time Horizon:** {user_profile.get("horizon", "Not specified")}

        **COMPREHENSIVE MARKET DATA ANALYSIS (Your Research):**
        ```json
        {json.dumps(market_context, indent=2, default=str)}
        ```

        **TASK:**
        Based on the client's unique profile AND your comprehensive market research, create a personalized investment recommendation plan. Structure your response in clear, easy-to-understand Markdown.

        **REPORT STRUCTURE:**
        1.  **Opening Statement:** Start by acknowledging the client's specific profile and goals in a reassuring and professional tone.
        2.  **Investment Strategy Recommendation:**
            -   Based on their profile, recommend a primary investment strategy (e.g., "Long-Term Growth," "Balanced Dividend Income," "Aggressive Short-Term Trading").
            -   **Justify your choice.** Explain *why* this strategy aligns with their profession, goals, and risk tolerance (e.g., "As a student with a long time horizon and a goal of saving for a startup, an aggressive growth-focused strategy is appropriate...").
        3.  **Asset Allocation Suggestions:**
            -   Suggest a simple asset allocation.
            -   From the provided market data, recommend specific stocks, ETFs, or sectors that fit the strategy. For example, if recommending growth, point to the top-performing stocks from the `short_term_backtest_results` or the top `sector_analysis`. If recommending value, reference the `long_term_analysis`.
            -   **Provide the "why."** (e.g., "Consider an initial position in NVDA. Our analysis shows it has strong momentum (25% return in backtests) and aligns with the outperforming Technology sector.")
        4.  **Risk Management Advice:**
            -   Provide 2-3 bullet points of crucial, personalized risk management advice (e.g., "For your aggressive strategy, it is critical to use a stop-loss on all trades," or "For your long-term savings goal, consider Dollar-Cost Averaging into an ETF like SPY to mitigate market timing risk.").
        5.  **Disclaimer:** Conclude with a standard financial advisor disclaimer.

        Your response should be empathetic, data-driven, and empowering.
        """
        
        try:
            response = self.gemini_client.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"❌ RecommenderAgent ERROR: {e}")
            return f"## Recommendation Generation Failed\n\n**Error during API call:** {e}"

# --- Streamlit Showcase ---
if __name__ == "__main__":
    st.set_page_config(page_title="AI Investment Consultant", layout="wide")
    st.title("🤖 AI Investment Consultant")
    st.markdown("Get a personalized investment plan based on your profile and live market data.")

    GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY"))

    if not GEMINI_KEY:
        st.error("GEMINI_API_KEY not found! This agent requires a Gemini API key.")
    else:
        agent = RecommenderAgent(gemini_api_key=GEMINI_KEY)
        
        # --- User Profile Input ---
        st.sidebar.header("👤 Your Profile")
        profession = st.sidebar.selectbox("What is your profession?", ["Student", "Salaried Professional", "Business Owner"])
        goal = st.sidebar.selectbox("What is your primary investment goal?", ["Maximum Savings (Long-Term Growth)", "Steady Income (Dividends)", "Funding a Startup (Aggressive Growth)"])
        risk = st.sidebar.selectbox("What is your risk tolerance?", ["Low", "Medium", "High (Aggressive)"])
        horizon = st.sidebar.selectbox("What is your time horizon?", ["Short-Term (< 2 years)", "Medium-Term (2-5 years)", "Long-Term (5+ years)"])
        
        user_profile = {"profession": profession, "goal": goal, "risk": risk, "horizon": horizon}

        # --- Mock Market Context (In a real app, this comes from the Orchestrator) ---
        mock_market_context = {
            "long_term_analysis": { "KO": { "Dividend Investing": { "Dividend Yield": "3.10%" }}},
            "short_term_backtest_results": [
                {"Ticker": "NVDA", "Strategy": "Momentum", "Total Return %": 45.8},
                {"Ticker": "SPY", "Strategy": "SMA Crossover", "Total Return %": 12.1}
            ]
        }
        
        if st.sidebar.button("💡 Get My Personalized Plan", use_container_width=True):
            st.header("Your Personalized Investment Recommendation")
            with st.spinner("Your AI consultant is analyzing the markets and tailoring a plan for you..."):
                recommendation = agent.generate_recommendation(user_profile, mock_market_context)
                st.markdown(recommendation)