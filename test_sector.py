import os
from dotenv import load_dotenv
from agents.sector_agent import SectorDiscoveryAgent
from utils.llm_manager import LLMManager

load_dotenv(r"..\.env")

def test_sector_agent():
    print("🚀 Initializing Sector Agent...")
    
    llm = LLMManager(temperature=0)
    agent = SectorDiscoveryAgent(llm)
    
    # Mock efficient state
    state = {
        "user_profile": {"preferences": {"risk_tolerance": "Aggressive"}},
        "messages": [],
        "errors": []
    }
    
    print("\n--- Running Sector Analysis ---")
    result = agent(state)
    
    if "errors" in result and result["errors"]:
        print(f"❌ Error: {result['errors']}")
    else:
        print("✓ Agent execution successful")
        print(f"Top Sector: {result['selected_sector']}")
        print(f"Season: {result['current_season']}")
        print(f"News Count: {len(result['sector_news'])}")

if __name__ == "__main__":
    test_sector_agent()
