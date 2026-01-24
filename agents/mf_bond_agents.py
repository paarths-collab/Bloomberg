import os
import requests
from langchain_core.messages import HumanMessage, SystemMessage
from fredapi import Fred
from state import WealthState
import json

class MutualFundAgent:
    """Stage 4a: MF Selection using Guardian News"""
    
    def __init__(self, llm_manager):
        self.llm_manager = llm_manager
        self.guardian_key = os.getenv("GUARDIAN_API_KEY")

    def __call__(self, state: WealthState) -> WealthState:
        # Check allocation
        if state.get('allocation_strategy', {}).get('mutual_funds', 0) <= 0:
            return {**state, "messages": ["⚠️ Skipping MF (0% allocation)"]}
            
        try:
            # Fetch 'Best Mutual Funds' news
            news = self._get_mf_news()
            
            # Recommend
            prompt = f"""Recommend a mutual fund category based on news and user profile.
            
            User Profile: {state.get('user_profile', {})}
            News Headlines: {[n['title'] for n in news[:5]]}
            
            Return JSON: {{ "category": "Large Cap", "rationale": "..." }}
            """
            response = self.llm_manager.invoke([HumanMessage(content=prompt)])
            rec = json.loads(response.content.replace('```json','').replace('```','').strip())
            
            return {
                **state,
                "selected_mf": rec,
                "messages": [f"✓ MF Strategy: {rec['category']}"]
            }
        except Exception as e:
             return {**state, "errors": [f"MF Agent Failed: {e}"]}

    def _get_mf_news(self):
        url = "https://content.guardianapis.com/search"
        params = {"api-key": self.guardian_key, "q": "mutual funds investment", "section": "business"}
        try:
            r = requests.get(url, params=params)
            return [{"title": x['webTitle']} for x in r.json()['response']['results']]
        except:
            return []


class BondAgent:
    """Stage 4b: Bond Selection using FRED Data"""
    
    def __init__(self, llm_manager):
        self.llm_manager = llm_manager
        self.fred = Fred(api_key=os.getenv("FRED_API_KEY"))

    def __call__(self, state: WealthState) -> WealthState:
        if state.get('allocation_strategy', {}).get('bonds', 0) <= 0:
            return {**state, "messages": ["⚠️ Skipping Bonds (0% allocation)"]}
            
        try:
            # Fetch 10Y Treasury Yield
            yield_10y = self.fred.get_series('DGS10').iloc[-1]
            inflation = self.fred.get_series('CPIAUCSL').pct_change(12).iloc[-1] * 100
            
            macro_data = {"10y_yield": yield_10y, "inflation": inflation}
            
            prompt = f"""Recommend bond strategy given:
            10Y Yield: {yield_10y}%
            Inflation: {inflation}%
            User Profile: {state.get('user_profile')}
            
            Return JSON: {{ "bond_type": "Govt/Corp", "duration": "Short/Long", "rationale": "..." }}
            """
            
            response = self.llm_manager.invoke([HumanMessage(content=prompt)])
            rec = json.loads(response.content.replace('```json','').replace('```','').strip())
            
            return {
                **state,
                "macro_indicators": macro_data,
                "selected_bonds": rec,
                "messages": [f"✓ Bond Strategy: {rec['bond_type']} ({rec['duration']})"]
            }
        except Exception as e:
            return {**state, "errors": [f"Bond Agent Failed: {e}"]}
