import pandas as pd
import numpy as np
import yfinance as yf
import streamlit as st
import plotly.graph_objects as go # <-- ADDED THIS MISSING IMPORT
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
from typing import List, Dict, Any

# --- Helper Indicators ---
def SMA(values, n):
    return pd.Series(values).rolling(n).mean()

def RSI(close, period=14):
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- The Strategy Class (with risk management) ---
class MA_RSI_Risk_Strategy(Strategy):
    fast_ma = 50; slow_ma = 200; rsi_period = 14; rsi_upper = 70
    risk_per_trade = 0.02; stop_loss_pct = 0.05; take_profit_pct = 0.10
    trailing_pct = 0.05; max_drawdown_stop = 0.20

    def init(self):
        close = self.data.Close
        self.ma_fast = self.I(SMA, close, self.fast_ma)
        self.ma_slow = self.I(SMA, close, self.slow_ma)
        self.rsi = self.I(RSI, close, self.rsi_period)
        self.equity_peak = self.equity
        self.can_trade = True
        self._entry_price = None; self._position_peak = None

    def _position_size(self, price):
        risk_amount = self.equity * self.risk_per_trade
        risk_per_share = price * self.stop_loss_pct
        if risk_per_share <= 0: return 0
        return int(risk_amount / risk_per_share)

    def next(self):
        price = self.data.Close[-1]
        if self.equity > self.equity_peak: self.equity_peak = self.equity
        drawdown = (self.equity_peak - self.equity) / self.equity_peak
        if drawdown >= self.max_drawdown_stop:
            self.can_trade = False
            if self.position: self.position.close()
            return
        if self.position:
            self._position_peak = max(self._position_peak or price, price)
            if price <= self._position_peak * (1 - self.trailing_pct) or \
               (self._entry_price and price <= self._entry_price * (1 - self.stop_loss_pct)) or \
               (self._entry_price and price >= self._entry_price * (1 + self.take_profit_pct)):
                self.position.close()
                self._entry_price = None; self._position_peak = None
                return
        if crossover(self.ma_fast, self.ma_slow) and self.rsi[-1] < self.rsi_upper and not self.position and self.can_trade:
            size = self._position_size(price)
            if size > 0:
                self.buy(size=size)
                self._entry_price = price; self._position_peak = price
        elif (crossover(self.ma_slow, self.ma_fast) or self.rsi[-1] > self.rsi_upper) and self.position:
            self.position.close()
            self._entry_price = None; self._position_peak = None

# --- The Backtester Class (Orchestrator/API Entry Point) ---
class AdvancedBacktester:
    def __init__(self):
        """Initializes the backtester."""
        print("✅ AdvancedBacktester initialized.")
        self.presets = {
            "swing": {"fast_ma": 20, "slow_ma": 50, "rsi_period": 14, "rsi_upper": 70},
            "long_term": {"fast_ma": 50, "slow_ma": 200, "rsi_period": 14, "rsi_upper": 75},
            "short_term": {"fast_ma": 10, "slow_ma": 20, "rsi_period": 9, "rsi_upper": 80},
        }

    def run(self, ticker: str, start_date: str, end_date: str, preset: str = "swing", cash: float = 100000) -> Dict[str, Any]:
        """
        Runs a single, comprehensive backtest for one stock using the advanced strategy.
        """
        print(f"AdvancedBacktester: Running '{preset}' preset for {ticker}...")
        try:
            data = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if data.empty:
                return {"Error": "No data found for the given ticker and date range."}

            TempStrategy = MA_RSI_Risk_Strategy
            params = self.presets.get(preset, self.presets["swing"])
            for key, value in params.items():
                setattr(TempStrategy, key, value)
            
            bt = Backtest(data, TempStrategy, cash=cash, commission=0.002, exclusive_orders=True)
            stats = bt.run()

            return {
                "Ticker": ticker,
                "Strategy Preset": preset.title(),
                "Return %": f"{stats.get('Return [%]', 0):.2f}",
                "Sharpe Ratio": f"{stats.get('Sharpe Ratio', 0):.2f}",
                "Max Drawdown %": f"{stats.get('Max. Drawdown [%]', 0):.2f}",
                "Win Rate %": f"{stats.get('Win Rate [%]', 0):.2f}",
                "Number of Trades": int(stats.get('# Trades', 0)),
                "_trades": stats._trades,
                "_equity_curve": stats._equity_curve
            }
        except Exception as e:
            return {"Ticker": ticker, "Strategy Preset": preset.title(), "Error": str(e)}

# --- Streamlit Visualization (Frontend Part) ---
if __name__ == "__main__":
    st.set_page_config(page_title="Advanced Backtester", layout="wide")
    st.title("🛡️ Advanced Strategy Backtester with Risk Management")

    backtester = AdvancedBacktester()

    with st.sidebar:
        st.header("⚙️ Configuration")
        ticker = st.text_input("Ticker Symbol", "RELIANCE.NS")
        start_date = st.date_input("Start Date", pd.to_datetime("2020-01-01"))
        end_date = st.date_input("End Date", pd.to_datetime("today"))
        preset = st.selectbox("Select Strategy Preset", options=list(backtester.presets.keys()))
        run_button = st.button("🔬 Run Backtest", use_container_width=True)

    if run_button:
        st.header(f"Results for {ticker} (Preset: {preset.title()})")
        
        with st.spinner("Running advanced backtest..."):
            results = backtester.run(ticker, str(start_date), str(end_date), preset=preset)
            
            if "Error" in results:
                st.error(results["Error"])
            else:
                st.subheader("Performance Summary")
                cols = st.columns(5)
                cols[0].metric("Total Return", f"{results.get('Return %', '0.00')}%")
                cols[1].metric("Sharpe Ratio", results.get('Sharpe Ratio', '0.00'))
                cols[2].metric("Max Drawdown", f"{results.get('Max Drawdown %', '0.00')}%")
                cols[3].metric("Win Rate", f"{results.get('Win Rate %', '0.00')}%")
                cols[4].metric("Trades", results.get('Number of Trades', 0))

                st.subheader("Equity Curve & Trades")
                
                equity_df = results.get('_equity_curve')
                trades_df = results.get('_trades')
                
                if equity_df is not None:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=equity_df.index, y=equity_df['Equity'], name='Equity Curve'))

                    if trades_df is not None and not trades_df.empty:
                        buy_trades = trades_df[trades_df['Size'] > 0]
                        sell_trades = trades_df[trades_df['Size'] < 0]
                        fig.add_trace(go.Scatter(x=buy_trades['EntryTime'], y=buy_trades['EntryPrice'], mode='markers', name='Buy', marker=dict(color='green', size=10, symbol='triangle-up')))
                        fig.add_trace(go.Scatter(x=sell_trades['EntryTime'], y=sell_trades['EntryPrice'], mode='markers', name='Sell', marker=dict(color='red', size=10, symbol='triangle-down')))

                    fig.update_layout(title_text=f"Equity Curve and Trades for {ticker}", xaxis_title="Date", yaxis_title="Portfolio Value ($)")
                    st.plotly_chart(fig, use_container_width=True)

                    st.subheader("Trade Log")
                    st.dataframe(trades_df)