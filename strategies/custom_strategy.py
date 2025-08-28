# custom_strategy.py
import argparse
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt

def generate_signals(df):
    """
    Define your custom entry/exit rules here.
    Example: RSI + SMA filter
    """
    # SMA filter
    df['SMA_50'] = df['Close'].rolling(50).mean()
    df['SMA_200'] = df['Close'].rolling(200).mean()

    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # Signal rules:
    df['Signal'] = 0
    df.loc[(df['RSI'] < 30) & (df['Close'] > df['SMA_50']), 'Signal'] = 1   # Buy
    df.loc[(df['RSI'] > 70) & (df['Close'] < df['SMA_50']), 'Signal'] = -1  # Sell

    return df

def custom_strategy(ticker, start, end, initial_capital=10000):
    df = yf.download(ticker, start=start, end=end)
    df.dropna(inplace=True)

    df = generate_signals(df)
    df['Position'] = df['Signal'].shift(1)

    # Returns
    df['Market_Returns'] = df['Close'].pct_change()
    df['Strategy_Returns'] = df['Position'] * df['Market_Returns']
    df['Equity_Curve'] = (1 + df['Strategy_Returns']).cumprod() * initial_capital

    return df

def plot_strategy(df, ticker):
    plt.figure(figsize=(14,7))
    plt.plot(df['Close'], label=f"{ticker} Price", alpha=0.7)

    buy_signals = df[df['Signal'] == 1]
    sell_signals = df[df['Signal'] == -1]
    plt.scatter(buy_signals.index, buy_signals['Close'], marker="^", color="green", label="Buy")
    plt.scatter(sell_signals.index, sell_signals['Close'], marker="v", color="red", label="Sell")

    plt.title(f"Custom Strategy ({ticker})")
    plt.legend(); plt.grid(True); plt.show()

    plt.figure(figsize=(12,5))
    plt.plot(df['Equity_Curve'], label="Equity Curve", color="blue")
    plt.legend(); plt.grid(True); plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, required=True)
    parser.add_argument("--start", type=str, required=True)
    parser.add_argument("--end", type=str, required=True)
    args = parser.parse_args()

    df = custom_strategy(args.ticker, args.start, args.end)
    plot_strategy(df, args.ticker)

    total_return = df['Equity_Curve'].iloc[-1]/df['Equity_Curve'].iloc[0] - 1
    print(f"Total Return: {total_return:.2%}")
