from __future__ import annotations
import yaml
from typing import Dict, Any, List
import pandas as pd # Import pandas for DataFrame creation

#from streamlit.caching import st_cache_data # <-- STEP 1: ADD THIS IMPORT
# MUST be the very first line of code

# Now, all other imports can follow


from utils.data_loader import get_company_snapshot, get_history, add_indicators
from utils.news_fetcher import get_live_quote, get_company_news, sentiment_on_headlines
from utils.validation import sma_crossover_signal, rsi_filter, atr_stop_levels
from utils.news_fetcher import get_live_quote, get_company_news, sentiment_on_headlines, get_insider_transactions # Add the new import

class Orchestrator:
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config
        self.keys = self.cfg.get("api_keys", {})
        self.sets = self.cfg.get("settings", {})

    def run_once(self, ticker: str) -> Dict[str, Any] | None:
        """One-shot analysis pipeline for a ticker. Returns None on failure."""
        # 1) Fundamentals
        fundamentals = get_company_snapshot(ticker)
        if "error" in fundamentals:
            print(f"Could not retrieve fundamentals for {ticker}. Aborting.")
            return None

        # 2) History + Indicators (Used ONLY for TA calculations)
        hist = get_history(
            ticker,
            period=self.sets.get("history_period", "1y"),
            interval=self.sets.get("history_interval", "1d"),
        )
        if hist is None:
            print(f"Could not retrieve historical data for {ticker}. Aborting analysis.")
            return None
        hist = add_indicators(hist)

        # 3) Live quote + news (This is our SINGLE SOURCE OF TRUTH for prices)
        fn_key = self.keys.get("finnhub")
        use_nse = ticker.endswith(".NS")
        quote = get_live_quote(ticker, fn_key, use_nse=use_nse)
        news = get_company_news(ticker, fn_key, days_back=7, use_nse=use_nse)
        headlines = [n.get("headline") for n in news if n.get("headline")]
        avg_sent, _ = sentiment_on_headlines(headlines[:30])

        # 4) Signals + Risk (Calculated from yfinance history)
        signal = sma_crossover_signal(hist)
        rsi_state = rsi_filter(hist)
        stop, take = atr_stop_levels(hist, atr_mult=2.0)

        # 5) Pack result (Note: 'last_close' from yfinance is now removed)
        result = {
            "ticker": ticker,
            "fundamentals": fundamentals,
            "live_quote": quote, # Pass the entire Finnhub quote object
            "signal": signal,
            "rsi_state": rsi_state,
            "stop_loss": stop,
            "take_profit": take,
            "sentiment_avg": round(avg_sent, 3),
            "news_samples": headlines[:10],
        }
        return result


   # In agents/orchestrator.py

    def build_dashboard(self, ticker: str) -> Dict[str, Any]:
        """
        Runs the analysis and structures the data for the Streamlit dashboard.
        """
        # Step 1: Get all the raw data from our existing method
        data = self.run_once(ticker)

        # Step 2: If data fetching failed, return an empty structure
        if not data:
            return {
                "Fundamental Analysis": pd.DataFrame(),
                "Insider Activity": pd.DataFrame(),
                "Macro Outlook": pd.DataFrame(),
                "Social Sentiment": pd.DataFrame(),
                "Technical Signals": {},
            }

        # Step 3: Reshape the fundamentals and technicals
        
        f = data["fundamentals"]
        
        # --- Step 1: Get all the raw values ---
        raw_values = [
            f.get('longName'), f.get('sector'), f.get('industry'),
            f.get('marketCap'), f.get('trailingPE'), f.get('forwardPE'),
            f.get('returnOnEquity'), f.get('profitMargins')
        ]
        
        # --- Step 2: Convert every value to a string, handling None and formatting ---
        string_values = []
        for v in raw_values:
            if v is None:
                string_values.append("N/A")
            elif isinstance(v, int):
                string_values.append(f"{v:,}") # Add commas to large numbers
            elif isinstance(v, float):
                string_values.append(f"{v:.2f}") # Format floats to 2 decimal places
            else:
                string_values.append(str(v))

        # --- Step 3: Now create the DataFrame with the all-string list ---
        fundamentals_df = pd.DataFrame.from_dict({
            "Metric": ["Company Name", "Sector", "Industry", "Market Cap", "Trailing P/E", "Forward P/E", "ROE", "Profit Margins"],
            "Value": string_values # Use the clean, all-string list here
        }).set_index("Metric")
        
        # --- THIS IS THE CORRECTED AND VERIFIED BLOCK ---
        # In build_dashboard method
        quote_data = data.get('live_quote', {})
        technicals = {
            "Previous Close": f"${quote_data.get('pc', 0):.2f}",
            "Current Price": f"${quote_data.get('c', 0):.2f}",
    # ... other keys}
            "SMA Signal": data["signal"],
            "RSI State": data["rsi_state"],
            "ATR Stop-Loss": data["stop_loss"],
            "ATR Take-Profit": data["take_profit"],
            "Headline Sentiment": data["sentiment_avg"],
            "Recent Headlines": data["news_samples"]
        }

        # --- (the rest of the function continues) ---
        insider_df = get_insider_transactions(ticker, self.keys.get("finnhub"))
        
        dashboard_data = {
            "Fundamental Analysis": fundamentals_df,
            "Technical Signals": technicals,
            "Insider Activity": insider_df,
            # ...
        }
        return dashboard_data
    def pretty_print(self, result: Dict[str, Any]) -> None:
        # This function remains unchanged and works with the output of run_once
        if not result:
            print("No data to print.")
            return
        f = result["fundamentals"]
        print("\n=== QuantInsight Snapshot ===")
        # ... (the rest of this function is unchanged)

    @classmethod
    def from_file(cls, path: str = "config.yaml") -> "Orchestrator":
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cls(cfg)

# In agents/orchestrator.py

    
# from __future__ import annotations
# import yaml
# from typing import Dict, Any, List

# from utils.data_loader import get_company_snapshot, get_history, add_indicators
# from utils.news_fetcher import get_live_quote, get_company_news, sentiment_on_headlines
# from utils.validation import sma_crossover_signal, rsi_filter, atr_stop_levels

# class Orchestrator:
#     def __init__(self, config: Dict[str, Any]):
#         self.cfg = config
#         self.keys = self.cfg.get("api_keys", {})
#         self.sets = self.cfg.get("settings", {})

#     def run_once(self, ticker: str) -> Dict[str, Any]:
#         """One-shot analysis pipeline for a ticker."""
#         # 1) Fundamentals
#         fundamentals = get_company_snapshot(ticker)

#         # 2) History + Indicators
#         hist = get_history(
#             ticker,
#             period=self.sets.get("history_period", "1y"),
#             interval=self.sets.get("history_interval", "1d"),
#         )
#         hist = add_indicators(hist)

#         # 3) Live quote + news
#         fn_key = self.keys.get("finnhub")
#         use_nse = ticker.endswith(".NS")  # heuristic: NSE tickers
#         quote = get_live_quote(ticker, fn_key, use_nse=use_nse)
#         news = get_company_news(ticker, fn_key, days_back=7, use_nse=use_nse)
#         headlines = [n.get("headline") for n in news if n.get("headline")]
#         avg_sent, scored = sentiment_on_headlines(headlines[:30])  # cap to 30 headlines

#         # 4) Signals + Risk
#         signal = sma_crossover_signal(hist)
#         rsi_state = rsi_filter(hist)
#         stop, take = atr_stop_levels(hist, atr_mult=2.0)

#         # 5) Pack result
#         result = {
#             "ticker": ticker,
#             "fundamentals": fundamentals,
#             "last_close": float(hist["Close"].iloc[-1]),
#             "live_quote": quote,  # dict with c/h/l/o/pc/t
#             "signal": signal,
#             "rsi_state": rsi_state,
#             "stop_loss": stop,
#             "take_profit": take,
#             "sentiment_avg": round(avg_sent, 3),
#             "news_samples": headlines[:10],
#         }
#         return result

#     def pretty_print(self, result: Dict[str, Any]) -> None:
#         f = result["fundamentals"]
#         print("\n=== QuantInsight Snapshot ===")
#         print(f"Ticker: {result['ticker']} | Name: {f.get('longName')} | Sector: {f.get('sector')} / {f.get('industry')}")
#         print(f"PE (trail/forward): {f.get('trailingPE')} / {f.get('forwardPE')}")
#         print(f"ROE: {f.get('returnOnEquity')}  | Profit Margins: {f.get('profitMargins')}")
#         print(f"Last Close: {result['last_close']} | Live Price: {result['live_quote'].get('c')}")
#         print(f"Signal: {result['signal']} | RSI: {result['rsi_state']}")
#         print(f"ATR-based Stop: {result['stop_loss']} | Take-Profit: {result['take_profit']}")
#         print(f"Avg Headline Sentiment (VADER compound): {result['sentiment_avg']}")
#         print("Recent headlines:")
#         for h in result["news_samples"]:
#             print(" -", h)

#     @classmethod
#     def from_file(cls, path: str = "config.yaml") -> "Orchestrator":
#         with open(path, "r", encoding="utf-8") as f:
#             cfg = yaml.safe_load(f)
#         return cls(cfg)
