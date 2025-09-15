import yfinance as yf
import pandas as pd
import numpy as np
import quantstats as qs
import logging

logger = logging.getLogger(__name__)

def get_benchmark_returns(symbol: str, start: str, end: str) -> pd.Series:
    logger.info(f"Fetching benchmark data for {symbol}...")
    try:
        benchmark_data = yf.download(symbol, start=start, end=end, progress=True, auto_adjust=False)
        if benchmark_data.empty:
            logger.warning(f"No benchmark data found for {symbol}.")
            return pd.Series(dtype=float)
            
        return benchmark_data['Close'].pct_change().dropna()
        
    except Exception as e:
        logger.error(f"Failed to fetch benchmark data for {symbol}: {e}")
        return pd.Series(dtype=float)

def calculate_beta(portfolio_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    returns = pd.concat([portfolio_returns, benchmark_returns], axis=1).dropna()
    returns.columns = ['portfolio', 'benchmark']
    covariance = returns['portfolio'].cov(returns['benchmark'])
    variance = returns['benchmark'].var()
    return np.nan if variance == 0 else covariance / variance

def calculate_all_metrics(portfolio_returns: pd.Series, benchmark_returns: pd.Series) -> dict:
    retail_metrics = {
        "CAGR (%)": qs.stats.cagr(portfolio_returns) * 100,
        "Max Drawdown (%)": qs.stats.max_drawdown(portfolio_returns) * 100,
        "Sharpe Ratio": qs.stats.sharpe(portfolio_returns),
    }

    institutional_metrics = {
        "Sortino Ratio": qs.stats.sortino(portfolio_returns),
        "Calmar Ratio": qs.stats.calmar(portfolio_returns),
        "Volatility (ann.) (%)": qs.stats.volatility(portfolio_returns, annualize=True) * 100,
        "Skew": qs.stats.skew(portfolio_returns),
        "Kurtosis": qs.stats.kurtosis(portfolio_returns),
        "Value at Risk (VaR)": qs.stats.var(portfolio_returns),
        "Conditional VaR (cVaR)": qs.stats.cvar(portfolio_returns),
        "Beta (vs. Benchmark)": calculate_beta(portfolio_returns, benchmark_returns)
    }
    
    return {
        "retail": {k: round(v, 2) if isinstance(v, (int, float)) else v for k, v in retail_metrics.items()},
        "institutional": {k: round(v, 2) if isinstance(v, (int, float)) else v for k, v in institutional_metrics.items()}
    }

def generate_quantstats_report(portfolio_returns: pd.Series, benchmark_returns: pd.Series, output_file="portfolio_report.html"):
    try:
        qs.reports.html(portfolio_returns, benchmark=benchmark_returns, output=output_file, title="Portfolio Performance Report")
        logger.info(f"Successfully generated QuantStats report to {output_file}")
    except Exception as e:
        logger.error(f"Could not generate QuantStats report: {e}")
