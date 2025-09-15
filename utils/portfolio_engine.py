# File: utils/portfolio_engine.py
# This is the backend logic for your application.

import pandas as pd
import numpy as np
import yfinance as yf

# --- Import all strategy run functions from the 'strategies' package ---
from strategies.breakout_strategy import run as run_breakout
from strategies.channel_trading import run as run_channel_trading
from strategies.ema_crossover import run as run_ema_crossover
from strategies.macd_strategy import run as run_macd_strategy
from strategies.mean_inversion import run as run_mean_inversion
from strategies.momentum_strategy import run as run_momentum_strategy
from strategies.pairs_trading import run as run_pairs_trading
from strategies.pullback_fibonacci import run as run_pullback_fibonacci
from strategies.reversal_strategy import run as run_reversal_strategy
from strategies.rsi_strategy import run as run_rsi_strategy
from strategies.sma_crossover import run as run_sma_crossover
from strategies.support_resistance import run as run_support_resistance

# --- Create the strategy mapping ---
STRATEGY_MAPPING = {
    "Breakout Strategy": run_breakout, "Channel Trading": run_channel_trading,
    "EMA Crossover": run_ema_crossover, "MACD Strategy": run_macd_strategy,
    "Mean Reversion": run_mean_inversion, "Momentum Strategy": run_momentum_strategy,
    "Pairs Trading": run_pairs_trading, "Fibonacci Pullback": run_pullback_fibonacci,
    "RSI Reversal": run_reversal_strategy, "RSI Momentum": run_rsi_strategy,
    "SMA Crossover": run_sma_crossover, "Support/Resistance": run_support_resistance,
}

# --- Self-Contained Backtesting Engine and Metric Functions ---
def get_benchmark_data(ticker, start, end, initial_capital):
    df = yf.download(ticker, start=start, end=end, progress=False)
    df['Returns'] = df['Close'].pct_change()
    df['Equity_Curve'] = initial_capital * (1 + df['Returns']).cumprod()
    return df

def calculate_portfolio_metrics(equity_curve, start_date, end_date):
    if equity_curve is None or equity_curve.empty: return {}
    days = (pd.to_datetime(end_date) - pd.to_datetime(start_date)).days
    years = max(days / 365.25, 1/52)
    initial_capital = equity_curve.iloc[0]
    final_equity = equity_curve.iloc[-1]
    total_return_pct = (final_equity / initial_capital - 1) * 100
    cagr = ((final_equity / initial_capital) ** (1 / years) - 1) * 100
    daily_returns = equity_curve.pct_change().dropna()
    if daily_returns.empty or daily_returns.std() == 0:
        sharpe_ratio, annual_volatility = 0.0, 0.0
    else:
        annual_volatility = daily_returns.std() * np.sqrt(252) * 100
        sharpe_ratio = (daily_returns.mean() * 252) / (daily_returns.std() * np.sqrt(252))
    peak = equity_curve.cummax()
    drawdown = (equity_curve - peak) / peak
    max_drawdown_pct = drawdown.min() * 100
    return {
        "Total Return %": f"{total_return_pct:.2f}", "CAGR %": f"{cagr:.2f}",
        "Annual Volatility %": f"{annual_volatility:.2f}", "Sharpe Ratio": f"{sharpe_ratio:.2f}",
        "Max Drawdown %": f"{max_drawdown_pct:.2f}",
    }

def run_portfolio_backtest(selections, start_date, end_date, initial_capital):
    all_equity_curves = {}
    error_messages = []
    for key, params in selections.items():
        strategy_name = params['name']
        run_func = STRATEGY_MAPPING[strategy_name]
        run_params = {"start_date": start_date, "end_date": end_date, "initial_capital": initial_capital, **params['params']}
        if strategy_name == "Pairs Trading":
            tickers = [t.strip().upper() for t in params["ticker"].split(",")]
            if len(tickers) != 2:
                error_messages.append(f"Pairs Trading requires exactly two tickers for '{key}'. Skipping.")
                continue
            run_params["tickers"] = tickers
        else:
            run_params["ticker"] = params["ticker"]
        
        results = run_func(**run_params)
        if "Error" in results.get("summary", {}) or results.get("data", pd.DataFrame()).empty:
            error_messages.append(f"Backtest for {strategy_name} on {params['ticker']} failed. Skipping.")
            continue
        all_equity_curves[key] = {"equity": results["data"]['Equity_Curve'], "weight": params['weight']}

    if not all_equity_curves: return pd.DataFrame(), {}, error_messages
    portfolio_df = pd.DataFrame()
    for key, data in all_equity_curves.items():
        strategy_returns = data['equity'].pct_change().fillna(0)
        portfolio_df[f'{key}_weighted_returns'] = strategy_returns * data['weight']
    portfolio_df['Total_Returns'] = portfolio_df.sum(axis=1)
    portfolio_df['Equity_Curve'] = (1 + portfolio_df['Total_Returns']).cumprod() * initial_capital
    portfolio_df.iloc[0]['Equity_Curve'] = initial_capital
    metrics = calculate_portfolio_metrics(portfolio_df['Equity_Curve'], start_date, end_date)
    return portfolio_df, metrics, error_messages
# import pandas as pd
# from utils.data_loader import format_ticker, get_history
# from utils import risk_metrics
  
# def build_portfolio(orchestrator, tickers, market, start_date, end_date, strategies_config, **kwargs):
#         """
#         Builds and evaluates a portfolio from a list of STRATEGY NAMES.
#         """
#         print(f"PortfolioEngine: Building portfolio for tickers in '{market}' market...")
#         if not tickers: return {"error": "No tickers provided."}
#         if not strategies_config: return {"error": "No strategies selected."}
        
#         ticker = tickers[0]
#         formatted_ticker = format_ticker(ticker, market)
        
#         all_returns = {}
#         valid_strategy_names = []

#         # This loop correctly iterates over a list of strings.
#         for strategy_name in strategies_config:
#             strategy_module = orchestrator.short_term_modules.get(strategy_name)
#             if not strategy_module:
#                 print(f"WARNING: Strategy '{strategy_name}' not found. Skipping.")
#                 continue
                
#             print(f"--- Running: {strategy_name} on {formatted_ticker} ---")
#             # Call the strategy's run function with the simple, correct signature.
#             result = strategy_module.run(
#                     ticker=formatted_ticker,
#                     start_date=start_date,
#                     end_date=end_date,
#                 # Pass the slow period from your config
#                 )
            
#             summary = result.get("summary", {})
#             equity_curve_df = result.get("data")

#             if summary.get("Error") or equity_curve_df is None:
#                 print(f"WARNING: Strategy '{strategy_name}' failed: {summary.get('Error', 'No data')}. Skipping.")
#                 continue

#             if summary.get('# Trades', 0) > 0 and not equity_curve_df.empty:
#                 all_returns[strategy_name] = equity_curve_df['Equity'].pct_change().fillna(0)
#                 valid_strategy_names.append(strategy_name)
#             else:
#                 print(f"INFO: Strategy '{strategy_name}' produced no trades. Treating as 0% return.")
#                 # Use a benchmark to get a correctly dated index of zero returns.
#                 spy_data = get_history("SPY", start_date, end_date)
#                 if not spy_data.empty:
#                     all_returns[strategy_name] = pd.Series(0, index=spy_data.index)
#                     valid_strategy_names.append(strategy_name)

#         if not all_returns:
#             return {"error": "No strategies produced valid backtests."}

#         # Combine all successful strategy returns into a single portfolio.
#         returns_df = pd.DataFrame(all_returns)
#         num_strategies = len(valid_strategy_names)
#         equal_weight = 1 / num_strategies if num_strategies > 0 else 0
#         weights = {name: round(equal_weight * 100, 2) for name in valid_strategy_names}
        
#         returns_df['Portfolio'] = returns_df.mean(axis=1) # Simple average for equal weight
        
#         initial_capital = 100_000
#         final_equity_curve = initial_capital * (1 + returns_df).cumprod()

#         # Analyze performance against a benchmark.
#         benchmark_symbol = "SPY"
#         benchmark_returns = risk_metrics.get_benchmark_returns(benchmark_symbol, start_date, end_date)
#         final_equity_curve[benchmark_symbol] = initial_capital * (1 + benchmark_returns).cumprod()
        
#         portfolio_metrics = risk_metrics.calculate_all_metrics(final_equity_curve['Portfolio'], benchmark_returns)

#         return {
#             "equity_curve": final_equity_curve,
#             "metrics": portfolio_metrics,
#             "weights": weights,
#             "currency_symbol": "$",
#             "benchmark": benchmark_symbol,
#             "error": None
#         }
# --- IGNORE ---
# from . import risk_metrics
# from agents.orchestrator import Orchestrator
# from utils.data_loader import format_ticker # Ensure this import is present

# def build_portfolio(
#     orchestrator: Orchestrator,
#     tickers: list,
#     strategies: list,
#     weights: list,
#     start_date: str,
#     end_date: str,
#     market: str,
#     strategy_params: dict = None
# ) -> dict:
#     """
#     Builds and backtests a portfolio by running specified strategies on a list of tickers.
#     """
#     if sum(weights) != 100:
#         return {"error": "Strategy weights must sum to 100."}
#     if not tickers:
#         return {"error": "At least one ticker must be provided."}
#     if not strategies:
#         return {"error": "At least one strategy must be selected."}

#     strategy_params = strategy_params or {}
    
#     # --- THIS IS THE PRIMARY FIX ---
#     # 1. Format all user-provided tickers for the correct market
#     try:
#         formatted_tickers = [format_ticker(t, market) for t in tickers]
#         print(f"PortfolioEngine: Running analysis on formatted tickers: {formatted_tickers}")
#     except Exception as e:
#         return {"error": f"Failed to format tickers: {e}"}
#     # --- END OF PRIMARY FIX ---

#     all_strategy_returns = pd.DataFrame()
    
#     # 2. Loop through EACH formatted ticker
#     for ticker in formatted_tickers:
#         for strat_name in strategies:
#             strategy_module = orchestrator.short_term_modules.get(strat_name)
#             if not strategy_module:
#                 print(f"WARNING: Strategy '{strat_name}' not found. Skipping.")
#                 continue

#             # Run the backtest for the current ticker and strategy
#             result = strategy_module.run(
#                 ticker, 
#                 start_date, 
#                 end_date, 
#                 **strategy_params
#             )
            
#             # The run() function now returns a dictionary with a 'returns_series'
#             returns_series = result.get('returns_series')
            
#             if returns_series is None or not isinstance(returns_series, pd.Series) or returns_series.empty:
#                 print(f"WARNING: Strategy '{strat_name}' on {ticker} did not produce valid returns. Skipping.")
#                 continue
            
#             # Store the individual returns series with a unique name
#             all_strategy_returns[f"{ticker}_{strat_name}"] = returns_series

#     if all_strategy_returns.empty:
#         return {"error": "None of the selected strategies produced valid results for the given tickers."}
        
#     # 3. Combine the returns based on the user-defined weights
#     # Note: This is a simplified weighting. A real engine would handle this differently,
#     # but for this logic, we will average the returns of all generated series.
#     portfolio_daily_returns = all_strategy_returns.mean(axis=1)
    
#     # 4. Calculate final portfolio metrics
#     portfolio_equity_curve = (1 + portfolio_daily_returns).cumprod() * 100_000
    
#     benchmark_ticker = "SPY" if market.lower() == "usa" else "^NSEI"
#     benchmark_returns = risk_metrics.get_benchmark_returns(symbol=benchmark_ticker, start=start_date, end=end_date)
    
#     # Ensure a full set of metrics is calculated
#     all_metrics = risk_metrics.calculate_all_metrics(portfolio_daily_returns, benchmark_returns)
    
#     currency_symbol = "₹" if market.lower() == "india" else "$"

#     return {
#         "equity_curve": portfolio_equity_curve,
#         "metrics": all_metrics,
#         "weights": {s: w for s, w in zip(strategies, weights)},
#         "currency_symbol": currency_symbol,
#         "benchmark": benchmark_ticker
#     }