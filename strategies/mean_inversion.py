## mean_revision (Uses Bollinger Bands – buy when price < lower band, sell when > upper band)
# mean_reversion.py
import argparse
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def mean_reversion_strategy(ticker, start, end, window=20, num_std=2, initial_capital=10000):
    df = yf.download(ticker, start=start, end=end)
    df.dropna(inplace=True)

    # Bollinger Bands
    df['MA'] = df['Close'].rolling(window).mean()
    df['STD'] = df['Close'].rolling(window).std()
    df['Upper'] = df['MA'] + num_std * df['STD']
    df['Lower'] = df['MA'] - num_std * df['STD']

    # Signals
    df['Signal'] = 0
    df.loc[df['Close'] < df['Lower'], 'Signal'] = 1   # Buy
    df.loc[df['Close'] > df['Upper'], 'Signal'] = -1  # Sell
    df['Position'] = df['Signal'].shift(1)

    # Returns
    df['Market_Returns'] = df['Close'].pct_change()
    df['Strategy_Returns'] = df['Position'] * df['Market_Returns']
    df['Equity_Curve'] = (1 + df['Strategy_Returns']).cumprod() * initial_capital

    return df

def plot_strategy(df, ticker):
    plt.figure(figsize=(14,7))
    plt.plot(df['Close'], label=f"{ticker} Price", alpha=0.7)
    plt.plot(df['Upper'], linestyle="--", label="Upper Band")
    plt.plot(df['Lower'], linestyle="--", label="Lower Band")

    buy_signals = df[df['Signal'] == 1]
    sell_signals = df[df['Signal'] == -1]
    plt.scatter(buy_signals.index, buy_signals['Close'], marker="^", color="green", label="Buy")
    plt.scatter(sell_signals.index, sell_signals['Close'], marker="v", color="red", label="Sell")

    plt.title(f"Mean Reversion Strategy ({ticker})")
    plt.legend(); plt.grid(True); plt.show()

    plt.figure(figsize=(12,5))
    plt.plot(df['Equity_Curve'], label="Equity Curve")
    plt.legend(); plt.grid(True); plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, required=True)
    parser.add_argument("--start", type=str, required=True)
    parser.add_argument("--end", type=str, required=True)
    parser.add_argument("--window", type=int, default=20)
    parser.add_argument("--num_std", type=float, default=2.0)
    args = parser.parse_args()

    df = mean_reversion_strategy(args.ticker, args.start, args.end, args.window, args.num_std)
    plot_strategy(df, args.ticker)

    total_return = df['Equity_Curve'].iloc[-1]/df['Equity_Curve'].iloc[0] - 1
    print(f"Total Return: {total_return:.2%}")
