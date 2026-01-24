import os
from dotenv import load_dotenv
from agents.input_agent import InputStructurerAgent
from utils.llm_manager import LLMManager

# Load environment variables
load_dotenv(r"..\.env")

def test_input_agent():
    print("🚀 Initializing Input Agent with Multi-Key LLM Manager...")
    
    # Initialize Manager (which handles rotation)
    try:
        llm = LLMManager(temperature=0)
    except Exception as e:
        print(f"❌ Initialization Failed: {e}")
        return
    
    print(f"✓ Manager Initialized with {len(llm.gemini_keys)} keys found.")

    # Initialize Agent
    agent = InputStructurerAgent(llm)
    
    # Test Data
    raw_input = """
    I earn $5000 a month and have $20k in savings. 
    I want to save for a house in 5 years (medium term).
    I am a conservative investor.
    """
    
    state = {
        "raw_input": raw_input,
        "messages": [],
        "errors": []
    }
    
    print("\n--- Running Input Agent ---")
    try:
        result = agent(state)
        
        if "errors" in result and result["errors"]:
            print(f"❌ Error: {result['errors']}")
        else:
            print("✓ Agent execution successful")
            print("\n--- User Profile ---")
            print(result["user_profile"])
            
    except Exception as e:
        print(f"❌ Execution Error: {e}")

if __name__ == "__main__":
    test_input_agent()
