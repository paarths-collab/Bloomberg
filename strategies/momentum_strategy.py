# 2. Momentum Strategy
# (Simple – go long if return > 0 over lookback days, else flat)
# momentum.py
import argparse
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def momentum_strategy(ticker, start, end, lookback=20, initial_capital=10000):
    df = yf.download(ticker, start=start, end=end)
    df.dropna(inplace=True)

    # Momentum signal
    df['Return_Lookback'] = df['Close'].pct_change(lookback)
    df['Signal'] = 0
    df.loc[df['Return_Lookback'] > 0, 'Signal'] = 1
    df['Position'] = df['Signal'].shift(1)

    # Returns
    df['Market_Returns'] = df['Close'].pct_change()
    df['Strategy_Returns'] = df['Position'] * df['Market_Returns']
    df['Equity_Curve'] = (1 + df['Strategy_Returns']).cumprod() * initial_capital

    return df

def plot_strategy(df, ticker):
    plt.figure(figsize=(14,7))
    plt.plot(df['Close'], label=f"{ticker} Price")
    plt.title(f"Momentum Strategy ({ticker})")
    plt.legend(); plt.grid(True); plt.show()

    plt.figure(figsize=(12,5))
    plt.plot(df['Equity_Curve'], label="Equity Curve", color="blue")
    plt.legend(); plt.grid(True); plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, required=True)
    parser.add_argument("--start", type=str, required=True)
    parser.add_argument("--end", type=str, required=True)
    parser.add_argument("--lookback", type=int, default=20)
    args = parser.parse_args()

    df = momentum_strategy(args.ticker, args.start, args.end, args.lookback)
    plot_strategy(df, args.ticker)

    total_return = df['Equity_Curve'].iloc[-1]/df['Equity_Curve'].iloc[0] - 1
    print(f"Total Return: {total_return:.2%}")
