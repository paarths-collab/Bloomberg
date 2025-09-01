"""
main.py

Main entry point for the multi-flow analysis engine.

This script initializes the Orchestrator and executes a specific analysis
pipeline based on user input. It serves as the command-line interface (CLI)
for the system.

USAGE EXAMPLES:

1. AI-Driven Analysis:
   Finds a promising stock and performs a deep-dive using LLM agents.
   >> python main.py --type ai_driven

2. Short-Term (Quantitative) Analysis:
   Backtests multiple technical strategies for given tickers.
   >> python main.py --type short-term --tickers AAPL,MSFT --start 2023-01-01 --end 2024-01-01

3. Long-Term (Fundamental) Analysis:
   Runs fundamental analysis strategies for given tickers.
   >> python main.py --type long-term --tickers GOOG,AMZN
"""
import argparse
import json
from agents.orchestrator import Orchestrator

def main():
    """
    Main entry point for the analysis engine.
    Parses command-line arguments to run the selected analysis flow.
    """
    parser = argparse.ArgumentParser(description="Run a multi-agent stock analysis pipeline.")
    
    parser.add_argument(
        "--type", 
        type=str, 
        required=True, 
        choices=['ai_driven', 'long-term', 'short-term'],
        help="The type of analysis flow to execute."
    )
    parser.add_argument(
        "--tickers", 
        type=str,
        help="Comma-separated list of tickers for 'long-term' or 'short-term' analysis (e.g., AAPL,MSFT)."
    )
    parser.add_argument(
        "--start", 
        type=str, 
        help="Start date (YYYY-MM-DD) for 'short-term' backtesting."
    )
    parser.add_argument(
        "--end", 
        type=str, 
        help="End date (YYYY-MM-DD) for 'short-term' backtesting."
    )

    args = parser.parse_args()

    # --- Initialize the Orchestrator from the config file ---
    # Ensure your config.yaml is in the root directory or provide the correct path.
    orch = Orchestrator.from_file("config.yaml")

    # --- Execute the selected analysis flow ---
    tickers_list = args.tickers.split(',') if args.tickers else None
    
    results = orch.execute_analysis_flow(
        investor_type=args.type,
        tickers=tickers_list,
        start_date=args.start,
        end_date=args.end
    )
    
    # --- Print the final results from the flow ---
    print("\n" + "="*25 + " FINAL RESULTS " + "="*25)
    if results:
        # Use pretty printing for the JSON/dict output
        print(json.dumps(results, indent=4, default=str))
    else:
        print("The analysis flow did not return any results.")
    print("="*67 + "\n")


if __name__ == "__main__":
    main()

