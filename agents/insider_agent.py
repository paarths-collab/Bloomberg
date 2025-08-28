# agents/insider_agent.py
import requests

class InsiderAgent:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://finnhub.io/api/v1/stock/insider-transactions"

    def _safe_request(self, url, params):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"Error": str(e)}

    def analyze(self, ticker: str) -> dict:
        params = {"symbol": ticker, "token": self.api_key}
        response = self._safe_request(self.base_url, params)

        if not isinstance(response, dict) or "data" not in response or not response["data"]:
            return {"Message": "No recent insider activity"}

        # Count insider buys and sells
        buys = sum(1 for tx in response["data"] if tx.get("transactionCode") == "P")  # Purchase
        sells = sum(1 for tx in response["data"] if tx.get("transactionCode") == "S")  # Sale

        # Interpret activity
        if buys > sells:
            net = "Bullish"
        elif sells > buys:
            net = "Bearish"
        else:
            net = "Neutral"

        return {
            "Insider Buys": buys,
            "Insider Sells": sells,
            "Net Activity": net,
        }
