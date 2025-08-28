
import os
from fredapi import Fred

class MacroAgent:
    def __init__(self, api_key: str = None):
        # ✅ Fallback to env var if config key missing
        self.api_key = api_key or os.getenv("FRED_API_KEY")
        if not self.api_key:
            raise ValueError(
                "❌ No FRED API key found. "
                "Set it in config.yaml under api_keys.fred, "
                "or export FRED_API_KEY as an environment variable."
            )
        self.fred = Fred(api_key=self.api_key)

    def analyze(self):
        """Fetch a few macroeconomic indicators."""
        try:
            gdp = self.fred.get_series_latest_release("GDP").iloc[-1]
            inflation = self.fred.get_series_latest_release("CPIAUCSL").iloc[-1]
            unemployment = self.fred.get_series_latest_release("UNRATE").iloc[-1]

            return {
                "GDP (latest)": round(float(gdp), 2),
                "CPI (latest)": round(float(inflation), 2),
                "Unemployment Rate": round(float(unemployment), 2),
            }
        except Exception as e:
            return {"error": f"Macro data fetch failed: {e}"}



# agents/macro_agent.py
# import datetime
# from fredapi import Fred


# class MacroAgent:
#     def __init__(self, api_key: str):
#         self.fred = Fred(api_key=api_key)

#     def analyze(self, ticker: str = None) -> dict:
#         """
#         Analyze macroeconomic indicators that affect markets.
#         Ticker is optional since these are global indicators.
#         """
#         today = datetime.date.today()
#         last_month = today - datetime.timedelta(days=30)

#         try:
#             # Fed Funds Rate (interest rate)
#             interest_rate = self.fred.get_series_latest_release("FEDFUNDS")

#             # Inflation (CPI last 30 days % change)
#             inflation = (
#                 self.fred.get_series("CPIAUCSL", last_month, today)
#                 .pct_change()
#                 .iloc[-1] * 100
#             )

#             # Market Volatility (VIX)
#             vix = self.fred.get_series("VIXCLS", last_month, today).iloc[-1]

#         except Exception as e:
#             return {"Error": str(e)}

#         # Interpret indicators
#         rate_impact = "High (Negative)" if interest_rate > 4 else "Moderate"
#         inflation_trend = "Cooling" if inflation < 3 else "Rising"
#         sentiment = "Neutral → Positive" if vix < 20 else "Cautious"

#         return {
#             "Interest Rate Impact": rate_impact,
#             "Inflation Trend": inflation_trend,
#             "Market Sentiment": sentiment,
#         }


# # Example usage
# if __name__ == "__main__":
#     # Example key (replace with real)
#     agent = MacroAgent(api_key="YOUR_FRED_KEY")
#     print(agent.analyze("AAPL"))
