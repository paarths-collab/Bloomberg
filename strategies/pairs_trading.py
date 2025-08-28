# 3. Pairs Trading Strategy

# (Trade spread between two correlated stocks, mean-reversion on z-score)
# pairs_trading.py
import argparse
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def pairs_trading_strategy(ticker1, ticker2, start, end, lookback=30, entry_z=2, exit_z=0, initial_capital=10000):
    data = yf.download([ticker1, ticker2], start=start, end=end)['Close']
    data.dropna(inplace=True)

    # Hedge ratio by regression
    X = data[ticker2].values.reshape(-1,1)
    Y = data[ticker1].values
    beta = np.polyfit(data[ticker2], data[ticker1], 1)[0]

    # Spread
    data['Spread'] = data[ticker1] - beta * data[ticker2]
    data['Mean'] = data['Spread'].rolling(lookback).mean()
    data['STD'] = data['Spread'].rolling(lookback).std()
    data['Zscore'] = (data['Spread'] - data['Mean']) / data['STD']

    # Signals
    data['Signal'] = 0
    data.loc[data['Zscore'] > entry_z, 'Signal'] = -1  # Short spread
    data.loc[data['Zscore'] < -entry_z, 'Signal'] = 1  # Long spread
    data.loc[abs(data['Zscore']) < exit_z, 'Signal'] = 0
    data['Position'] = data['Signal'].shift(1)

    # Strategy returns (simplified: assume hedge ratio = beta)
    data['Returns'] = data['Spread'].pct_change()
    data['Strategy_Returns'] = data['Position'] * data['Returns']
    data['Equity_Curve'] = (1 + data['Strategy_Returns']).cumprod() * initial_capital

    return data, beta

def plot_strategy(df, ticker1, ticker2):
    plt.figure(figsize=(14,7))
    plt.plot(df['Spread'], label="Spread")
    plt.axhline(0, color="black", linestyle="--")
    plt.title(f"Pairs Trading Spread ({ticker1}/{ticker2})")
    plt.legend(); plt.grid(True); plt.show()

    plt.figure(figsize=(12,5))
    plt.plot(df['Equity_Curve'], label="Equity Curve", color="blue")
    plt.legend(); plt.grid(True); plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker1", type=str, required=True)
    parser.add_argument("--ticker2", type=str, required=True)
    parser.add_argument("--start", type=str, required=True)
    parser.add_argument("--end", type=str, required=True)
    parser.add_argument("--lookback", type=int, default=30)
    parser.add_argument("--entry_z", type=float, default=2.0)
    parser.add_argument("--exit_z", type=float, default=0.0)
    args = parser.parse_args()

    df, beta = pairs_trading_strategy(args.ticker1, args.ticker2, args.start, args.end, args.lookback, args.entry_z, args.exit_z)
    plot_strategy(df, args.ticker1, args.ticker2)

    total_return = df['Equity_Curve'].iloc[-1]/df['Equity_Curve'].iloc[0] - 1
    print(f"Hedge Ratio (beta): {beta:.2f}")
    print(f"Total Return: {total_return:.2%}")
