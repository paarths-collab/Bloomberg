"""
api_server.py

This script provides a comprehensive FastAPI backend for the QuantInsights platform.
It exposes endpoints for:
- Running various analysis flows (AI-driven, long-term, short-term).
- Executing trades via the ExecutionAgent.
- Fetching account information and positions.

To run this API server:
1. Make sure all packages are installed: pip install -r requirements.txt
2. Run the server using uvicorn: uvicorn api_server:app --reload
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional

from agents.orchestrator import Orchestrator

# --- Pydantic Models for Request Data Validation ---

class AnalysisRequest(BaseModel):
    """Defines the structure for an incoming analysis request."""
    investor_type: str = Field(..., description="The type of analysis to run.", examples=['ai_driven', 'long-term', 'short-term'])
    tickers: Optional[List[str]] = Field(None, description="A list of stock tickers.", examples=[['AAPL', 'MSFT']])
    start_date: Optional[str] = Field(None, description="Start date for analysis (YYYY-MM-DD).", examples=['2023-01-01'])
    end_date: Optional[str] = Field(None, description="End date for analysis (YYYY-MM-DD).", examples=['2024-01-01'])

class TradeRequest(BaseModel):
    """Defines the structure for a trade execution request."""
    ticker: str
    qty: float
    side: str = Field(..., description="'buy' or 'sell'")

# --- Initialize FastAPI and the Orchestrator ---
app = FastAPI(
    title="QuantInsights API",
    description="A multi-agent API for stock discovery, analysis, and trading.",
    version="3.0.0"
)

# Load the single orchestrator instance at startup
# --- AFTER ---
orchestrator = Orchestrator.from_file("quant-company-insights-agent/config.yaml")

# --- CORS Middleware for Frontend Communication ---
origins = [
    "http://localhost:3000",  # React default
    "http://localhost:5173",
    "https://408887b3-dec5-461e-a296-edcd3683a912-00-1964om6pf5t2f.sisko.replit.dev/"
 # Vite default
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
  
)
# --- API Endpoints ---

@app.get("/")
def read_root():
    """A simple health check endpoint."""
    return {"message": "QuantInsights API is running 🚀"}

@app.post("/api/analyze")
def run_dynamic_analysis(request: AnalysisRequest):
    """
    Handles all analysis requests and routes them to the appropriate
    orchestrator flow based on 'investor_type'.
    """
    try:
        print(f"API: Received request for '{request.investor_type}' analysis...")
        results = orchestrator.execute_analysis_flow(
            investor_type=request.investor_type,
            tickers=request.tickers,
            start_date=request.start_date,
            end_date=request.end_date
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during analysis: {str(e)}")

@app.post("/api/trade/execute")
def execute_trade(request: TradeRequest):
    """Endpoint to execute a market order."""
    try:
        # Note: Assumes your ExecutionAgent has a 'submit_market_order' method.
        # This might need to be implemented or adjusted in the agent itself.
        order_result = orchestrator.execution_agent.submit_market_order(
            ticker=request.ticker,
            qty=request.qty,
            side=request.side
        )
        if "error" in order_result:
            raise HTTPException(status_code=400, detail=order_result["error"])
        return {"status": "success", "order_details": order_result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/account/info")
def get_account():
    """Endpoint to get Alpaca account information."""
    # Note: Assumes ExecutionAgent has 'get_account_info' method.
    info = orchestrator.execution_agent.get_account_info()
    if "error" in info:
        raise HTTPException(status_code=500, detail=info["error"])
    return info

@app.get("/api/account/positions")
def get_positions():
    """Endpoint to get all open positions."""
    # Note: Assumes ExecutionAgent has 'get_open_positions' method.
    positions = orchestrator.execution_agent.get_open_positions()
    if positions and "error" in positions[0]:
        raise HTTPException(status_code=500, detail=positions[0]["error"])
    return positions

# uvicorn api_server:app --reload



# from fastapi import FastAPI, HTTPException
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from typing import List

# from agents.orchestrator import Orchestrator

# # --- Pydantic model for validating incoming request data ---
# class AnalysisRequest(BaseModel):
#     tickers: List[str]
#     investor_type: str
#     start_date: str
#     end_date: str

# # --- Initialize FastAPI and the Orchestrator ---
# app = FastAPI(title="QuantInsights API")
# orchestrator = Orchestrator.from_file("quant-company-insights-agent/config.yaml")

# # --- Allow frontend to connect (CORS) ---
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["http://localhost:3000", "http://localhost:5173"], # Add your frontend's URL
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # --- Define the API Endpoint ---
# @app.post("/api/analyze")
# def run_dynamic_analysis(request: AnalysisRequest):
#     """
#     Receives user's choices from the frontend and triggers the
#     appropriate analysis flow in the Orchestrator.
#     """
#     try:
#         results = orchestrator.execute_analysis_flow(
#             tickers=request.tickers,
#             investor_type=request.investor_type,
#             start_date=request.start_date,
#             end_date=request.end_date
#         )
#         return results
#     except Exception as e:
#         # Return a server error if anything goes wrong
#         raise HTTPException(status_code=500, detail=str(e))

# @app.get("/")
# def read_root():
    # return {"message": "QuantInsights API is running."}

# To run this server: uvicorn api_server:app --reload
#--------------------------------------------------------------------------------------------------------------

# import argparse
# from fastapi import FastAPI, HTTPException
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from typing import List, Optional

# from agents.orchestrator import Orchestrator

# # --- Pydantic Models for Request Data Validation ---
# class AnalysisRequest(BaseModel):
#     tickers: Optional[List[str]] = None
#     start_date: str
#     end_date: str
#     investor_type: str

# # --- Initialize FastAPI and the Orchestrator ---
# app = FastAPI(
#     title="QuantInsights API",
#     description="A multi-agent API for comprehensive stock analysis and discovery.",
#     version="2.0.0"
# )
# orchestrator = Orchestrator.from_file("quant-company-insights-agent/config.yaml")

# # --- CORS Middleware to allow React Frontend to connect ---
# origins = [
#     "http://localhost:3000",  # Default for create-react-app
#     "http://localhost:5173",  # Default for Vite
#     # Add your frontend's production URL here when you deploy
# ]
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # --- Define the Core API Endpoint ---

# @app.post("/api/analyze")
# def run_dynamic_analysis(request: AnalysisRequest):
#     """
#     This single, powerful endpoint handles all analysis requests from the frontend.
#     - If tickers are provided, it runs a direct analysis.
#     - If tickers are NOT provided, it runs a discovery flow.
#     """
#     try:
#         if request.tickers:
#             # --- PATH A: Direct Analysis on specific tickers ---
#             print(f"API: Running direct deep-dive analysis on {request.tickers}...")
#             # Note: For multiple tickers, we'll loop and call run_once.
#             # A more advanced version might have a dedicated batch analysis method.
#             results = {}
#             for ticker in request.tickers:
#                 analysis = orchestrator.run_once(
#                     ticker=ticker,
#                     start_date=request.start_date,
#                     end_date=request.end_date
#                 )
#                 results[ticker] = analysis
#             return {"analysis_type": "direct", "data": results}

#         else:
#             # --- PATH B: Discovery Analysis to find and analyze a top stock ---
#             print(f"API: Running discovery analysis for {request.start_date} to {request.end_date}...")
#             analysis_result, ticker_analyzed = orchestrator.execute_discovery_flow(
#                 start_date=request.start_date,
#                 end_date=request.end_date
#             )
#             return {
#                 "analysis_type": "discovery",
#                 "discovered_ticker": ticker_analyzed,
#                 "data": analysis_result
#             }

#     except Exception as e:
#         # Raise an HTTPException which FastAPI will correctly format as a 500 error
#         raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")

# @app.get("/")
# def read_root():
#     return {"message": "QuantInsights API is running."}

# # To run this server:
# # uvicorn api_server:app --reload