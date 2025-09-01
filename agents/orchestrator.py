from __future__ import annotations
import yaml
import pandas as pd
import importlib.util
import os
from pathlib import Path
from typing import Dict, Any, List

# --- Import all REAL agents ---
from agents.screener_agent import ScreenerAgent
from agents.llm_analyst_agent import LLMAnalystAgent as LLMAgent
from agents.execution_agent import ExecutionAgent
from agents.macro_agent import MacroAgent
from agents.insider_agent import InsiderAgent
from agents.social_media_sentiment import SentimentAgent

# --- Import all REAL utility modules ---
from utils.data_loader import get_company_snapshot, get_history, add_technical_indicators
from utils.news_fetcher import get_live_quote, get_company_news, calculate_headline_sentiment

def _load_modules_from_path(path: Path, module_prefix: str):
    """Dynamically loads all python modules from a given directory path."""
    modules = {}
    for file_path in path.glob("*.py"):
        if file_path.stem == "__init__":
            continue
        
        module_name = f"{module_prefix}.{file_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            # Use a readable name for the strategy, e.g., "SMA Crossover" from "sma_crossover"
            strategy_name = file_path.stem.replace('_', ' ').title()
            modules[strategy_name] = module
    return modules

class Orchestrator:
    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the entire ecosystem of agents based on the central config file.
        """
        self.cfg = config
        self.keys = self.cfg.get("api_keys", {})
        self.sets = self.cfg.get("agent_settings", {})
        self.rapidapi_cfg = self.cfg.get("rapidapi", {})
        
        print("Orchestrator: Initializing all agents...")
        self._initialize_agents()
        self._register_strategies()
        print("Orchestrator: Initialization complete.")

    def _initialize_agents(self):
        """Creates instances of all agents the orchestrator can use."""
        self.screener_agent = ScreenerAgent(rapidapi_config=self.rapidapi_cfg)
        self.llm_agent = LLMAgent(gemini_api_key=self.keys.get("gemini"))
        self.execution_agent = ExecutionAgent(
            api_key=self.keys.get("alpaca_key_id"),
            api_secret=self.keys.get("alpaca_secret_key"),
            paper=self.sets.get("paper_trading", True)
        )
        self.macro_agent = MacroAgent(fred_api_key=self.keys.get("fred"))
        self.insider_agent = InsiderAgent(
            finnhub_key=self.keys.get("finnhub"),
            rapidapi_config=self.rapidapi_cfg
        )
        self.sentiment_agent = SentimentAgent(
            reddit_client_id=self.keys.get("reddit_client_id"),
            reddit_client_secret=self.keys.get("reddit_client_secret"),
            reddit_user_agent=self.keys.get("reddit_user_agent")
        )

    def _register_strategies(self):
        """Dynamically discovers and registers all available strategy modules."""
        print("Orchestrator: Discovering and registering strategies...")
        # Assuming the script is run from the root 'Boomerang' directory
        long_term_path = Path("Long_Term_Strategy")
        short_term_path = Path("strategies")
        
        self.long_term_modules = _load_modules_from_path(long_term_path, "Long_Term_Strategy")
        self.short_term_modules = _load_modules_from_path(short_term_path, "strategies")
        
        print(f"Registered {len(self.long_term_modules)} long-term strategies.")
        print(f"Registered {len(self.short_term_modules)} short-term strategies.")

    # --- PRIMARY WORKFLOW METHODS CALLED BY THE FRONTEND ---

    def run_deep_dive_analysis(self, ticker: str, start_date: str, end_date: str) -> Dict[str, Any]:
        """Runs a comprehensive, multi-agent analysis on a single stock."""
        print(f"Orchestrator: Running deep-dive analysis for {ticker}...")
        hist_df = get_history(ticker, start_date, end_date)
        if hist_df.empty: return {"error": "Could not fetch historical data."}
        
        enriched_df = add_technical_indicators(hist_df)
        
        snapshot = get_company_snapshot(ticker)
        live_quote = get_live_quote(ticker, self.keys.get("finnhub"))
        news = get_company_news(ticker, self.keys.get("finnhub"))
        headlines = [item.get("headline", "") for item in news]
        news_sentiment = calculate_headline_sentiment(headlines)
        social_sentiment = self.sentiment_agent.analyze(ticker)
        insider_analysis = self.insider_agent.analyze(ticker)

        return {
            "snapshot": snapshot,
            "live_quote": live_quote,
            "news_sentiment": {"avg_score": news_sentiment, "headlines": headlines[:10]},
            "social_sentiment": social_sentiment,
            "insider_analysis": insider_analysis,
            "technical_data": enriched_df.tail(1).to_dict(orient='records')[0] if not enriched_df.empty else {}
        }

    def run_long_term_analysis(self, tickers: List[str]) -> Dict[str, Any]:
        """Runs the suite of long-term fundamental analyses for the given tickers."""
        print(f"Orchestrator: Running long-term analysis for {tickers}...")
        results = {}
        for ticker in tickers:
            results[ticker] = {name: module.analyze(ticker) for name, module in self.long_term_modules.items()}
        return results

    def run_short_term_analysis(self, tickers: List[str], start_date: str, end_date: str) -> pd.DataFrame:
        """Runs the suite of short-term backtests and returns a summary DataFrame."""
        print(f"Orchestrator: Running short-term backtests for {tickers}...")
        all_summaries = []
        for ticker in tickers:
            for name, module in self.short_term_modules.items():
                if name == "Pairs Trading": continue
                try:
                    result_dict = module.run(ticker, start_date, end_date)
                    summary = result_dict.get("summary", {})
                    summary['Strategy'] = name
                    summary['Ticker'] = ticker
                    all_summaries.append(summary)
                except Exception as e:
                    print(f"ERROR running strategy '{name}' for ticker '{ticker}': {e}")
                    # Optionally, append a summary indicating the error
                    all_summaries.append({'Strategy': name, 'Ticker': ticker, 'Error': str(e)})


        if len(tickers) >= 2 and "Pairs Trading" in self.short_term_modules:
             try:
                 pair_module = self.short_term_modules["Pairs Trading"]
                 pair_result = pair_module.run(tickers[:2], start_date, end_date)
                 pair_summary = pair_result.get("summary", {})
                 pair_summary['Ticker'] = f"{tickers[0]}/{tickers[1]}"
                 all_summaries.append(pair_summary)
             except Exception as e:
                 print(f"ERROR running strategy 'Pairs Trading' for tickers '{tickers[:2]}': {e}")
                 all_summaries.append({'Strategy': 'Pairs Trading', 'Ticker': f"{tickers[0]}/{tickers[1]}", 'Error': str(e)})
             
        return pd.DataFrame(all_summaries)


    def run_market_overview(self) -> Dict[str, Any]:
        """Provides a top-down view of the market using the MacroAgent."""
        print("Orchestrator: Running market overview...")
        return {
            "us_indicators": self.macro_agent.analyze_us_market(),
            "india_indicators": self.macro_agent.analyze_indian_market(),
            "global_indicators": self.macro_agent.get_global_indicators()
        }
        
    def get_ai_recommendation(self, user_profile: Dict[str, Any], provider: str = 'ollama', model: str = 'llama3') -> str:
        """Gathers market context and passes it to the LLMAgent for a personalized plan."""
        print(f"Orchestrator: Gathering context for AI recommendation via {provider}:{model}...")
        backtest_results = self.run_short_term_analysis(["SPY"], "2024-01-01", "2025-01-01")
        
        # Filter out any rows that have error information
        valid_backtests = backtest_results[backtest_results['Error'].isnull()].to_dict(orient='records')

        market_context = {
            "market_overview": self.run_market_overview(),
            "sample_short_term_backtests": valid_backtests
        }
        prompt = f"""
        You are "QuantVest AI," a certified financial advisor...
        CLIENT PROFILE: {user_profile}
        MARKET DATA: {market_context}
        TASK: Create a personalized investment plan...
        """
        return self.llm_agent.run(prompt)


    @classmethod
    def from_file(cls, path: str = "quant-company-insights-agent/config.yaml") -> "Orchestrator":
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cls(cfg)