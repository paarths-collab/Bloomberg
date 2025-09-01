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

# --- Master Analyst Agent ---
import requests

class LLMAnalystAgent:
    def __init__(self, model="mistral", gemini_api_key: str = None):
        self.model = model
        self.gemini_api_key = gemini_api_key
        self.ollama_available = self.check_ollama()

        if self.gemini_api_key and _HAS_GEMINI:
            genai.configure(api_key=self.gemini_api_key)

    def check_ollama(self) -> bool:
        """Check if Ollama server is running on localhost:11434"""
        try:
            resp = requests.get("http://localhost:11434/api/tags", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def run(self, prompt: str) -> str:
        if self.ollama_available:
            return self.run_ollama(prompt)
        elif self.gemini_api_key:
            return self.run_gemini(prompt)
        else:
            st.error("No LLM provider is available. Please run the Ollama server or provide a Gemini API key.")
            return ""


    def run_ollama(self, prompt: str) -> str:
        url = "http://localhost:11434/api/generate"
        payload = {"model": self.model, "prompt": prompt}
        resp = requests.post(url, json=payload, stream=True)
        output = ""
        for line in resp.iter_lines():
            if line:
                part = line.decode("utf-8")
                # Corrected the line below to safely parse JSON
                if "response" in part:
                    output += json.loads(part)["response"]
        return output.strip()

    def run_gemini(self, prompt: str) -> str:
        if not _HAS_GEMINI:
            return "Error: The 'google-generativeai' library is required. Please install it using 'pip install google-generativeai'."
        try:
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            st.error(f"An error occurred while contacting the Gemini API: {e}")
            return ""

    def generate_brokerage_report(self, context: Dict[str, Any], user_query: str) -> str:
        """
        Generates a professional brokerage report based on the provided context and user query.
        """
        prompt = f"""
        As a senior financial analyst, generate a professional brokerage report.

        **Client Query:** "{user_query}"

        **Available Data Context:**
        {json.dumps(context, indent=2)}

        Based on the data, provide a comprehensive investment analysis and a final recommendation.
        Structure the report with clear headings, such as 'Market Overview', 'Fundamental Analysis',
        'Technical Outlook', 'Sentiment Analysis', and 'Final Recommendation'.
        """
        return self.run(prompt)


# --- Streamlit Showcase ---
if __name__ == "__main__":
    st.set_page_config(page_title="Master AI Analyst", layout="wide")
    st.title("🤖 Master AI Financial Analyst (Gemini 1.5 Pro)")

    GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY"))

    if not GEMINI_KEY:
        st.error("GEMINI_API_KEY not found! This agent requires a Gemini API key.")
    else:
        # Correctly pass the API key to the agent
        agent = LLMAnalystAgent(gemini_api_key=GEMINI_KEY)

        st.info("This showcase simulates the final step of the AI workflow. The Orchestrator would gather all the data below and pass it to this agent.")

        # ... (The rest of your Streamlit showcase code remains the same)