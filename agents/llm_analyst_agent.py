import os
import json
from typing import Dict, Any
import streamlit as st
from openai import OpenAI

class LLMEngine:
    """
    A dedicated wrapper for the OpenRouter API.
    """
    def __init__(self, api_key: str, model_name: str = "openai/gpt-oss-20b:free"):
        """
        Initializes the OpenRouter client.

        Args:
            api_key (str): The OpenRouter API key.
            model_name (str): The default model to use for requests.
        """
        self.api_key = api_key
        self.model_name = model_name
        
        if not self.api_key:
            raise ValueError("An OpenRouter API key must be provided.")

        try:
            self.client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self.api_key,
            )
            print(f"[SUCCESS] LLMEngine: OpenRouter client initialized with default model: {self.model_name}")
        except Exception as e:
            print(f"[ERROR] LLMEngine: Failed to initialize OpenRouter client: {e}")
            raise

    def run(self, prompt: str, model_name: str = None) -> str:
        """
        Runs the LLM with a given prompt and returns the text response.

        Args:
            prompt (str): The prompt to send to the language model.
            model_name (str, optional): A specific OpenRouter model to use for this request.

        Returns:
            str: The content of the LLM's response.
        """
        if not self.client:
            return "Error: OpenRouter client is not initialized."

        effective_model_name = model_name if model_name else self.model_name

        try:
            completion = self.client.chat.completions.create(
                model=effective_model_name,
                messages=[{"role": "user", "content": prompt}],
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"Error during OpenRouter LLM execution with model {effective_model_name}: {e}")
            return f"An error occurred while contacting the OpenRouter API: {e}"

class LLMAnalystAgent:
    """
    An agent that uses a dedicated OpenRouter LLM engine to perform financial analysis.
    """
    def __init__(self, openrouter_api_key: str):
        """
        Initializes the agent and its underlying OpenRouter engine.

        Args:
            openrouter_api_key (str): The API key for OpenRouter.
        """
        if not openrouter_api_key:
            raise ValueError("An OpenRouter API key is required to initialize the LLMAnalystAgent.")
        
        self.llm = LLMEngine(api_key=openrouter_api_key)

    def run(self, prompt: str, model_name: str = None) -> str:
        """
        Runs the LLM with a given prompt, allowing for a model override.

        Args:
            prompt (str): The input prompt for the language model.
            model_name (str, optional): A specific OpenRouter model to use for this request.
        
        Returns:
            str: The response from the language model.
        """
        return self.llm.run(prompt, model_name=model_name)

# --- Streamlit Showcase (for standalone testing) ---
if __name__ == "__main__":
    st.set_page_config(page_title="OpenRouter AI Analyst", layout="wide")
    st.title("🤖 OpenRouter Financial Analyst")

    OPENROUTER_KEY = st.secrets.get("OPENROUTER_API_KEY", os.getenv("OPENROUTER_API_KEY"))

    if not OPENROUTER_KEY:
        st.error("OPENROUTER_API_KEY not found! Please set it in your Streamlit secrets or environment variables.")
    else:
        agent = LLMAnalystAgent(openrouter_api_key=OPENROUTER_KEY)

        sample_context = {
            "stock_symbol": "NVDA",
            "current_price": 950.00,
            "52_week_high": 974.00,
            "market_cap": "2.37T",
            "recent_news": "Nvidia's earnings report surpassed all expectations, fueled by demand for their AI chips."
        }
        user_query = "Given the strong earnings, is Nvidia still a good buy?"

        st.info("Generating a brokerage report using a model from OpenRouter...")

        test_model = "openai/gpt-3.5-turbo" 

        with st.spinner(f"Analyzing with {test_model}..."):
            prompt = f"""
            As a senior financial analyst, generate a professional brokerage report.
            **Client Query:** "{user_query}"
            
            **Available Data Context:**
            {json.dumps(sample_context, indent=2)}
            
            Based on the data, provide a comprehensive investment analysis and a final recommendation.
            Structure the report with clear headings.
            """
            
            report = agent.run(prompt, model_name=test_model)
            st.markdown(report)

