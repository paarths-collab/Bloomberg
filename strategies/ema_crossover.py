# ema_crossover.py
import argparse
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def ema_crossover_strategy(ticker, start, end, fast=20, slow=50, initial_capital=10000):
    # Fetch data
    df = yf.download(ticker, start=start, end=end)
    df.dropna(inplace=True)

    # Compute EMAs
    df['EMA_Fast'] = df['Close'].ewm(span=fast, adjust=False).mean()
    df['EMA_Slow'] = df['Close'].ewm(span=slow, adjust=False).mean()

    # Signals: 1 = long, 0 = flat
    df['Signal'] = 0
    df.loc[df['EMA_Fast'] > df['EMA_Slow'], 'Signal'] = 1
    df['Position'] = df['Signal'].shift(1)  # trade next bar

    # Returns
    df['Market_Returns'] = df['Close'].pct_change()
    df['Strategy_Returns'] = df['Position'] * df['Market_Returns']
    df['Equity_Curve'] = (1 + df['Strategy_Returns']).cumprod() * initial_capital

    return df


def plot_strategy(df, ticker, fast, slow):
    plt.figure(figsize=(14,7))

    # Plot price and EMAs
    plt.plot(df['Close'], label=f"{ticker} Price", alpha=0.7)
    plt.plot(df['EMA_Fast'], label=f"EMA {fast}", linestyle="--", alpha=0.8)
    plt.plot(df['EMA_Slow'], label=f"EMA {slow}", linestyle="--", alpha=0.8)

    # Buy signals
    buy_signals = df[(df['Signal'] == 1) & (df['Signal'].shift(1) == 0)]
    plt.scatter(buy_signals.index, buy_signals['Close'], marker="^", color="green", label="Buy", alpha=1)

    # Sell signals
    sell_signals = df[(df['Signal'] == 0) & (df['Signal'].shift(1) == 1)]
    plt.scatter(sell_signals.index, sell_signals['Close'], marker="v", color="red", label="Sell", alpha=1)

    plt.title(f"EMA Crossover Strategy on {ticker}")
    plt.xlabel("Date")
    plt.ylabel("Price")
    plt.legend()
    plt.grid(True)
    plt.show()

    # Plot equity curve
    plt.figure(figsize=(12,5))
    plt.plot(df['Equity_Curve'], label="Strategy Equity", color="blue")
    plt.title("Equity Curve")
    plt.xlabel("Date")
    plt.ylabel("Portfolio Value")
    plt.legend()
    plt.grid(True)
    plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EMA Crossover Trading Strategy")
    parser.add_argument("--ticker", type=str, required=True, help="Stock ticker (e.g., AAPL, TSLA)")
    parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--fast", type=int, default=20, help="Fast EMA period")
    parser.add_argument("--slow", type=int, default=50, help="Slow EMA period")
    args = parser.parse_args()

    df = ema_crossover_strategy(args.ticker, args.start, args.end, args.fast, args.slow)
    plot_strategy(df, args.ticker, args.fast, args.slow)

    # Print summary stats
    total_return = df['Equity_Curve'].iloc[-1] / df['Equity_Curve'].iloc[0] - 1
    print(f"Total Return: {total_return:.2%}")
    print(f"CAGR: {( (df['Equity_Curve'].iloc[-1]/df['Equity_Curve'].iloc[0]) ** (252/len(df)) - 1):.2%}")
    print(f"Sharpe Ratio: {np.sqrt(252) * df['Strategy_Returns'].mean() / df['Strategy_Returns'].std():.2f}")
