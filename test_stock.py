import os
from dotenv import load_dotenv
from agents.stock_agent import StockSelectionAgent
from utils.llm_manager import LLMManager

load_dotenv(r"..\.env")

def test_stock_agent():
    print("🚀 Initializing Stock Agent...")
    
    llm = LLMManager(temperature=0)
    agent = StockSelectionAgent(llm)
    
    # Mock state
    state = {
        "selected_sector": "Semiconductors", # Specific for testing
        "market": "US",
        "messages": [],
        "errors": []
    }
    
    print("\n--- Running Stock Selection Pipeline ---")
    result = agent(state)
    
    if "errors" in result and result["errors"]:
        print(f"❌ Error: {result['errors']}")
    else:
        print("✓ Agent execution successful")
        print(f"Selected: {result['selected_stock']['Ticker']}")
        print(f"Reason: {result['selected_stock']['Reason']}")
        print("\n--- Research ---")
        print(result['stock_research'])

if __name__ == "__main__":
    test_stock_agent()
