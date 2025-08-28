# ma_crossover.py
import argparse
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt

def ma_crossover_strategy(ticker, start, end, short_window=50, long_window=200, initial_capital=10000):
    df = yf.download(ticker, start=start, end=end)
    df.dropna(inplace=True)

    # Moving averages
    df['SMA_Short'] = df['Close'].rolling(short_window).mean()
    df['SMA_Long'] = df['Close'].rolling(long_window).mean()

    # Signals
    df['Signal'] = 0
    df.loc[df['SMA_Short'] > df['SMA_Long'], 'Signal'] = 1
    df.loc[df['SMA_Short'] < df['SMA_Long'], 'Signal'] = -1
    df['Position'] = df['Signal'].shift(1)

    # Returns
    df['Market_Returns'] = df['Close'].pct_change()
    df['Strategy_Returns'] = df['Position'] * df['Market_Returns']
    df['Equity_Curve'] = (1 + df['Strategy_Returns']).cumprod() * initial_capital

    return df

def plot_strategy(df, ticker):
    plt.figure(figsize=(14,7))
    plt.plot(df['Close'], label=f"{ticker} Price", alpha=0.7)
    plt.plot(df['SMA_Short'], label="Short SMA", color="green")
    plt.plot(df['SMA_Long'], label="Long SMA", color="red")

    buy_signals = df[(df['Signal'] == 1) & (df['Position'].shift(1) == -1)]
    sell_signals = df[(df['Signal'] == -1) & (df['Position'].shift(1) == 1)]

    plt.scatter(buy_signals.index, buy_signals['Close'], marker="^", color="green", label="Buy")
    plt.scatter(sell_signals.index, sell_signals['Close'], marker="v", color="red", label="Sell")

    plt.title(f"MA Crossover Strategy ({ticker})")
    plt.legend(); plt.grid(True); plt.show()

    plt.figure(figsize=(12,5))
    plt.plot(df['Equity_Curve'], label="Equity Curve", color="blue")
    plt.legend(); plt.grid(True); plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, required=True)
    parser.add_argument("--start", type=str, required=True)
    parser.add_argument("--end", type=str, required=True)
    parser.add_argument("--short", type=int, default=50)
    parser.add_argument("--long", type=int, default=200)
    args = parser.parse_args()

    df = ma_crossover_strategy(args.ticker, args.start, args.end, args.short, args.long)
    plot_strategy(df, args.ticker)

    total_return = df['Equity_Curve'].iloc[-1]/df['Equity_Curve'].iloc[0] - 1
    print(f"Total Return: {total_return:.2%}")
