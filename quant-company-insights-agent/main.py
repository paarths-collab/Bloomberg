
# main.py
import argparse
from agents.orchestrator import Orchestrator

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, default=None, help="Ticker symbol, e.g., AAPL or INFY.NS")
    args = parser.parse_args()

    orch = Orchestrator.from_file("quant-company-insights-agent\config.yaml")
    ticker = args.ticker or orch.sets.get("default_ticker", "AAPL")

    result = orch.run_once(ticker)
    orch.pretty_print(result)

if __name__ == "__main__":
    main()
'''
# In main.py
import argparse
import sys # Import the sys module
from agents.orchestrator import Orchestrator

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, default=None, help="Ticker symbol, e.g., AAPL or INFY.NS")
    args = parser.parse_args()

    orch = Orchestrator.from_file("quant-company-insights-agent\config.yaml")
    ticker = args.ticker or orch.sets.get("default_ticker", "AAPL")

    # --- ADD THIS VALIDATION BLOCK ---
    if not ticker or not isinstance(ticker, str) or ticker.strip() == "":
        print("ERROR: No valid ticker symbol provided.")
        print("Please provide a ticker using the --ticker argument or set a default_ticker in config.yaml.")
        sys.exit(1) # Exit the program with an error code
    # --- END OF VALIDATION BLOCK ---

    result = orch.run_once(ticker)
    
    if result:
        orch.pretty_print(result)
    else:
        print(f"\nAnalysis for {ticker} could not be completed.")

if __name__ == "__main__":
    main()
'''