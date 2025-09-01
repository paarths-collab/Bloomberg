import yfinance as yf
import pandas as pd
import streamlit as st
import plotly.express as px
from typing import List, Dict
import os

class StockPickerAgent:
    def __init__(self, 
                 data_path: str = "quant-company-insights-agent/data",
                 cache_path: str = "quant-company-insights-agent/data/stock_universe.parquet"):
        """
        Initializes the StockPickerAgent by loading a dynamic, cached universe of stocks.
        """
        self.data_path = data_path
        self.cache_path = cache_path
        self.stock_universe = self._load_or_build_universe_cache()
        
        if self.stock_universe.empty:
            print("❌ StockPickerAgent WARNING: Stock universe is empty. Agent will not function.")
        else:
            print(f"✅ StockPickerAgent: Loaded {len(self.stock_universe)} stocks with sector data.")

    def _load_or_build_universe_cache(self) -> pd.DataFrame:
        """Loads the stock universe from a cache file or builds it if it doesn't exist."""
        if os.path.exists(self.cache_path):
            print(f"StockPickerAgent: Loading stock universe from cache: {self.cache_path}")
            return pd.read_parquet(self.cache_path)
        else:
            return self._build_universe_cache()

    def _build_universe_cache(self) -> pd.DataFrame:
        """
        Slow, one-time process to load all Indian stocks from CSVs, fetch their sectors
        using yfinance, and build a cache file.
        """
        print("StockPickerAgent: Building stock universe cache... This will take a VERY long time and only runs once.")
        try:
            main_path = os.path.join(self.data_path, "EQUITY_L.csv")
            sme_path = os.path.join(self.data_path, "SME_EQUITY_L.csv")
            df_main = pd.read_csv(main_path)
            df_sme = pd.read_csv(sme_path)
            
            # Clean and combine
            df_main.rename(columns=lambda x: x.strip().upper().replace(" ", "_"), inplace=True)
            df_sme.rename(columns=lambda x: x.strip().upper().replace(" ", "_"), inplace=True)
            universe_df = pd.concat([df_main[['SYMBOL', 'NAME_OF_COMPANY']], df_sme[['SYMBOL', 'NAME_OF_COMPANY']]], ignore_index=True)
            universe_df['YF_TICKER'] = universe_df['SYMBOL'] + '.NS'
        except FileNotFoundError as e:
            print(f"❌ StockPickerAgent ERROR: Could not find stock data file: {e}")
            return pd.DataFrame()

        sectors = []
        total = len(universe_df)
        for i, row in universe_df.iterrows():
            # Add a progress printout
            print(f"  Fetching sector for {row['YF_TICKER']} ({i+1}/{total})...")
            try:
                # Use the fast 'info' fetch
                sector = yf.Ticker(row['YF_TICKER']).info.get('sector', 'Unknown')
                sectors.append(sector)
            except Exception:
                sectors.append('Unknown') # Append 'Unknown' on any error
        
        universe_df['Sector'] = sectors
        
        # Save the enriched dataframe to a fast parquet file for future runs
        universe_df.to_parquet(self.cache_path)
        print(f"✅ StockPickerAgent: Universe cache built and saved to {self.cache_path}")
        return universe_df

    def _get_stock_data(self, tickers: List[str]) -> Dict[str, yf.Ticker]:
        """Fetches and caches yfinance Ticker objects."""
        print(f"StockPickerAgent: Fetching detailed data for {len(tickers)} stocks...")
        return {ticker: yf.Ticker(ticker) for ticker in tickers}

    def calculate_scores(self, stock_data: Dict[str, yf.Ticker]) -> pd.DataFrame:
        """Calculates momentum, value, and quality scores for each stock."""
        all_metrics = []
        for ticker, stock_obj in stock_data.items():
            try:
                info = stock_obj.info
                hist = stock_obj.history(period="1y")
                if hist.empty: continue
                
                momentum_score = (hist['Close'].iloc[-1] / hist['Close'].iloc[0] - 1) * 100
                pe = info.get('trailingPE')
                value_score = 1 / pe if pe and pe > 0 else 0
                roe = info.get('returnOnEquity')
                quality_score = roe if roe else 0

                all_metrics.append({
                    "Ticker": ticker, "Momentum": momentum_score,
                    "Value": value_score * 100, "Quality (ROE)": quality_score * 100 if quality_score else 0
                })
            except Exception:
                continue # Skip stocks with data fetching errors
        return pd.DataFrame(all_metrics).dropna()

    def rank_stocks(self, scores_df: pd.DataFrame, weights: Dict[str, float]) -> pd.DataFrame:
        """Ranks stocks based on a weighted average of their scores."""
        if scores_df.empty: return pd.DataFrame()
        for metric in ['Momentum', 'Value', 'Quality (ROE)']:
            scores_df[f'{metric}_Rank'] = scores_df[metric].rank(pct=True) * 100
        scores_df['Final Score'] = (
            scores_df['Momentum_Rank'] * weights['momentum'] +
            scores_df['Value_Rank'] * weights['value'] +
            scores_df['Quality (ROE)_Rank'] * weights['quality']
        )
        return scores_df.sort_values('Final Score', ascending=False).reset_index(drop=True)

    def run(self, sector: str, weights: Dict[str, float], top_n: int = 5) -> List[str]:
        """
        Runs the full stock picking pipeline for a given sector from the dynamic universe.
        """
        print(f"StockPickerAgent: Running discovery for '{sector}' sector...")
        
        # --- THIS IS THE DYNAMIC PART ---
        # Filter the full universe to get tickers for the selected sector
        tickers_to_analyze = self.stock_universe[self.stock_universe['Sector'] == sector]['YF_TICKER'].tolist()
        
        if not tickers_to_analyze:
            return [f"Error: No stocks found for sector '{sector}' in the loaded universe."]
            
        stock_data = self._get_stock_data(tickers_to_analyze)
        scores_df = self.calculate_scores(stock_data)
        ranked_df = self.rank_stocks(scores_df, weights)
        
        # Return the DataFrame for the Streamlit showcase to use
        return ranked_df.head(top_n)

# --- Streamlit Visualization ---
if __name__ == "__main__":
    st.set_page_config(page_title="Dynamic Stock Picker", layout="wide")
    st.title("🎯 Dynamic Multi-Factor Stock Picker Agent")

    agent = StockPickerAgent()
    
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Get the list of available sectors dynamically from the loaded data
        available_sectors = sorted(agent.stock_universe['Sector'].unique().tolist())
        sector = st.selectbox("Select a Sector to Analyze", options=available_sectors)
        
        st.subheader("Factor Weights")
        w_momentum = st.slider("Momentum Weight", 0.0, 1.0, 0.4, 0.05)
        w_value = st.slider("Value Weight", 0.0, 1.0, 0.3, 0.05)
        w_quality = st.slider("Quality (ROE) Weight", 0.0, 1.0, 0.3, 0.05)

        run_button = st.button("🔬 Find Top Stocks", use_container_width=True)

    if run_button:
        total_weight = w_momentum + w_value + w_quality
        if total_weight == 0:
            st.error("Total weight cannot be zero.")
        else:
            weights = {
                "momentum": w_momentum / total_weight, "value": w_value / total_weight, "quality": w_quality / total_weight,
            }
            st.header(f"Top Stock Picks for: *{sector}*")
            with st.spinner(f"Fetching data and ranking stocks in the {sector} sector..."):
                # The agent's run method now returns a DataFrame
                ranked_df = agent.run(sector, weights, top_n=10)

                if ranked_df.empty or "Error" in ranked_df.iloc[0]:
                    st.error("Could not generate rankings. The sector might be empty or data could not be fetched.")
                else:
                    st.subheader("🏆 Final Rankings")
                    st.dataframe(ranked_df[['Ticker', 'Final Score', 'Momentum', 'Value', 'Quality (ROE)']])

                    st.subheader("Visual Factor Comparison")
                    fig = px.bar(ranked_df, x='Ticker', y=['Momentum_Rank', 'Value_Rank', 'Quality (ROE)_Rank'],
                                 title=f"Factor Ranks for Top 10 Stocks in {sector}",
                                 labels={'value': 'Normalized Rank (0-100)', 'variable': 'Factor'})
                    st.plotly_chart(fig, use_container_width=True)