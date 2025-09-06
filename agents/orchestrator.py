from __future__ import annotations
import yaml
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List
import importlib.util

# --- Agents ---
from agents.screener_agent import ScreenerAgent
from agents.llm_analyst_agent import LLMAnalystAgent as LLMAgent
from agents.execution_agent import ExecutionAgent
from agents.macro_agent import MacroAgent
from agents.insider_agent import InsiderAgent
from agents.social_media_sentiment import SentimentAgent
from agents.yfinance_agent import YFinanceAgent

# --- Utilities ---
from utils.news_fetcher import get_live_quote, get_company_news, calculate_headline_sentiment
from utils.moneycontrol_scraper import scrape_moneycontrol_data
from utils.data_loader import get_history, add_technical_indicators, get_company_snapshot, _get_indian_symbols_set
def _load_modules_from_path(path: Path, module_prefix: str):
    modules = {}
    for file_path in path.glob("*.py"):
        if file_path.stem == "__init__": continue
        module_name = f"{module_prefix}.{file_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            strategy_name = file_path.stem.replace('_', ' ').title()
            modules[strategy_name] = module
    return modules

class Orchestrator:
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config
        self.keys = self.cfg.get("api_keys", {})
        self.sets = self.cfg.get("agent_settings", {})
        self.rapidapi_cfg = self.cfg.get("rapidapi", {})
        self.moneycontrol_map = {
            "INFY": "https://www.moneycontrol.com/india/stockpricequote/computers-software/infosys/IT",
            "TCS": "https://www.moneycontrol.com/india/stockpricequote/computers-software/tataconsultancyservices/TCS",
            "RELIANCE": "https://www.moneycontrol.com/india/stockpricequote/refineries/relianceindustries/RI"
        }
        print("Orchestrator: Initializing all agents...")
        self._initialize_agents()
        self._register_strategies()
        print("Orchestrator: Initialization complete.")

    def _initialize_agents(self):
        self.yfinance_agent = YFinanceAgent()
        self.screener_agent = ScreenerAgent(rapidapi_config=self.rapidapi_cfg)
        self.llm_agent = LLMAgent(gemini_api_key=self.keys.get("gemini"))
        self.execution_agent = ExecutionAgent(api_key=self.keys.get("alpaca_key_id"), api_secret=self.keys.get("alpaca_secret_key"), paper=self.sets.get("paper_trading", True))
        self.macro_agent = MacroAgent(fred_api_key=self.keys.get("fred"))
        self.insider_agent = InsiderAgent(finnhub_key=self.keys.get("finnhub"), rapidapi_config=self.rapidapi_cfg)
        self.sentiment_agent = SentimentAgent(reddit_client_id=self.keys.get("reddit_client_id"), reddit_client_secret=self.keys.get("reddit_client_secret"), reddit_user_agent=self.keys.get("reddit_user_agent"))

    def _register_strategies(self):
        print("Orchestrator: Discovering and registering strategies...")
        long_term_path, short_term_path = Path("Long_Term_Strategy"), Path("strategies")
        self.long_term_modules = _load_modules_from_path(long_term_path, "Long_Term_Strategy")
        self.short_term_modules = _load_modules_from_path(short_term_path, "strategies")
        print(f"Registered {len(self.long_term_modules)} long-term strategies.")
        print(f"Registered {len(self.short_term_modules)} short-term strategies.")

    # In agents/orchestrator.py

    def run_deep_dive_analysis(self, ticker: str, start_date: str, end_date: str) -> Dict[str, Any]:
        """
        Runs a comprehensive multi-agent analysis. It now robustly detects
        Indian stocks using the master symbol list from the data_loader.
        """
        print(f"Orchestrator: Running unified deep-dive analysis for {ticker}...")
        
        # 1. Get the comprehensive base data from the YFinanceAgent. This works for ALL stocks.
        analysis_data = self.yfinance_agent.get_full_analysis(ticker)
        if "error" in analysis_data:
            return analysis_data

        # 2. Add social media and news sentiment (works for all stocks)
        analysis_data["social_sentiment"] = self.sentiment_agent.analyze(ticker)
        news = get_company_news(ticker, self.keys.get("finnhub"), start_date, end_date)
        headlines = [item.get("headline", "") for item in news]
        analysis_data["news_sentiment"] = {"avg_score": calculate_headline_sentiment(headlines), "headlines": headlines[:10]}
        
        # 3. Handle region-specific data (Live Price & Insider Trading)
        snapshot = analysis_data.get("snapshot", {})
        
        # --- THIS IS THE NEW, ROBUST LOGIC ---
        # We use the currency code from the yfinance snapshot to reliably detect the region.
        if snapshot.get("currency") == "INR":
            print(f"Orchestrator: Indian stock detected ({ticker}). Using yfinance data as primary source.")
            
            # For Indian stocks, the price from yfinance is reliable and sufficient.
            live_quote = {
                "c": snapshot.get("currentPrice") or snapshot.get("regularMarketPrice", 0),
                "pc": snapshot.get("previousClose", 0)
            }
            # Insider trading data is generally not available for this region via these APIs.
            insider_analysis = {
                "summary": {"Net Sentiment": "N/A for this region"},
                "transactions": pd.DataFrame()
            }
        else:
            print(f"Orchestrator: US stock detected ({ticker}). Fetching live API data for price.")
            
            # For US stocks, we can get a faster, more "live" price from the Finnhub API.
            live_quote = get_live_quote(ticker, self.keys.get("finnhub"))
            insider_analysis = self.insider_agent.analyze(ticker)
            
        # 4. Populate the final dictionary with the correct regional data
        analysis_data["live_quote"] = live_quote
        analysis_data["insider_analysis"] = insider_analysis
        analysis_data["stock_name"] = snapshot.get("longName", ticker)
        
        return analysis_data

    def run_market_overview(self) -> Dict[str, Any]:
        print("Orchestrator: Running market overview...")
        return {
            "us_indicators": self.macro_agent.analyze_us_market(),
            "india_indicators": self.macro_agent.analyze_indian_market(), # <-- CORRECTED
            "global_indicators": self.macro_agent.get_global_indicators()
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
        # (Your backtesting logic would go here)
        return pd.DataFrame(all_summaries)

    def get_ai_recommendation(self, user_profile: Dict[str, Any], provider: str = 'ollama', model: str = 'llama3') -> str:
        backtest_results = self.run_short_term_analysis(["SPY"], "2024-01-01", "2025-01-01")
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
    def from_file(cls, path: str = "config.yaml") -> "Orchestrator":
        """A factory method to create an Orchestrator instance from a YAML config file."""
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cls(cfg)

# from __future__ import annotations
# import yaml
# import pandas as pd
# import importlib.util
# import os
# from pathlib import Path
# from typing import Dict, Any, List

# # --- Import all REAL agents ---
# from agents.screener_agent import ScreenerAgent
# from agents.llm_analyst_agent import LLMAnalystAgent as LLMAgent
# from agents.execution_agent import ExecutionAgent
# from agents.macro_agent import MacroAgent
# from agents.insider_agent import InsiderAgent
# from agents.social_media_sentiment import SentimentAgent
# # --- Import ALL agents and utilities needed ---

# from agents.social_media_sentiment import SentimentAgent
# from utils.data_loader import get_company_snapshot, get_history, add_technical_indicators
# from utils.news_fetcher import get_live_quote, get_company_news, calculate_headline_sentiment
# from utils.moneycontrol_scraper import scrape_moneycontrol_data
# # --- Import all REAL utility modules ---
# from utils.data_loader import get_company_snapshot, get_history, add_technical_indicators
# from utils.news_fetcher import get_live_quote, get_company_news, calculate_headline_sentiment
# # --- Import the web scraper ---
# from utils.moneycontrol_scraper import scrape_moneycontrol_data


# def _load_modules_from_path(path: Path, module_prefix: str):
#     """Dynamically loads all python modules from a given directory path."""
#     modules = {}
#     for file_path in path.glob("*.py"):
#         if file_path.stem == "__init__":
#             continue
        
#         module_name = f"{module_prefix}.{file_path.stem}"
#         spec = importlib.util.spec_from_file_location(module_name, file_path)
#         if spec and spec.loader:
#             module = importlib.util.module_from_spec(spec)
#             spec.loader.exec_module(module)
#             strategy_name = file_path.stem.replace('_', ' ').title()
#             modules[strategy_name] = module
#     return modules

# class Orchestrator:
#     def __init__(self, config: Dict[str, Any]):
#         """
#         Initializes the entire ecosystem of agents based on the central config file.
#         """
#         self.cfg = config
#         self.keys = self.cfg.get("api_keys", {})
#         self.sets = self.cfg.get("agent_settings", {})
#         self.rapidapi_cfg = self.cfg.get("rapidapi", {})
        
#         self.moneycontrol_map = {
#             "INFY": "https://www.moneycontrol.com/india/stockpricequote/computers-software/infosys/IT",
#             "TCS": "https://www.moneycontrol.com/india/stockpricequote/computers-software/tataconsultancyservices/TCS",
#             "RELIANCE": "https://www.moneycontrol.com/india/stockpricequote/refineries/relianceindustries/RI"
#         }
        
#         print("Orchestrator: Initializing all agents...")
#         self._initialize_agents()
#         self._register_strategies()
#         print("Orchestrator: Initialization complete.")

#     def _initialize_agents(self):
#         """Creates instances of all agents the orchestrator can use."""
#         self.screener_agent = ScreenerAgent(rapidapi_config=self.rapidapi_cfg)
#         self.llm_agent = LLMAgent(gemini_api_key=self.keys.get("gemini"))
#         self.execution_agent = ExecutionAgent(
#             api_key=self.keys.get("alpaca_key_id"),
#             api_secret=self.keys.get("alpaca_secret_key"),
#             paper=self.sets.get("paper_trading", True)
#         )
#         self.macro_agent = MacroAgent(fred_api_key=self.keys.get("fred"))
#         self.insider_agent = InsiderAgent(
#             finnhub_key=self.keys.get("finnhub"),
#             rapidapi_config=self.rapidapi_cfg
#         )
#         self.sentiment_agent = SentimentAgent(
#             reddit_client_id=self.keys.get("reddit_client_id"),
#             reddit_client_secret=self.keys.get("reddit_client_secret"),
#             reddit_user_agent=self.keys.get("reddit_user_agent")
#         )

#     def _register_strategies(self):
#         """Dynamically discovers and registers all available strategy modules."""
#         print("Orchestrator: Discovering and registering strategies...")
#         long_term_path = Path("Long_Term_Strategy")
#         short_term_path = Path("strategies")
        
#         self.long_term_modules = _load_modules_from_path(long_term_path, "Long_Term_Strategy")
#         self.short_term_modules = _load_modules_from_path(short_term_path, "strategies")
        
#         print(f"Registered {len(self.long_term_modules)} long-term strategies.")
#         print(f"Registered {len(self.short_term_modules)} short-term strategies.")

#     # --- PRIMARY WORKFLOW METHODS CALLED BY THE FRONTEND ---

#     # In agents/orchestrator.py

#     def run_deep_dive_analysis(self, ticker: str, start_date: str, end_date: str) -> Dict[str, Any]:
#         """
#         Runs a comprehensive, multi-agent analysis on a single stock, with a special
#         combined data path for Indian stocks. This version is hardened against scraper failures.
#         """
#         print(f"Orchestrator: Running deep-dive analysis for {ticker}...")
        
#         # --- Universal Data Gathering ---
#         hist_df = get_history(ticker, start_date, end_date)
#         if hist_df.empty: return {"error": "Could not fetch historical data."}
        
#         enriched_df = add_technical_indicators(hist_df)
#         snapshot = get_company_snapshot(ticker)
#         social_sentiment = self.sentiment_agent.analyze(ticker)

#         # --- Conditional Data Gathering ---
#         clean_ticker = ticker.upper().replace(".NS", "")
        
#         if clean_ticker in self.moneycontrol_map:
#             # --- Path for Indian Stocks: Combine Scraper + APIs ---
#             print(f"Orchestrator: Indian stock detected. Using combined approach for {clean_ticker}...")
            
#             mc_url = self.moneycontrol_map[clean_ticker]
#             scraped_data = scrape_moneycontrol_data(mc_url)
            
#             # --- HARDENED PRICE HANDLING ---
#             # Step 1: Safely get the price string from the scraper's result.
#             price_str = scraped_data.get("nse_price") 
            
#             # Step 2: If the result is None (empty), default it to '0'.
#             if price_str is None:
#                 price_str = '0'
            
#             # Step 3: Now it's safe to call .replace() and convert to float.
#             cleaned_price_str = price_str.replace(',', '')
#             price_float = float(cleaned_price_str) if cleaned_price_str else 0.0
#             live_quote = {"c": price_float, "pc": 0} 
            
#             # Use APIs for news and sentiment
#             news = get_company_news(ticker, self.keys.get("finnhub"))
#             headlines = [item.get("headline", "") for item in news]
#             news_sentiment = {"avg_score": calculate_headline_sentiment(headlines), "headlines": headlines[:10]}
#             insider_analysis = {"summary": "Data not available for this region", "transactions": pd.DataFrame()}

#         else:
#             # --- Path for Other Stocks ---
#             print(f"Orchestrator: Using standard APIs for {ticker}...")
#             live_quote = get_live_quote(ticker, self.keys.get("finnhub"))
#             news = get_company_news(ticker, self.keys.get("finnhub"))
#             headlines = [item.get("headline", "") for item in news]
#             news_sentiment = {"avg_score": calculate_headline_sentiment(headlines), "headlines": headlines[:10]}
#             insider_analysis = self.insider_agent.analyze(ticker)
#             scraped_data = {}

#         return {
#             "snapshot": snapshot,
#             "live_quote": live_quote,
#             "news_sentiment": news_sentiment,
#             "social_sentiment": social_sentiment,
#             "insider_analysis": insider_analysis,
#             "technical_data": enriched_df.tail(1).to_dict(orient='records')[0] if not enriched_df.empty else {},
#             "scraped_data": scraped_data
#         }
#     def run_long_term_analysis(self, tickers: List[str]) -> Dict[str, Any]:
#         """Runs the suite of long-term fundamental analyses for the given tickers."""
#         print(f"Orchestrator: Running long-term analysis for {tickers}...")
#         results = {}
#         for ticker in tickers:
#             results[ticker] = {name: module.analyze(ticker) for name, module in self.long_term_modules.items()}
#         return results

#     def run_short_term_analysis(self, tickers: List[str], start_date: str, end_date: str) -> pd.DataFrame:
#         """Runs the suite of short-term backtests and returns a summary DataFrame."""
#         print(f"Orchestrator: Running short-term backtests for {tickers}...")
#         all_summaries = []
#         for ticker in tickers:
#             for name, module in self.short_term_modules.items():
#                 if name == "Pairs Trading": continue
#                 try:
#                     result_dict = module.run(ticker, start_date, end_date)
#                     summary = result_dict.get("summary", {})
#                     summary['Strategy'] = name
#                     summary['Ticker'] = ticker
#                     all_summaries.append(summary)
#                 except Exception as e:
#                     print(f"ERROR running strategy '{name}' for ticker '{ticker}': {e}")
#                     all_summaries.append({'Strategy': name, 'Ticker': ticker, 'Error': str(e)})

#         if len(tickers) >= 2 and "Pairs Trading" in self.short_term_modules:
#              try:
#                  pair_module = self.short_term_modules["Pairs Trading"]
#                  pair_result = pair_module.run(tickers[:2], start_date, end_date)
#                  pair_summary = pair_result.get("summary", {})
#                  pair_summary['Ticker'] = f"{tickers[0]}/{tickers[1]}"
#                  all_summaries.append(pair_summary)
#              except Exception as e:
#                  print(f"ERROR running strategy 'Pairs Trading' for tickers '{tickers[:2]}': {e}")
#                  all_summaries.append({'Strategy': 'Pairs Trading', 'Ticker': f"{tickers[0]}/{tickers[1]}", 'Error': str(e)})
             
#         return pd.DataFrame(all_summaries)

#     def run_market_overview(self) -> Dict[str, Any]:
#         """Provides a top-down view of the market using the MacroAgent."""
#         print("Orchestrator: Running market overview...")
#         return {
#             "us_indicators": self.macro_agent.analyze_us_market(),
#              "india_indicators": self.macro_agent.analyze_indian_market(),
#             "global_indicators": self.macro_agent.get_global_indicators()
#         }
        
#     def get_ai_recommendation(self, user_profile: Dict[str, Any], provider: str = 'ollama', model: str = 'llama3') -> str:
#         """Gathers market context and passes it to the LLMAgent for a personalized plan."""
#         print(f"Orchestrator: Gathering context for AI recommendation via {provider}:{model}...")
#         backtest_results = self.run_short_term_analysis(["SPY"], "2024-01-01", "2025-01-01")
        
#         valid_backtests = backtest_results[backtest_results['Error'].isnull()].to_dict(orient='records')

#         market_context = {
#             "market_overview": self.run_market_overview(),
#             "sample_short_term_backtests": valid_backtests
#         }
#         prompt = f"""
#         You are "QuantVest AI," a certified financial advisor...
#         CLIENT PROFILE: {user_profile}
#         MARKET DATA: {market_context}
#         TASK: Create a personalized investment plan...
#         """
#         return self.llm_agent.run(prompt)

#     @classmethod
#     def from_file(cls, path: str = "quant-company-insights-agent/config.yaml") -> "Orchestrator":
#         with open(path, "r", encoding="utf-8") as f:
#             cfg = yaml.safe_load(f)
#         return cls(cfg)


# from __future__ import annotations
# import yaml
# import pandas as pd
# import importlib.util
# import os
# from pathlib import Path
# from typing import Dict, Any, List

# # --- Import all REAL agents ---
# from agents.screener_agent import ScreenerAgent
# from agents.llm_analyst_agent import LLMAnalystAgent as LLMAgent
# from agents.execution_agent import ExecutionAgent
# from agents.macro_agent import MacroAgent
# from agents.insider_agent import InsiderAgent
# from agents.social_media_sentiment import SentimentAgent

# # --- Import all REAL utility modules ---
# from utils.data_loader import get_company_snapshot, get_history, add_technical_indicators
# from utils.news_fetcher import get_live_quote, get_company_news, calculate_headline_sentiment

# def _load_modules_from_path(path: Path, module_prefix: str):
#     """Dynamically loads all python modules from a given directory path."""
#     modules = {}
#     for file_path in path.glob("*.py"):
#         if file_path.stem == "__init__":
#             continue
        
#         module_name = f"{module_prefix}.{file_path.stem}"
#         spec = importlib.util.spec_from_file_location(module_name, file_path)
#         if spec and spec.loader:
#             module = importlib.util.module_from_spec(spec)
#             spec.loader.exec_module(module)
#             # Use a readable name for the strategy, e.g., "SMA Crossover" from "sma_crossover"
#             strategy_name = file_path.stem.replace('_', ' ').title()
#             modules[strategy_name] = module
#     return modules

# class Orchestrator:
#     def __init__(self, config: Dict[str, Any]):
#         """
#         Initializes the entire ecosystem of agents based on the central config file.
#         """
#         self.cfg = config
#         self.keys = self.cfg.get("api_keys", {})
#         self.sets = self.cfg.get("agent_settings", {})
#         self.rapidapi_cfg = self.cfg.get("rapidapi", {})
        
#         print("Orchestrator: Initializing all agents...")
#         self._initialize_agents()
#         self._register_strategies()
#         print("Orchestrator: Initialization complete.")

#     def _initialize_agents(self):
#         """Creates instances of all agents the orchestrator can use."""
#         self.screener_agent = ScreenerAgent(rapidapi_config=self.rapidapi_cfg)
#         self.llm_agent = LLMAgent(gemini_api_key=self.keys.get("gemini"))
#         self.execution_agent = ExecutionAgent(
#             api_key=self.keys.get("alpaca_key_id"),
#             api_secret=self.keys.get("alpaca_secret_key"),
#             paper=self.sets.get("paper_trading", True)
#         )
#         self.macro_agent = MacroAgent(fred_api_key=self.keys.get("fred"))
#         self.insider_agent = InsiderAgent(
#             finnhub_key=self.keys.get("finnhub"),
#             rapidapi_config=self.rapidapi_cfg
#         )
#         self.sentiment_agent = SentimentAgent(
#             reddit_client_id=self.keys.get("reddit_client_id"),
#             reddit_client_secret=self.keys.get("reddit_client_secret"),
#             reddit_user_agent=self.keys.get("reddit_user_agent")
#         )

#     def _register_strategies(self):
#         """Dynamically discovers and registers all available strategy modules."""
#         print("Orchestrator: Discovering and registering strategies...")
#         # Assuming the script is run from the root 'Boomerang' directory
#         long_term_path = Path("Long_Term_Strategy")
#         short_term_path = Path("strategies")
        
#         self.long_term_modules = _load_modules_from_path(long_term_path, "Long_Term_Strategy")
#         self.short_term_modules = _load_modules_from_path(short_term_path, "strategies")
        
#         print(f"Registered {len(self.long_term_modules)} long-term strategies.")
#         print(f"Registered {len(self.short_term_modules)} short-term strategies.")

#     # --- PRIMARY WORKFLOW METHODS CALLED BY THE FRONTEND ---

#     def run_deep_dive_analysis(self, ticker: str, start_date: str, end_date: str) -> Dict[str, Any]:
#         """Runs a comprehensive, multi-agent analysis on a single stock."""
#         print(f"Orchestrator: Running deep-dive analysis for {ticker}...")
#         hist_df = get_history(ticker, start_date, end_date)
#         if hist_df.empty: return {"error": "Could not fetch historical data."}
        
#         enriched_df = add_technical_indicators(hist_df)
        
#         snapshot = get_company_snapshot(ticker)
#         live_quote = get_live_quote(ticker, self.keys.get("finnhub"))
#         news = get_company_news(ticker, self.keys.get("finnhub"))
#         headlines = [item.get("headline", "") for item in news]
#         news_sentiment = calculate_headline_sentiment(headlines)
#         social_sentiment = self.sentiment_agent.analyze(ticker)
#         insider_analysis = self.insider_agent.analyze(ticker)

#         return {
#             "snapshot": snapshot,
#             "live_quote": live_quote,
#             "news_sentiment": {"avg_score": news_sentiment, "headlines": headlines[:10]},
#             "social_sentiment": social_sentiment,
#             "insider_analysis": insider_analysis,
#             "technical_data": enriched_df.tail(1).to_dict(orient='records')[0] if not enriched_df.empty else {}
#         }

#     def run_long_term_analysis(self, tickers: List[str]) -> Dict[str, Any]:
#         """Runs the suite of long-term fundamental analyses for the given tickers."""
#         print(f"Orchestrator: Running long-term analysis for {tickers}...")
#         results = {}
#         for ticker in tickers:
#             results[ticker] = {name: module.analyze(ticker) for name, module in self.long_term_modules.items()}
#         return results

#     def run_short_term_analysis(self, tickers: List[str], start_date: str, end_date: str) -> pd.DataFrame:
#         """Runs the suite of short-term backtests and returns a summary DataFrame."""
#         print(f"Orchestrator: Running short-term backtests for {tickers}...")
#         all_summaries = []
#         for ticker in tickers:
#             for name, module in self.short_term_modules.items():
#                 if name == "Pairs Trading": continue
#                 try:
#                     result_dict = module.run(ticker, start_date, end_date)
#                     summary = result_dict.get("summary", {})
#                     summary['Strategy'] = name
#                     summary['Ticker'] = ticker
#                     all_summaries.append(summary)
#                 except Exception as e:
#                     print(f"ERROR running strategy '{name}' for ticker '{ticker}': {e}")
#                     # Optionally, append a summary indicating the error
#                     all_summaries.append({'Strategy': name, 'Ticker': ticker, 'Error': str(e)})


#         if len(tickers) >= 2 and "Pairs Trading" in self.short_term_modules:
#              try:
#                  pair_module = self.short_term_modules["Pairs Trading"]
#                  pair_result = pair_module.run(tickers[:2], start_date, end_date)
#                  pair_summary = pair_result.get("summary", {})
#                  pair_summary['Ticker'] = f"{tickers[0]}/{tickers[1]}"
#                  all_summaries.append(pair_summary)
#              except Exception as e:
#                  print(f"ERROR running strategy 'Pairs Trading' for tickers '{tickers[:2]}': {e}")
#                  all_summaries.append({'Strategy': 'Pairs Trading', 'Ticker': f"{tickers[0]}/{tickers[1]}", 'Error': str(e)})
             
#         return pd.DataFrame(all_summaries)


#     def run_market_overview(self) -> Dict[str, Any]:
#         """Provides a top-down view of the market using the MacroAgent."""
#         print("Orchestrator: Running market overview...")
#         return {
#             "us_indicators": self.macro_agent.analyze_us_market(),
#             "india_indicators": self.macro_agent.analyze_indian_market(),
#             "global_indicators": self.macro_agent.get_global_indicators()
#         }
        
#     def get_ai_recommendation(self, user_profile: Dict[str, Any], provider: str = 'ollama', model: str = 'llama3') -> str:
#         """Gathers market context and passes it to the LLMAgent for a personalized plan."""
#         print(f"Orchestrator: Gathering context for AI recommendation via {provider}:{model}...")
#         backtest_results = self.run_short_term_analysis(["SPY"], "2024-01-01", "2025-01-01")
        
#         # Filter out any rows that have error information
#         valid_backtests = backtest_results[backtest_results['Error'].isnull()].to_dict(orient='records')

#         market_context = {
#             "market_overview": self.run_market_overview(),
#             "sample_short_term_backtests": valid_backtests
#         }
#         prompt = f"""
#         You are "QuantVest AI," a certified financial advisor...
#         CLIENT PROFILE: {user_profile}
#         MARKET DATA: {market_context}
#         TASK: Create a personalized investment plan...
#         """
#         return self.llm_agent.run(prompt)


#     @classmethod
#     def from_file(cls, path: str = "quant-company-insights-agent/config.yaml") -> "Orchestrator":
#         with open(path, "r", encoding="utf-8") as f:
#             cfg = yaml.safe_load(f)
#         return cls(cfg)