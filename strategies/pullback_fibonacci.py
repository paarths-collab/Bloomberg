# pullback_fibonacci.py
"""
Pullback Strategy using Fibonacci retracement levels
- Detects swing high/low over lookback window
- Buys when price retraces near Fib levels (38.2%, 50%, 61.8%)
- Exits after fixed hold_days
"""

import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import argparse

def get_data(ticker, start, end, interval='1d'):
    df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
    return df[['Open', 'High', 'Low', 'Close', 'Volume']]

def generate_signals(df, lookback=50, levels=[0.382, 0.5, 0.618]):
    df = df.copy()
    df['signal'] = 0
    df['trade'] = 0
    for i in range(lookback, len(df)):
        window_df = df.iloc[i-lookback:i]
        low = window_df['Low'].min()
        high = window_df['High'].max()
        move = high - low
        if move <= 0:
            continue
        fib_levels = {lvl: high - lvl * move for lvl in levels}
        price = df.iloc[i]['Close']
        tol = 0.005 * price  # 0.5% tolerance
        for lvl, level_price in fib_levels.items():
            if abs(price - level_price) <= tol:
                df.iat[i, df.columns.get_loc('signal')] = 1
                df.iat[i, df.columns.get_loc('trade')] = 1
                break
    return df

def backtest_signals(df, hold_days=10, init_cash=100000, slippage=0, fee=0):
    df = df.copy().reset_index()
    position = 0
    cash = init_cash
    shares = 0
    trades = []
    entry_idx = None
    for i in range(len(df)-1):
        trade = df.loc[i].get('trade', 0)
        next_row = df.loc[i+1]
        if trade == 1 and position == 0:
            price = next_row['Open'] * (1 + slippage)
            shares = cash // price
            if shares:
                cash -= shares * price * (1 + fee)
                position = 1
                entry_idx = i+1
                trades.append({'date': next_row['Date'], 'type': 'BUY', 'price': price, 'shares': shares, 'cash': cash})
        if position == 1 and entry_idx is not None and (i+1 - entry_idx) >= hold_days:
            price = next_row['Open'] * (1 - slippage)
            cash += shares * price * (1 - fee)
            trades.append({'date': next_row['Date'], 'type': 'SELL', 'price': price, 'shares': shares, 'cash': cash})
            shares = 0
            position = 0
            entry_idx = None
    final_price = df.iloc[-1]['Close']
    portfolio_value = cash + shares * final_price
    summary = {
        'init_cash': init_cash,
        'final_value': portfolio_value,
        'returns_pct': (portfolio_value/init_cash - 1)*100,
        'n_trades': len(trades)
    }
    return summary, pd.DataFrame(trades)

def plot_signals(df, ticker):
    plt.figure(figsize=(12,6))
    plt.plot(df.index, df['Close'], label="Close Price", color='blue')
    plt.scatter(df.index[df['trade']==1], df['Close'][df['trade']==1], marker='^', color='green', label="Fib Buy Signal", alpha=0.8)
    plt.title(f"Pullback Fibonacci Strategy - {ticker}")
    plt.xlabel("Date")
    plt.ylabel("Price")
    plt.legend()
    plt.grid(True)
    plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pullback Fibonacci Strategy Backtest")
    parser.add_argument("--ticker", type=str, help="Stock ticker (e.g. AAPL, INFY.NS, RELIANCE.NS)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    # If not passed as arguments, ask interactively
    ticker = args.ticker or input("Enter stock ticker (e.g., AAPL or INFY.NS): ")
    start = args.start or input("Enter start date (YYYY-MM-DD): ")
    end = args.end or input("Enter end date (YYYY-MM-DD): ")

    df = get_data(ticker, start, end)
    df = generate_signals(df)
    summary, trades = backtest_signals(df)
    print("\n📊 Strategy Summary:")
    print(summary)
    print("\n🔑 Sample Trades:")
    print(trades.head())
    plot_signals(df, ticker)
