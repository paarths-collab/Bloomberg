# QuantInsights Financial Analysis Platform - Project Analysis

## Project Overview

The QuantInsights Financial Analysis Platform is an AI-enhanced financial analysis and trading strategy backtesting tool built with Streamlit. It provides a comprehensive suite of tools for market analysis, stock analysis, strategy backtesting, and AI-driven investment planning. The platform integrates multiple data sources, AI models, and financial analysis tools to provide users with a complete financial analysis environment.

## Project Structure

```
Boomerang/
├── app.py                    # Main Streamlit application entry point
├── main.py                   # Entry point that just prints greeting
├── config.py                 # Configuration file with settings and defaults
├── pyproject.toml           # Project dependencies and metadata
├── requirements.txt         # Python dependencies
├── .gitignore               # Git ignore patterns
├── .python-version          # Python version specification
├── DOCUMENTATION.md         # Strategy backtester documentation
├── QWEN.md                  # Project context file
├── README.md                # Project README
├── portfolio_report.html    # Generated portfolio report
├── final_verification.py    # Verification script for risk metrics
├── test_alignment.py        # Test script for risk metrics
├── uv.lock                  # uv package manager lock file
├── agents/                  # AI agent implementations
│   ├── analyst_agent.py
│   ├── execution_agent.py
│   ├── insider_agent.py
│   ├── llm_analyst_agent.py
│   ├── macro_agent.py
│   ├── nse_debug.json
│   ├── orchestrator.py      # Main orchestrator that coordinates all agents
│   ├── recommender_agent.py
│   ├── report_agent.py
│   ├── risk_agent.py
│   ├── screener_agent.py
│   ├── sector_agent.py
│   ├── social_media_sentiment.py
│   ├── stock_picker_agent.py
│   ├── system_health_agent.py
│   └── yfinance_agent.py
├── analytics/               # Analytics and reporting modules
│   └── pyfolio_reports.py   # Performance reporting using QuantStats
├── data/                    # Stock universe and market data files
│   ├── indian_stock_universe.parquet
│   ├── nifty500.csv
│   ├── sp500_backup.csv
│   ├── us_stock_universe.parquet
│   └── us_stocks.csv
├── pages/                   # Streamlit page components
│   ├── 1_📈_Market_Overview.py
│   ├── 2_🔬_Deep_Dive_Analysis.py
│   ├── 3_📊_Strategy_Backtester.py
│   ├── 3_🔄_Combination_Builder.py
│   ├── 4_💬_AI_Consultant.py
│   ├── 4_📈_Results.py
│   └── 5_💸_Paper_Trading.py
├── strategies/              # Trading strategy implementations
│   ├── .DS_Store
│   ├── Breakout Strategy.py
│   ├── Channel Trading.py
│   ├── Dca Investing.py
│   ├── Ema Crossover.py
│   ├── Fibonacci Pullback.py
│   ├── Macd Strategy.py
│   ├── Mean Reversion.py
│   ├── Momentum Strategy.py
│   ├── Pairs Trading.py
│   ├── Rsi Momentum.py
│   ├── Rsi Reversal.py
│   ├── Sma Crossover.py
│   ├── Support Resistance.py
│   ├── Value Investing.py
│   └── custom_strategy.py
├── utils/                   # Utility and helper functions
│   ├── __init__.py
│   ├── data_loader.py
│   ├── market_scraper.py
│   ├── market_utils.py
│   ├── moneycontrol_scraper.py
│   ├── news_fetcher.py
│   ├── portfolio_engine.py
│   ├── risk_metrics.py
│   ├── validation.py
│   └── visualization.py
└── .venv/                   # Python virtual environment (ignored)
```

## Core Architecture and File Connections

### 1. Application Entry Points

**app.py** -> **Streamlit Main Page**
- Main entry point for the application
- Contains homepage with navigation to other pages
- Connected to all other Streamlit pages in the `pages/` directory

**orchestrator.py** -> **Main Business Logic Coordinator**
- Central component that initializes and coordinates all agents
- Loads strategy modules from `strategies/` directory
- Exposes APIs to Streamlit pages for analysis
- Connected to every agent in the `agents/` directory
- Connected to utility modules in `utils/` directory

### 2. AI Agent System

**orchestrator.py** is connected to all AI agents:
- `analyst_agent.py` - Financial analysis
- `execution_agent.py` - Trade execution
- `insider_agent.py` - Insider trading analysis
- `llm_analyst_agent.py` - LLM-based analysis
- `macro_agent.py` - Macro economic analysis
- `screener_agent.py` - Stock screening
- `sector_agent.py` - Sector analysis
- `social_media_sentiment.py` - Social media sentiment analysis
- `stock_picker_agent.py` - Stock picking
- `yfinance_agent.py` - Yahoo Finance data retrieval

### 3. Streamlit Pages Architecture

**app.py** → Main page that links to:
- `pages/1_📈_Market_Overview.py` → Uses orchestrator for market overview data
- `pages/2_🔬_Deep_Dive_Analysis.py` → Uses orchestrator for deep stock analysis
- `pages/3_📊_Strategy_Backtester.py` → Uses orchestrator for strategy backtesting
- `pages/3_🔄_Combination_Builder.py` → Uses orchestrator for strategy combinations
- `pages/4_💬_AI_Consultant.py` → Uses orchestrator for AI planning
- `pages/4_📈_Results.py` → Displays results
- `pages/5_💸_Paper_Trading.py` → Uses execution agent for paper trading

### 4. Strategy System

**orchestrator.py** dynamically loads all strategy modules from the `strategies/` directory:
- `strategies/Breakout Strategy.py` → Breakout strategy implementation
- `strategies/Channel Trading.py` → Channel trading strategy
- `strategies/Dca Investing.py` → Dollar-cost averaging strategy
- `strategies/Ema Crossover.py` → EMA crossover strategy
- `strategies/Fibonacci Pullback.py` → Fibonacci pullback strategy
- `strategies/Macd Strategy.py` → MACD strategy
- `strategies/Mean Reversion.py` → Mean reversion strategy
- `strategies/Momentum Strategy.py` → Momentum strategy
- `strategies/Pairs Trading.py` → Pairs trading strategy
- `strategies/Rsi Momentum.py` → RSI momentum strategy
- `strategies/Rsi Reversal.py` → RSI reversal strategy
- `strategies/Sma Crossover.py` → SMA crossover strategy
- `strategies/Support Resistance.py` → Support/resistance strategy
- `strategies/Value Investing.py` → Value investing strategy

### 5. Data Processing and Visualization

**utils/visualization.py** → Connected to:
- Strategy backtester page for charting
- Strategy-specific visualization functions
- Dynamic chart generation based on strategy type

**utils/risk_metrics.py** → Connected to:
- Strategy backtesting for performance metrics
- Calculation of comprehensive risk metrics
- Alpha, beta, Sharpe ratio, and other financial metrics
- Used by `analytics/pyfolio_reports.py` for advanced analytics

**utils/data_loader.py** → Connected to:
- Stock data loading and preprocessing
- Market-specific data handling
- Currency symbol detection for different markets

### 6. Analytics and Reporting

**analytics/pyfolio_reports.py** → Connected to:
- Risk metrics calculations from `utils/risk_metrics.py`
- Portfolio performance reporting
- QuantStats integration for comprehensive reports

### 7. Configuration System


**config.py** → Used by:
- All agents to get API keys and settings
- Strategy backtester for default parameters
- Risk metrics for metric explanations
- UI settings and currency configurations

### 8. Data Sources

**data/** directory contains:
- `nifty500.csv` → Indian stock universe for NSE
- `us_stocks.csv` → US stock universe
- `indian_stock_universe.parquet` → Extended Indian market data
- `us_stock_universe.parquet` → Extended US market data
- Used by stock picker, screener, and data loader utilities

## Key Dependencies

The project uses several key libraries:
- **Streamlit** - For the web interface
- **yfinance** - For stock market data
- **pandas/numpy** - For data processing
- **plotly** - For interactive charts
- **QuantStats** - For performance metrics
- **OpenAI/Google Generative AI** - For AI analysis
- **Alpaca** - For paper trading

## Data Flow

1. **User Input** → Streamlit pages
2. **Pages** → Orchestrator
3. **Orchestrator** → Multiple agents and strategy modules
4. **Agents** → External APIs (Yahoo Finance, Finnhub, FRED, etc.)
5. **Strategies** → Backtesting on market data
6. **Results** → Risk metrics calculation
7. **Processed Results** → Visualization and reporting
8. **Final Output** → Web UI for user consumption

## Key Features

- **Multi-Agent AI System**: Coordinated analysis through specialized agents
- **Strategy Backtesting**: Over a dozen quantitative trading strategies
- **Market Analysis**: Global, US, and Indian market overviews
- **Deep Stock Analysis**: Multi-dimensional analysis of individual stocks
- **AI Investment Planning**: Personalized investment plans using LLMs
- **Paper Trading**: Integration with Alpaca for simulation
- **Risk Management**: Comprehensive risk metrics and analysis
- **Visualization**: Interactive charts and performance dashboards

This is a sophisticated, full-featured financial analysis platform with a modular architecture that enables comprehensive market analysis, strategy backtesting, and AI-driven investment planning.