
# macd_crossover.py
"""
MACD Crossover Strategy
- Buy when MACD line crosses above signal line
- Sell when MACD line crosses below signal line
Works for US & Indian markets (auto NSE/BSE suffix handling).
"""

import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt

# -------- Fetch Data --------
def get_data(ticker, start, end, interval='1d'):
    df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
    return df[['Open', 'High', 'Low', 'Close', 'Volume']]

# -------- Generate Signals --------
def generate_signals(df, fast=12, slow=26, signal=9):
    df = df.copy()
    df['ema_fast'] = df['Close'].ewm(span=fast, adjust=False).mean()
    df['ema_slow'] = df['Close'].ewm(span=slow, adjust=False).mean()
    df['macd'] = df['ema_fast'] - df['ema_slow']
    df['macd_signal'] = df['macd'].ewm(span=signal, adjust=False).mean()
    df['signal'] = 0
    df.loc[df['macd'] > df['macd_signal'], 'signal'] = 1
    df['trade'] = df['signal'].diff().fillna(0)
    return df

# -------- Backtesting --------
def backtest_signals(df, init_cash=100000, slippage=0, fee=0):
    df = df.copy().reset_index()
    cash, shares, position = init_cash, 0, 0
    trades = []

    for i in range(len(df) - 1):
        row, next_row = df.loc[i], df.loc[i+1]
        trade = row.get('trade', 0)

        # BUY
        if trade == 1 and position == 0:
            price = next_row['Open'] * (1 + slippage)
            shares = cash // price
            if shares > 0:
                cash -= shares * price * (1 + fee)
                position = 1
                trades.append({'date': next_row['Date'], 'type': 'BUY', 'price': price, 'shares': shares, 'cash': cash})

        # SELL
        elif trade == -1 and position == 1:
            price = next_row['Open'] * (1 - slippage)
            cash += shares * price * (1 - fee)
            trades.append({'date': next_row['Date'], 'type': 'SELL', 'price': price, 'shares': shares, 'cash': cash})
            shares, position = 0, 0

    final_price = df.iloc[-1]['Close']
    portfolio_value = cash + shares * final_price
    returns = (portfolio_value - init_cash) / init_cash

    summary = {
        'init_cash': init_cash,
        'final_value': portfolio_value,
        'returns_pct': returns * 100,
        'n_trades': len(trades)
    }
    return summary, pd.DataFrame(trades)

# -------- Visualization --------
def plot_signals(df, trades, ticker):
    plt.figure(figsize=(12, 6))
    plt.plot(df['Close'], label="Close Price", alpha=0.6)
    plt.plot(df['ema_fast'], label="EMA Fast (12)", linestyle="--", alpha=0.7)
    plt.plot(df['ema_slow'], label="EMA Slow (26)", linestyle="--", alpha=0.7)

    # Buy/Sell markers
    for _, trade in trades.iterrows():
        if trade['type'] == 'BUY':
            plt.scatter(trade['date'], trade['price'], marker="^", color="green", s=100, label="Buy Signal")
        else:
            plt.scatter(trade['date'], trade['price'], marker="v", color="red", s=100, label="Sell Signal")

    plt.title(f"MACD Crossover Strategy: {ticker}")
    plt.xlabel("Date")
    plt.ylabel("Price")
    plt.legend()
    plt.show()

# -------- Run Script --------
if __name__ == "__main__":
    ticker = input("Enter stock ticker (e.g., AAPL, RELIANCE, TCS): ").strip().upper()
    start = input("Enter start date (YYYY-MM-DD): ").strip()
    end = input("Enter end date (YYYY-MM-DD): ").strip()

    # Try NSE first if no suffix
    if "." not in ticker:
        try_ticker = ticker + ".NS"
        try:
            df = get_data(try_ticker, start, end)
            if not df.empty:
                ticker = try_ticker
            else:
                ticker = ticker + ".BO"
                df = get_data(ticker, start, end)
        except:
            ticker = ticker + ".BO"
            df = get_data(ticker, start, end)
    else:
        df = get_data(ticker, start, end)

    if df.empty:
        print(f"❌ No data found for {ticker}. Check symbol/date range.")
    else:
        df = generate_signals(df)
        summary, trades = backtest_signals(df)
        print(summary)
        plot_signals(df, trades, ticker)
