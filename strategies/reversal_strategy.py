import argparse
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# --- RSI Computation ---
def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

# --- Get stock data ---
def get_data(ticker, start, end):
    df = yf.download(ticker, start=start, end=end)
    df.dropna(inplace=True)
    return df

# --- Divergence detection ---
def detect_divergence(df, window=30):
    df = df.copy()
    df['rsi'] = compute_rsi(df['Close'])
    df['signal'] = 0
    df['trade'] = 0

    for i in range(window, len(df)):
        sub = df.iloc[i-window:i]

        # Bullish divergence
        lows = sub['Close'].nsmallest(2)
        if len(lows) == 2:
            idx1, idx2 = lows.index[0], lows.index[1]
            if sub.loc[idx2, 'Close'] < sub.loc[idx1, 'Close'] and sub.loc[idx2, 'rsi'] > sub.loc[idx1, 'rsi']:
                df.at[df.index[i], 'trade'] = 1
                df.at[df.index[i], 'signal'] = 1

        # Bearish divergence
        highs = sub['Close'].nlargest(2)
        if len(highs) == 2:
            idx1, idx2 = highs.index[0], highs.index[1]
            if sub.loc[idx2, 'Close'] > sub.loc[idx1, 'Close'] and sub.loc[idx2, 'rsi'] < sub.loc[idx1, 'rsi']:
                df.at[df.index[i], 'trade'] = -1
                df.at[df.index[i], 'signal'] = -1
    return df

# --- Backtest simple strategy ---
def backtest_signals(df):
    df = df.copy()
    df['position'] = df['trade'].replace(0, np.nan).ffill().fillna(0)
    df['returns'] = df['Close'].pct_change() * df['position'].shift()
    total_return = df['returns'].sum()
    trades = df[df['trade'] != 0]
    summary = {'Total Return': total_return, 'Trades': len(trades)}
    return summary, trades

# --- Plot results ---
def plot_signals(df, ticker):
    plt.figure(figsize=(14, 8))

    # Price chart
    plt.subplot(2, 1, 1)
    plt.plot(df['Close'], label='Close Price')
    plt.scatter(df.index[df['trade'] == 1], df['Close'][df['trade'] == 1], marker='^', color='green', label='Buy', s=100)
    plt.scatter(df.index[df['trade'] == -1], df['Close'][df['trade'] == -1], marker='v', color='red', label='Sell', s=100)
    plt.title(f"{ticker} Price & Divergence Signals")
    plt.legend()

    # RSI chart
    plt.subplot(2, 1, 2)
    plt.plot(df['rsi'], label='RSI', color='orange')
    plt.axhline(70, color='red', linestyle='--')
    plt.axhline(30, color='green', linestyle='--')
    plt.title('RSI')
    plt.legend()

    plt.tight_layout()
    plt.show()

# --- Main ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, default="AAPL")
    parser.add_argument("--start", type=str, default="2019-01-01")
    parser.add_argument("--end", type=str, default="2024-01-01")
    parser.add_argument("--window", type=int, default=30)
    args = parser.parse_args()

    df = get_data(args.ticker, args.start, args.end)
    df = detect_divergence(df, window=args.window)
    summary, trades = backtest_signals(df)

    print("\n📊 Strategy Summary:", summary)
    print("\n🔑 Sample Trades:\n", trades.head())

    plot_signals(df, args.ticker)
