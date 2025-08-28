# agents/analyst_agent.py
import requests

class AnalystAgent:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.quote_url = "https://finnhub.io/api/v1/quote"
        self.metrics_url = "https://finnhub.io/api/v1/stock/metric"

    def _safe_request(self, url, params):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"Error": str(e)}

    def analyze(self, ticker: str) -> dict:
        # Stock quote
        quote = self._safe_request(self.quote_url, {"symbol": ticker, "token": self.api_key})
        # Financial metrics
        metrics = self._safe_request(self.metrics_url, {"symbol": ticker, "metric": "all", "token": self.api_key})

        if not isinstance(metrics, dict) or "metric" not in metrics:
            return {"Message": "No financial data available"}

        pe_ratio = metrics["metric"].get("peNormalizedAnnual")
        eps = metrics["metric"].get("epsNormalizedAnnual")
        revenue_growth = metrics["metric"].get("revenueGrowth3Y")

        if pe_ratio and pe_ratio > 20:
            valuation = "Slightly Overvalued"
        elif pe_ratio:
            valuation = "Fairly Valued"
        else:
            valuation = "Unknown"

        return {
            "Current Price": quote.get("c", "N/A") if isinstance(quote, dict) else "N/A",
            "Revenue Growth (3Y)": f"{revenue_growth*100:.2f}%" if revenue_growth else "N/A",
            "PE Ratio": pe_ratio or "N/A",
            "EPS": eps or "N/A",
            "Valuation": valuation,
        }
