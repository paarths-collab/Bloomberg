#agents/   AI & orchestration layer
 # handles multi-agent flow
# agents/orchestrator.py
from __future__ import annotations
import yaml
from typing import Dict, Any, List

from utils.data_loader import get_company_snapshot, get_history, add_indicators
from utils.news_fetcher import get_live_quote, get_company_news, sentiment_on_headlines
from utils.validation import sma_crossover_signal, rsi_filter, atr_stop_levels

class Orchestrator:
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config
        self.keys = self.cfg.get("api_keys", {})
        self.sets = self.cfg.get("settings", {})

    def run_once(self, ticker: str) -> Dict[str, Any]:
        """One-shot analysis pipeline for a ticker."""
        # 1) Fundamentals
        fundamentals = get_company_snapshot(ticker)

        # 2) History + Indicators
        hist = get_history(
            ticker,
            period=self.sets.get("history_period", "1y"),
            interval=self.sets.get("history_interval", "1d"),
        )
        hist = add_indicators(hist)

        # 3) Live quote + news
        fn_key = self.keys.get("finnhub")
        use_nse = ticker.endswith(".NS")  # heuristic: NSE tickers
        quote = get_live_quote(ticker, fn_key, use_nse=use_nse)
        news = get_company_news(ticker, fn_key, days_back=7, use_nse=use_nse)
        headlines = [n.get("headline") for n in news if n.get("headline")]
        avg_sent, scored = sentiment_on_headlines(headlines[:30])  # cap to 30 headlines

        # 4) Signals + Risk
        signal = sma_crossover_signal(hist)
        rsi_state = rsi_filter(hist)
        stop, take = atr_stop_levels(hist, atr_mult=2.0)

        # 5) Pack result
        result = {
            "ticker": ticker,
            "fundamentals": fundamentals,
            "last_close": float(hist["Close"].iloc[-1]),
            "live_quote": quote,  # dict with c/h/l/o/pc/t
            "signal": signal,
            "rsi_state": rsi_state,
            "stop_loss": stop,
            "take_profit": take,
            "sentiment_avg": round(avg_sent, 3),
            "news_samples": headlines[:10],
        }
        return result

    def pretty_print(self, result: Dict[str, Any]) -> None:
        f = result["fundamentals"]
        print("\n=== QuantInsight Snapshot ===")
        print(f"Ticker: {result['ticker']} | Name: {f.get('longName')} | Sector: {f.get('sector')} / {f.get('industry')}")
        print(f"PE (trail/forward): {f.get('trailingPE')} / {f.get('forwardPE')}")
        print(f"ROE: {f.get('returnOnEquity')}  | Profit Margins: {f.get('profitMargins')}")
        print(f"Last Close: {result['last_close']} | Live Price: {result['live_quote'].get('c')}")
        print(f"Signal: {result['signal']} | RSI: {result['rsi_state']}")
        print(f"ATR-based Stop: {result['stop_loss']} | Take-Profit: {result['take_profit']}")
        print(f"Avg Headline Sentiment (VADER compound): {result['sentiment_avg']}")
        print("Recent headlines:")
        for h in result["news_samples"]:
            print(" -", h)

    @classmethod
    def from_file(cls, path: str = "config.yaml") -> "Orchestrator":
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cls(cfg)
