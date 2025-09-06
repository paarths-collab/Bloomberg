# File: agents/yfinance_agent.py

import yfinance as yf
import pandas as pd
import logging
from typing import Dict, Any
from functools import lru_cache

from utils.data_loader import _format_ticker_for_yf, add_technical_indicators

logger = logging.getLogger(__name__)

class YFinanceAgent:
    @lru_cache(maxsize=128)
    def get_full_analysis(self, ticker: str) -> Dict[str, Any]:
        yf_ticker_str = _format_ticker_for_yf(ticker)
        logger.info(f"YFinanceAgent: Starting full analysis for {yf_ticker_str}...")
        
        try:
            stock = yf.Ticker(yf_ticker_str)
            info = stock.info
            if not info or len(info) < 10:
                 return {"error": f"Invalid ticker or no data found for {ticker}"}
        except Exception as e:
            return {"error": str(e)}

        # --- Fetch all data points ---
        try: financials = stock.financials
        except Exception: financials = pd.DataFrame()
        try: balance_sheet = stock.balance_sheet
        except Exception: balance_sheet = pd.DataFrame()
        try: cashflow = stock.cashflow
        except Exception: cashflow = pd.DataFrame()
        try: major_holders = stock.major_holders
        except Exception: major_holders = pd.DataFrame()
        try: institutional_holders = stock.institutional_holders
        except Exception: institutional_holders = pd.DataFrame()
        try: dividends = stock.dividends.reset_index().sort_values(by='Date', ascending=False)
        except Exception: dividends = pd.DataFrame()
        try: splits = stock.splits
        except Exception: splits = pd.DataFrame()
        
        # --- FINAL, ROBUST RECOMMENDATIONS LOGIC ---
        try:
            recommendations = stock.recommendations
            if recommendations is not None and not recommendations.empty:
                rec_df = recommendations.reset_index()
                date_col_name = rec_df.columns[0]
                
                # Check if the date column is numeric (a Unix timestamp)
                if pd.api.types.is_numeric_dtype(rec_df[date_col_name]):
                    # If it's a number, convert from seconds
                    rec_df['Date'] = pd.to_datetime(rec_df[date_col_name], unit='s', errors='coerce')
                else:
                    # If it's not a number, it's likely a standard date string
                    rec_df['Date'] = pd.to_datetime(rec_df[date_col_name], errors='coerce')
                
                rec_df.dropna(subset=['Date'], inplace=True)
                recommendations = rec_df.sort_values(by='Date', ascending=False)
            else:
                recommendations = pd.DataFrame()
        except Exception:
            recommendations = pd.DataFrame()

        try:
            hist_df = stock.history(period="5y")
            enriched_hist = add_technical_indicators(hist_df)
        except Exception:
            enriched_hist = pd.DataFrame()

        return {
            "snapshot": info,
            "historical_data": enriched_hist,
            "financials": {"income_statement": financials, "balance_sheet": balance_sheet, "cash_flow": cashflow},
            "ownership": {"major_holders": major_holders, "institutional_holders": institutional_holders},
            "corporate_actions": {"dividends": dividends, "splits": splits},
            "analyst_recommendations": recommendations
        }

# # File: agents/yfinance_agent.py

# import yfinance as yf
# import pandas as pd
# import logging
# from typing import Dict, Any
# from functools import lru_cache
# from utils.data_loader import _format_ticker_for_yf, add_technical_indicators

# logger = logging.getLogger(__name__)

# class YFinanceAgent:
#     """
#     An agent dedicated to fetching a comprehensive set of data for a single
#     ticker from the yfinance library.
#     """

#     @lru_cache(maxsize=128)
#     def get_full_analysis(self, ticker: str) -> Dict[str, Any]:
#         yf_ticker_str = _format_ticker_for_yf(ticker)
#         logger.info(f"YFinanceAgent: Starting full analysis for {yf_ticker_str}...")

#         # Initialize Ticker
#         try:
#             stock = yf.Ticker(yf_ticker_str)
#             info = stock.info
#             if not info or len(info) < 10:
#                 return {"error": f"Invalid ticker or no data found for {ticker}"}
#         except Exception as e:
#             logger.error(f"Failed to create Ticker object for {ticker}. Error: {e}")
#             return {"error": str(e)}

#         # --- Fetch financials ---
#         try: financials = stock.financials
#         except Exception: financials = pd.DataFrame()
#         try: balance_sheet = stock.balance_sheet
#         except Exception: balance_sheet = pd.DataFrame()
#         try: cashflow = stock.cashflow
#         except Exception: cashflow = pd.DataFrame()

#         # --- Shareholders ---
#         try: major_holders = stock.major_holders
#         except Exception: major_holders = pd.DataFrame()
#         try: institutional_holders = stock.institutional_holders
#         except Exception: institutional_holders = pd.DataFrame()

#         # --- Corporate Actions ---
#         try: dividends = stock.dividends.reset_index().sort_values(by='Date', ascending=False)
#         except Exception: dividends = pd.DataFrame()
#         try: splits = stock.splits
#         except Exception: splits = pd.DataFrame()

#         # --- Analyst Recommendations ---
#         try:
#             recommendations = stock.recommendations
#             if recommendations is not None and not recommendations.empty:
#                 # Reset index if 'Date' is in index
#                 if recommendations.index.name in [None, 'Date']:
#                     recommendations = recommendations.reset_index()

#                 # Determine the date column
#                 date_col = 'Date' if 'Date' in recommendations.columns else recommendations.columns[0]

#                 # Convert to datetime safely
#                 recommendations['Date'] = pd.to_datetime(
#                     recommendations[date_col], errors='coerce'
#                 )

#                 # Drop rows with invalid dates
#                 recommendations = recommendations.dropna(subset=['Date'])

#                 # Sort descending
#                 recommendations = recommendations.sort_values(by='Date', ascending=False)

#         except Exception:
#             recommendations = pd.DataFrame()

#         # --- Historical Data with Technical Indicators ---
#         try:
#             hist_df = stock.history(period="5y")
#             enriched_hist = add_technical_indicators(hist_df)
#         except Exception:
#             enriched_hist = pd.DataFrame()

#         return {
#             "snapshot": info,
#             "historical_data": enriched_hist,
#             "financials": {
#                 "income_statement": financials,
#                 "balance_sheet": balance_sheet,
#                 "cash_flow": cashflow
#             },
#             "ownership": {
#                 "major_holders": major_holders,
#                 "institutional_holders": institutional_holders
#             },
#             "corporate_actions": {
#                 "dividends": dividends,
#                 "splits": splits
#             },
#             "analyst_recommendations": recommendations
#         }

# import yfinance as yf
# import pandas as pd
# import logging
# from typing import Dict, Any
# from functools import lru_cache

# # --- Utilities ---
# # We need to import the ticker formatting function from the data_loader
# from utils.data_loader import _format_ticker_for_yf, add_technical_indicators

# logger = logging.getLogger(__name__)

# class YFinanceAgent:
#     """
#     An agent dedicated to fetching a comprehensive set of data for a single
#     ticker from the yfinance library.
#     """
#     @lru_cache(maxsize=128)
#     def get_full_analysis(self, ticker: str) -> Dict[str, Any]:
#         """
#         Fetches all available yfinance data points for a given stock ticker.
#         Handles errors gracefully for each data point.
#         """
#         yf_ticker_str = _format_ticker_for_yf(ticker)
#         logger.info(f"YFinanceAgent: Starting full analysis for {yf_ticker_str}...")
        
#         try:
#             stock = yf.Ticker(yf_ticker_str)
#             info = stock.info
#             # If info is empty or short, the ticker is likely invalid
#             if not info or len(info) < 10:
#                  return {"error": f"Invalid ticker or no data found for {ticker}"}
#         except Exception as e:
#             logger.error(f"YFinanceAgent: Failed to create Ticker object for {ticker}. Error: {e}")
#             return {"error": str(e)}

#         # --- Fetch all data points with individual error handling ---
        
#         # Financials
#         try: financials = stock.financials
#         except Exception: financials = pd.DataFrame()
#         try: balance_sheet = stock.balance_sheet
#         except Exception: balance_sheet = pd.DataFrame()
#         try: cashflow = stock.cashflow
#         except Exception: cashflow = pd.DataFrame()

#         # Shareholders
#         try: major_holders = stock.major_holders
#         except Exception: major_holders = pd.DataFrame()
#         try: institutional_holders = stock.institutional_holders
#         except Exception: institutional_holders = pd.DataFrame()

#         # Corporate Actions
#         try: dividends = stock.dividends.reset_index().sort_values(by='Date', ascending=False)
#         except Exception: dividends = pd.DataFrame()
#         try: splits = stock.splits
#         except Exception: splits = pd.DataFrame()
        
#         # Recommendations
#         try: recommendations = stock.recommendations
#         except Exception: recommendations = pd.DataFrame()

#         # Historical Data with Technical Indicators
#         try:
#             hist_df = stock.history(period="5y") # Fetch 5 years for robust TA
#             enriched_hist = add_technical_indicators(hist_df)
#         except Exception:
#             enriched_hist = pd.DataFrame()

#         # --- Package and return all data ---
#         return {
#             "snapshot": info,
#             "historical_data": enriched_hist,
#             "financials": {
#                 "income_statement": financials,
#                 "balance_sheet": balance_sheet,
#                 "cash_flow": cashflow
#             },
#             "ownership": {
#                 "major_holders": major_holders,
#                 "institutional_holders": institutional_holders
#             },
#             "corporate_actions": {
#                 "dividends": dividends,
#                 "splits": splits
#             },
#             "analyst_recommendations": recommendations
#         }