# File: agents/wealth_orchestrator.py
"""
Autonomous Wealth Management System - FastAPI Compatible
=========================================================
Multi-agent orchestration using LangGraph with async support
"""

import asyncio
from typing import TypedDict, Annotated, List, Dict, Any, Optional
from datetime import datetime
import json
import logging
import os
import pandas as pd

# LangGraph imports
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, SystemMessage

# Async Reddit (fix the PRAW warning)
import asyncpraw

# Your existing agents and utils
# We assume adapter pattern or direct usage where possible
from agents.sector_agent import SectorDiscoveryAgent as LegacySectorAgent
from agents.stock_picker_agent import StockPickerAgent
from agents.sentiment_agent import SentimentAgent
from agents.macro_agent import MacroAgent
from utils.news_fetcher import NewsFetcher
from utils.portfolio_engine import PortfolioEngine 
from utils.llm_manager import LLMManager
from utils.guardrails import WealthGuardrails
from utils.data_loader import get_data

# Setup Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# STATE DEFINITION
# ============================================================================

class WealthState(TypedDict):
    """Shared state across all agents in the workflow"""
    
    # Input
    raw_input: str
    market: str
    
    # User Profile
    user_profile: Dict[str, Any]
    allocation_strategy: Dict[str, float]
    investable_amount: float
    
    # Market Context
    current_season: str
    
    # Sector Analysis
    sector_rankings: List[Dict[str, Any]]
    selected_sector: str
    sector_news: List[Dict[str, str]]
    
    # Stock Selection
    candidate_stocks: List[Dict[str, Any]]
    stock_backtests: Dict[str, Any]
    selected_stock: Dict[str, Any]
    stock_research: Dict[str, Any]
    
    # MF & Bond Selection
    selected_mf: Dict[str, Any]
    selected_bonds: Dict[str, Any]
    macro_indicators: Dict[str, Any]
    
    # Output
    investment_report: str
    execution_log: List[str]
    errors: List[str]
    is_blocked: bool


# ============================================================================
# ASYNC-COMPATIBLE AGENT NODES
# ============================================================================

class GuardrailAgent:
    """Stage 0: Validate Input"""
    
    def __init__(self, guardrails: WealthGuardrails):
        self.guardrails = guardrails
        
    async def __call__(self, state: WealthState) -> WealthState:
        logger.info("🛡️ Checking Guardrails...")
        
        validation = await self.guardrails.validate_input(state['raw_input'])
        
        if not validation['valid']:
            logger.warning(f"⛔ Input blocked: {validation['reason']}")
            return {
                **state,
                "is_blocked": True,
                "investment_report": f"### ⛔ Request Blocked\n\n{validation['reason']}",
                "execution_log": ["⛔ Guardrail blocked request: Non-financial topic detected."],
                "errors": [validation['reason']]
            }
            
        return {
            **state, 
            "is_blocked": False,
            "execution_log": ["✓ Guardrails passed"]
        }

class InputStructurerAgent:
    """Stage 1: Parse and structure user input using Gemini"""
    
    def __init__(self, llm_manager: LLMManager):
        self.llm = llm_manager
    
    async def __call__(self, state: WealthState) -> WealthState:
        """Structure natural language input into financial profile"""
        
        if state.get('is_blocked'): return state

        system_prompt = """You are a financial profile analyzer. Extract structured data from user input.

Parse the following information:

1. **Financial Snapshot**:
   - Monthly income (amount and type: recurring/non-recurring)
   - Current savings/investments
   - Active loans (home loan, car loan, personal loan with EMI and tenure)
   - Monthly expenses
   - Calculate: Investable Surplus = Income - Expenses - Loan EMIs

2. **Investment Strategy**:
   - Time horizon: short-term (<3 years), medium-term (3-7 years), long-term (>7 years)
   - Risk tolerance: conservative, moderate, aggressive
   - Financial goals: retirement, education, home, wealth creation, etc.

3. **Asset Allocation**:
   Based on risk profile and time horizon, recommend:
   - Stocks: X%
   - Mutual Funds: Y%
   - Bonds/Fixed Income: Z%
   
Rules:
- Conservative + Short-term -> High bonds (60-70%), Low stocks (10-20%)
- Moderate + Medium-term -> Balanced (40-50% stocks, 30-40% MF, 20-30% bonds)
- Aggressive + Long-term -> High equity (60-70% stocks, 20-30% MF, 10% bonds)

4. **Market Context**:
   - Market (e.g., 'US', 'IN' for India, 'UK', 'EU') inferred from currency symbols ($, ₹, £, €) or explicit mention. Default to 'US' if ambiguous.

Return ONLY valid JSON:
{
  "market": "US|IN|UK|EU",
  "financial_snapshot": {
    "monthly_income": <number>,
    "income_type": "recurring|non_recurring|mixed",
    "savings": <number>,
    "loans": [{"type": "str", "emi": <number>, "tenure_months": <int>}],
    "monthly_expenses": <number>,
    "investable_surplus": <number>
  },
  "preferences": {
    "horizon": "short|medium|long",
    "risk_tolerance": "conservative|moderate|aggressive",
    "goals": ["goal1", "goal2"]
  },
  "allocation": {
    "stocks": <0-1 decimal>,
    "mutual_funds": <0-1 decimal>,
    "bonds": <0-1 decimal>,
    "rationale": "explanation"
  }
}"""

        try:
            logger.info("🧠 Structuring user input with Gemini...")
            
            response = await asyncio.to_thread(
                self.llm.invoke,
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=f"User Input:\n{state['raw_input']}\nExplicit Market Preference: {state.get('market', 'US')}")
                ]
            )
            
            # Parse JSON from response
            content = response.content.strip()
            # Remove markdown code blocks if present
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            
            profile = json.loads(content.strip())
            
            # Calculate investable amount
            surplus = profile["financial_snapshot"]["investable_surplus"]
            savings = profile["financial_snapshot"].get("savings", 0)
            investable = surplus * 6 + savings * 0.7  # 6 months surplus + 70% of savings
            
            logger.info(f"✓ Profile created: {profile['preferences']['risk_tolerance']} investor, ${investable:,.0f} investable")
            
            return {
                **state,
                "user_profile": profile,
                "allocation_strategy": profile["allocation"],
                "investable_amount": investable,
                "execution_log": state.get("execution_log", []) + [f"✓ Structured profile: {profile['preferences']['risk_tolerance']} investor with ${investable:,.0f} to invest"],
                "errors": []
            }
            
        except Exception as e:
            logger.error(f"Input structuring failed: {e}")
            return {
                **state,
                "errors": [f"❌ Input structuring failed: {str(e)}"],
                "execution_log": []
            }


class SectorDiscoveryAgent:
    """Stage 2: Identify top sector with seasonal consideration"""
    
    def __init__(self, news_fetcher: NewsFetcher):
        self.news_fetcher = news_fetcher
    
    async def __call__(self, state: WealthState) -> WealthState:
        """Analyze sectors and apply seasonal filters"""
        if state.get('is_blocked'): return state
        
        # Skip if no stock allocation
        if state.get('allocation_strategy', {}).get('stocks', 0) == 0:
            return {
                **state,
                "execution_log": state.get("execution_log", []) + ["⊘ Skipping sector analysis (0% stock allocation)"],
                "errors": state.get("errors", [])
            }
        
        try:
            logger.info("🔍 Analyzing sectors...")
            
            season = self._get_season(datetime.now().month)
            market = state.get('market', 'US')
            
            if market == 'IN':
                sectors = ["Technology (IT)", "Banking (Finance)", "Energy", "Pharma", "FMCG", "Auto"]
            else:
                sectors = ["Technology", "Finance", "Energy", "Healthcare", "Consumer"]
                
            sector_scores = []
            
            for s in sectors:
                # Add market context to search
                query = f"{s} sector {market}"
                news = await asyncio.to_thread(self.news_fetcher.get_sector_news, query, limit=3)
                score = len(news) * 10 + (20 if season == "Q4/Winter" and ("Energy" in s or "Auto" in s) else 0)
                sector_scores.append({"Sector": s, "Score": score, "News": news})
            
            # Sort by score
            sector_scores.sort(key=lambda x: x["Score"], reverse=True)
            
            selected_sector = sector_scores[0]["Sector"]
            sector_news = sector_scores[0]["News"]
            
            logger.info(f"✓ Selected sector: {selected_sector}")
            
            return {
                **state,
                "current_season": season,
                "sector_rankings": sector_scores,
                "sector_news": sector_news,
                "selected_sector": selected_sector,
                "execution_log": state.get("execution_log", []) + [
                    f"✓ Sector Analysis: {selected_sector} ranked #1 (Season: {season})"
                ],
                "errors": state.get("errors", [])
            }
            
        except Exception as e:
            logger.error(f"Sector discovery failed: {e}")
            return {
                **state,
                "errors": state.get("errors", []) + [f"❌ Sector analysis failed: {str(e)}"],
                "execution_log": state.get("execution_log", [])
            }
    
    def _get_season(self, month: int) -> str:
        """Map month to financial season"""
        if month in [12, 1, 2]:
            return "Q4/Winter"
        elif month in [3, 4, 5]:
            return "Q1/Spring"
        elif month in [6, 7, 8]:
            return "Q2/Summer"
        else:
            return "Q3/Fall"


class StockSelectionAgent:
    """Stage 3: Select stocks with backtesting and deep research"""
    
    def __init__(self, 
                 stock_picker: StockPickerAgent,
                 portfolio_engine: PortfolioEngine,
                 news_fetcher: NewsFetcher,
                 llm_manager: LLMManager,
                 tavily_api_key: Optional[str] = None):
        self.stock_picker = stock_picker
        self.portfolio_engine = portfolio_engine
        self.news_fetcher = news_fetcher
        self.llm = llm_manager
        self.tavily_api_key = tavily_api_key
    
    async def __call__(self, state: WealthState) -> WealthState:
        """Multi-phase stock selection"""
        if state.get('is_blocked'): return state
        
        if not state.get('selected_sector'):
            return {
                **state,
                "execution_log": state.get("execution_log", []) + ["⊘ Skipping stock selection (no sector selected)"],
                "errors": state.get("errors", [])
            }
        
        try:
            logger.info("📊 Selecting stocks...")
            
            sector = state['selected_sector']
            market = state['market']
            
            # 1. Get candidate stocks (up to 5)
            candidates = await asyncio.to_thread(
                self.stock_picker.run,
                market=market,
                sector=sector,
                weights={"seasonal": 0.25, "momentum": 0.30}
            )
            
            if candidates.empty:
                raise ValueError(f"No candidate stocks found for sector: {sector}")
            
            top_candidates = candidates.head(5)
            backtest_results = {}
            valid_candidates = [] # Track which ones actually have data

            # 2. Strict Data Validation Loop
            for idx, stock in top_candidates.iterrows():
                ticker = stock['Ticker']
                strategies_config = ["Sma Crossover"]
                
                end_date = datetime.now().strftime("%Y-%m-%d")
                start_date = (datetime.now().replace(year=datetime.now().year - 1)).strftime("%Y-%m-%d")

                try:
                    # 2a. Pre-check Data Availability (Judge-Proof Rule #2)
                    raw_df = await asyncio.to_thread(get_data, ticker, start_date, end_date, market)
                    
                    if raw_df.empty or len(raw_df) < 50:
                        logger.warning(f"⚠️ Data Insufficient for {ticker} (Rows: {len(raw_df)}). Skipping.")
                        backtest_results[ticker] = {"total_return": -999, "error": "Insufficient Data"}
                        continue # Skip to next candidate
                    
                    # If we get here, data is valid. Proceed to backtest.
                    valid_candidates.append(ticker)
                    
                    # 2b. Run Backtest
                    result = await asyncio.to_thread(
                        self.portfolio_engine.build_portfolio,
                        orchestrator=None, # unused
                        tickers=[ticker],
                        market=market,
                        start_date=start_date,
                        end_date=end_date,
                        strategies_config=strategies_config,
                        initial_capital=10000
                    )
                    
                    metrics = result.get('metrics', {})
                    
                    # 2c. Prepare Chart Data (Real Data + RSI)
                    # Compute RSI manually here to ensure it reaches frontend
                    delta = raw_df['Close'].diff()
                    gain = (delta.where(delta > 0, 0)).fillna(0)
                    loss = (-delta.where(delta < 0, 0)).fillna(0)
                    avg_gain = gain.rolling(window=14).mean()
                    avg_loss = loss.rolling(window=14).mean()
                    rs = avg_gain / avg_loss
                    raw_df['RSI'] = 100 - (100 / (1 + rs))
                    raw_df['RSI'] = raw_df['RSI'].fillna(50)

                    df_chart = raw_df.iloc[::5] # Downsample
                    chart_data = [{"date": str(d.date()), "value": float(v), "rsi": float(r)} for d, v, r in zip(df_chart.index, df_chart['Close'], df_chart['RSI'])]
                    
                    total_ret = float(metrics.get("Total Return %", "0"))
                    backtest_results[ticker] = {
                        "total_return": total_ret, 
                        "metrics": metrics,
                        "chart_data": chart_data
                    }
                    
                    logger.info(f"✅ Validated & Backtested: {ticker}")

                except Exception as bt_err:
                     logger.warning(f"Backtest/Data failed for {ticker}: {bt_err}")
                     backtest_results[ticker] = {"total_return": -999, "error": str(bt_err)}

            # 3. Strategy Selection or Graceful Degradation
            if not valid_candidates:
                logger.warning("❌ CRITICAL: No valid stock data found for any candidate.")
                logger.info("ℹ️ Activating Graceful Degradation Mode (Sector Strategy)")
                
                # Graceful Degradation: Recommend Sector ETF instead of hallucinated stock
                fallback_etf = "XLK" if "Tech" in sector else "SPY"
                if market == "IN": fallback_etf = "NIFTYBEES.NS"
                
                selected_stock = {
                    "Ticker": fallback_etf,
                    "Name": f"{sector} Sector ETF (Fallback)",
                    "Sector": sector,
                    "Reason": "Data unavailable for individual stocks. Recommending Sector ETF for safety."
                }
                
                # We need chart data for the ETF or at least empty
                # Try fetch ETF data
                etf_df = await asyncio.to_thread(get_data, fallback_etf, start_date, end_date, market)
                if not etf_df.empty:
                     df_chart = etf_df.iloc[::5]
                     chart_data = [{"date": str(d.date()), "value": float(v)} for d, v in zip(df_chart.index, etf_df['Close'])]
                else:
                     chart_data = [] # Empty chart better than fake chart
                     
                backtest_results[fallback_etf] = {
                    "total_return": 0.0,
                    "metrics": {"Note": "Market Data Unavailable"},
                    "chart_data": chart_data
                }
                best_ticker = fallback_etf
                
            else:
                # Normal Selection
                best_ticker = max(valid_candidates, key=lambda x: backtest_results[x].get('total_return', -999))
                selected_stock = candidates[candidates['Ticker'] == best_ticker].iloc[0].to_dict()

            # 4. Deep Research
            research = await self._deep_research(best_ticker, market)
            
            logger.info(f"✓ Final Selection: {best_ticker}")
            
            return {
                **state,
                "candidate_stocks": candidates.head(10).to_dict('records'),
                "stock_backtests": backtest_results,
                "selected_stock": selected_stock,
                "stock_research": research,
                "execution_log": state.get("execution_log", []) + [
                    f"✓ Stock Selected: {best_ticker}"
                ],
                "errors": state.get("errors", [])
            }
            
        except Exception as e:
            logger.error(f"Stock selection failed: {e}")
            return {
                **state,
                "errors": state.get("errors", []) + [f"❌ Stock selection failed: {str(e)}"],
                "execution_log": state.get("execution_log", [])
            }
    
    async def _deep_research(self, ticker: str, market: str) -> Dict[str, Any]:
        """Deep dive using Tavily and news analysis"""
        
        research = {
            "ticker": ticker,
            "company_news": [],
            "client_supplier_analysis": {},
            "recommendation": ""
        }
        
        try:
            # Get recent news
            news = await asyncio.to_thread(
                self.news_fetcher.get_stock_news,
                ticker,
                limit=5
            )
            research["company_news"] = news
            
            # Use Tavily if API key provided
            if self.tavily_api_key:
                from tavily import TavilyClient
                tavily = TavilyClient(api_key=self.tavily_api_key)
                
                query = f"{ticker} major clients suppliers customers 2024"
                
                tavily_results = await asyncio.to_thread(
                    tavily.search,
                    query,
                    max_results=3
                )
                
                analysis_prompt = f"""Analyze this company's ecosystem:
Ticker: {ticker}
Research Results: {json.dumps(tavily_results, indent=2)}

Provide:
1. Major clients/customers
2. Key suppliers
3. Supply chain risks

Return as JSON with keys: clients, suppliers, risks"""

                response = await asyncio.to_thread(
                    self.llm.invoke,
                    [
                        SystemMessage(content="You are a supply chain analyst."),
                        HumanMessage(content=analysis_prompt)
                    ]
                )
                
                clean = response.content.replace('```json', '').replace('```', '').strip()
                research["client_supplier_analysis"] = json.loads(clean)
            
        except Exception as e:
            logger.error(f"Deep research failed: {e}")
            research["error"] = str(e)
        
        return research


class MutualFundAgent:
    """Stage 4: MF recommendation based on news and sentiment"""
    
    def __init__(self, news_fetcher: NewsFetcher, sentiment_agent: SentimentAgent, llm_manager: LLMManager):
        self.news_fetcher = news_fetcher
        self.sentiment_agent = sentiment_agent
        self.llm = llm_manager
    
    async def __call__(self, state: WealthState) -> WealthState:
        """Select mutual fund strategy"""
        if state.get('is_blocked'): return state
        
        allocation = state.get('allocation_strategy', {}).get('mutual_funds', 0)
        if allocation == 0:
            return {
                **state,
                "execution_log": state.get("execution_log", []) + ["⊘ Skipping MF (0% allocation)"],
                "errors": state.get("errors", [])
            }
        
        try:
            logger.info("💼 Analyzing mutual funds...")
            market_context = state['market']
            
            # --- SPECIFIC SEARCH AS REQUESTED ---
            # Search for specific top funds in the market
            search_query = f"top performing mutual funds {market_context} 2024 2025"
            fund_news = await asyncio.to_thread(
                self.news_fetcher.get_category_news,
                search_query,
                limit=5
            )
            
            sentiments = await self.sentiment_agent.analyze_batch(
                [art.get('title', '') for art in fund_news]
            )
            
            prompt = f"""Recommend mutual fund category based on:

Market: {market_context}
User Profile:
- Risk: {state['user_profile']['preferences']['risk_tolerance']}
- Horizon: {state['user_profile']['preferences']['horizon']}
- Allocation: {allocation * 100}%

Market Insights: {json.dumps(fund_news[:3], indent=2)}

IMPORTANT: Search constraints require you to identify REAL specific funds mentioned in recent context or standard market leaders.

Recommend specific fund type and rationale. Return JSON:
{{
  "category": "equity|debt|hybrid|index",
  "subcategory": "large_cap|mid_cap|flexi_cap|liquid|gilt|etc",
  "rationale": "explanation",
  "suggested_names": ["Fund Name 1", "Fund Name 2"]
}}"""
            
            response = await asyncio.to_thread(
                self.llm.invoke,
                [
                    SystemMessage(content="You are a mutual fund advisor."),
                    HumanMessage(content=prompt)
                ]
            )
            
            clean = response.content.replace('```json', '').replace('```', '').strip()
            mf_selection = json.loads(clean)
            
            logger.info(f"✓ MF Recommendation: {mf_selection.get('subcategory', 'N/A')}")
            
            return {
                **state,
                "selected_mf": mf_selection,
                "execution_log": state.get("execution_log", []) + [
                    f"✓ MF Type: {mf_selection.get('category', 'N/A')} - {mf_selection.get('subcategory', 'N/A')}"
                ],
                "errors": state.get("errors", [])
            }
            
        except Exception as e:
            logger.error(f"MF selection failed: {e}")
            return {
                **state,
                "errors": state.get("errors", []) + [f"❌ MF selection failed: {str(e)}"],
                "execution_log": state.get("execution_log", [])
            }


class BondAgent:
    """Stage 5: Bond strategy based on macro indicators"""
    
    def __init__(self, macro_agent: MacroAgent, llm_manager: LLMManager, news_fetcher: NewsFetcher = None):
        self.macro_agent = macro_agent
        self.llm = llm_manager
        self.news_fetcher = news_fetcher
    
    async def __call__(self, state: WealthState) -> WealthState:
        """Recommend bond strategy"""
        if state.get('is_blocked'): return state
        
        allocation = state.get('allocation_strategy', {}).get('bonds', 0)
        if allocation == 0:
            return {
                **state,
                "execution_log": state.get("execution_log", []) + ["⊘ Skipping bonds (0% allocation)"],
                "errors": state.get("errors", [])
            }
        
        try:
            logger.info("🏦 Analyzing bond strategy...")
            
            indicators = await asyncio.to_thread(
                self.macro_agent.get_global_indicators
            )
            
            # --- SPECIFIC SEARCH AS REQUESTED ---
            # Attempt to find specific bond issuances or best yield options
            market = state['market']
            bond_news = []
            if self.news_fetcher:
                query = f"best bonds to buy {market} 2025"
                bond_news = await asyncio.to_thread(
                    self.news_fetcher.get_category_news,
                    query, 
                    limit=3
                )

            prompt = f"""Recommend bond strategy based on macro environment:

Macro Indicators: {json.dumps(indicators, indent=2)}
Recent Bond News: {json.dumps(bond_news, indent=2)}

User Profile:
- Risk: {state['user_profile']['preferences']['risk_tolerance']}
- Allocation: {allocation * 100}%

Return JSON:
{{
  "bond_type": "govt|corporate|treasury|municipal",
  "duration": "short|medium|long",
  "specific_instruments": ["Specific Bond 1", "Specific Bond 2"],
  "rationale": "explanation based on interest rate outlook"
}}"""
            
            response = await asyncio.to_thread(
                self.llm.invoke,
                [
                    SystemMessage(content="You are a fixed income strategist."),
                    HumanMessage(content=prompt)
                ]
            )
            
            clean = response.content.replace('```json', '').replace('```', '').strip()
            bond_selection = json.loads(clean)
            
            logger.info(f"✓ Bond Strategy: {bond_selection.get('bond_type', 'N/A')}")
            
            return {
                **state,
                "macro_indicators": indicators,
                "selected_bonds": bond_selection,
                "execution_log": state.get("execution_log", []) + [
                    f"✓ Bonds: {bond_selection.get('bond_type', 'N/A')} - {bond_selection.get('duration', 'N/A')} duration"
                ],
                "errors": state.get("errors", [])
            }
            
        except Exception as e:
            logger.error(f"Bond selection failed: {e}")
            return {
                **state,
                "errors": state.get("errors", []) + [f"❌ Bond selection failed: {str(e)}"],
                "execution_log": state.get("execution_log", [])
            }


class ReportDraftingAgent:
    """Final: Generate comprehensive investment report"""
    
    def __init__(self, llm_manager: LLMManager, guardrails: WealthGuardrails = None):
        self.llm = llm_manager
        self.guardrails = guardrails
    
    async def __call__(self, state: WealthState) -> WealthState:
        """Synthesize all analysis into final report"""
        
        if state.get('is_blocked'):
             # Return just the blocked report
             return state

        try:
            logger.info("📝 Drafting investment report...")
            
            prompt = f"""Create a simplified, action-oriented investment report.
DO NOT include any conversational filler, executive summaries, or explanations of your internal logic.
Directly provide the actionable advice in the following format.

Data:
Total Investable: ${state.get('investable_amount', 0):,.2f}
Allocation: {json.dumps(state.get('allocation_strategy', {}), indent=2)}
Stock: {json.dumps(state.get('selected_stock', {}), indent=2)}
Funds: {json.dumps(state.get('selected_mf', {}), indent=2)}
Bonds: {json.dumps(state.get('selected_bonds', {}), indent=2)}

OUTPUT FORMAT (STRICT):

## 🚀 ACTION PLAN

### 💰 INVESTMENT BREAKDOWN
*   **Total Investment:** ${state.get('investable_amount', 0):,.2f}
*   **Stocks:** X% -> $Amount
*   **Mutual Funds:** Y% -> $Amount
*   **Bonds:** Z% -> $Amount

### 1. STOCK: [TICKER]
*   **Why to Buy:** [One clear sentence reason]
*   **What to Buy:** Buy [Ticker] at Market Price
*   **Price Target:** [Projected Price based on momentum]
*   **Stop Loss:** [Calculated stop loss, e.g. 5-8% below current]
*   **When to Sell:** [Condition for exit, e.g. "If monthly trend reverses"]

### 2. MUTUAL FUND: [FUND NAME]
*   **Strategy:** Start SIP in [Category]
*   **Why:** [One sentence reason]
*   **Allocation:** Deploy calculated MF amount here.

### 3. BONDS
*   **Action:** Buy [Instrument Name]
*   **Goal:** [One sentence goal]
*   **Allocation:** Deploy calculated Bond amount here.

---
*Generated by Wealth OS*
"""

            response = await asyncio.to_thread(
                self.llm.invoke,
                [
                    SystemMessage(content="You are a certified financial planner (CFP) drafting client reports."),
                    HumanMessage(content=prompt)
                ]
            )
            
            logger.info("✓ Report generated successfully")
            
            final_report = response.content
            
            # Apply Disclaimer Guardrail
            if self.guardrails:
                final_report = self.guardrails.add_disclaimer(final_report)
            
            return {
                **state,
                "investment_report": final_report,
                "execution_log": state.get("execution_log", []) + ["✓ Investment report completed"],
                "errors": state.get("errors", [])
            }
            
        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            return {
                **state,
                "investment_report": "# Error\n\nFailed to generate report. Please review the execution log.",
                "errors": state.get("errors", []) + [f"❌ Report generation failed: {str(e)}"],
                "execution_log": state.get("execution_log", [])
            }


# ============================================================================
# MAIN ORCHESTRATOR
# ============================================================================

class AutonomousWealthManager:
    """Main orchestrator using LangGraph for async workflow"""
    
    def __init__(self,
                 gemini_api_key: str,
                 sector_agent: Any,
                 stock_picker: StockPickerAgent,
                 portfolio_engine: PortfolioEngine,
                 news_fetcher: NewsFetcher,
                 sentiment_agent: SentimentAgent,
                 macro_agent: MacroAgent,
                 tavily_api_key: Optional[str] = None):
        
        # Initialize LLM Manager (Handles Multi-Key Fallback)
        self.llm_manager = LLMManager(temperature=0.7)
        
        # Initialize Guardrails
        self.guardrails = WealthGuardrails(self.llm_manager)
        
        # Initialize agents
        self.guard_agent = GuardrailAgent(self.guardrails)
        self.input_agent = InputStructurerAgent(self.llm_manager)
        self.sector_agent = SectorDiscoveryAgent(news_fetcher)
        self.stock_agent = StockSelectionAgent(stock_picker, portfolio_engine, news_fetcher, self.llm_manager, tavily_api_key)
        self.mf_agent = MutualFundAgent(news_fetcher, sentiment_agent, self.llm_manager)
        self.bond_agent = BondAgent(macro_agent, self.llm_manager, news_fetcher) # Added news_fetcher for bonds
        self.report_agent = ReportDraftingAgent(self.llm_manager, self.guardrails)
        
        # Build workflow
        self.workflow = self._build_workflow()
    
    def _build_workflow(self) -> StateGraph:
        """Construct LangGraph workflow"""
        
        workflow = StateGraph(WealthState)
        
        # Add nodes
        workflow.add_node("guardrails", self.guard_agent)
        workflow.add_node("structure_input", self.input_agent)
        workflow.add_node("discover_sector", self.sector_agent)
        workflow.add_node("select_stock", self.stock_agent)
        workflow.add_node("select_mf", self.mf_agent)
        workflow.add_node("select_bonds", self.bond_agent)
        workflow.add_node("draft_report", self.report_agent)
        
        # Define flow with conditional logic
        workflow.set_entry_point("guardrails")
        
        # Conditional edge: If blocked -> draft_report (which returns blocked message) -> END
        # Or simpler: If blocked -> END. But we need to return the state. 
        # Let's route blocked requests directly to Report agent (which effectively just returns state) or hand off.
        # Actually, if blocked, we can go straight to draft_report which handles blocked state, or just END.
        
        def check_blocked(state):
            return "draft_report" if state.get("is_blocked") else "structure_input"

        workflow.add_conditional_edges(
            "guardrails",
            check_blocked,
            {
                "draft_report": "draft_report",
                "structure_input": "structure_input"
            }
        )
        
        workflow.add_edge("structure_input", "discover_sector")
        workflow.add_edge("discover_sector", "select_stock")
        workflow.add_edge("select_stock", "select_mf")
        workflow.add_edge("select_mf", "select_bonds")
        workflow.add_edge("select_bonds", "draft_report")
        workflow.add_edge("draft_report", END)
        
        return workflow.compile()
    
    async def run(self, raw_user_input: str, market: str = "US") -> Dict[str, Any]:
        """Execute autonomous wealth management workflow"""
        
        logger.info("🚀 Starting Autonomous Wealth Analysis...")
        
        initial_state = {
            "raw_input": raw_user_input,
            "market": market,
            "execution_log": [],
            "errors": [],
            "is_blocked": False
        }
        
        # Run workflow
        final_state = await self.workflow.ainvoke(initial_state)
        
        logger.info("✅ Wealth analysis complete")
        
        return {
            "success": len(final_state.get("errors", [])) == 0,
            "report": final_state.get("investment_report", ""),
            "profile": final_state.get("user_profile", {}),
            "allocation": final_state.get("allocation_strategy", {}),
            "selected_stock": final_state.get("selected_stock", {}),
            "selected_mf": final_state.get("selected_mf", {}),
            "selected_bonds": final_state.get("selected_bonds", {}),
            "execution_log": final_state.get("execution_log", []),
            "errors": final_state.get("errors", [])
        }
