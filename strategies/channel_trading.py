# channel_trading.py
"""
Channel Trading Strategy (Donchian Channel)
- Buy near the lower channel
- Sell near the upper channel
- Optional exit after fixed hold days
"""

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def get_data(ticker, start, end, interval='1d'):
    df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
    return df[['Open','High','Low','Close','Volume']]

def generate_signals(df, period=20, entry_buffer=0.002):
    df = df.copy()
    df['upper'] = df['High'].rolling(period).max().shift(1)
    df['lower'] = df['Low'].rolling(period).min().shift(1)
    df['signal'] = 0
    df['trade'] = 0
    for i in range(len(df)):
        if pd.isna(df.iloc[i]['upper']) or pd.isna(df.iloc[i]['lower']):
            continue
        price = df.iloc[i]['Close']
        if price <= df.iloc[i]['lower'] * (1 + entry_buffer):  # Buy near lower channel
            df.iat[i, df.columns.get_loc('signal')] = 1
            df.iat[i, df.columns.get_loc('trade')] = 1
        elif price >= df.iloc[i]['upper'] * (1 - entry_buffer):  # Sell near upper channel
            df.iat[i, df.columns.get_loc('signal')] = 0
            df.iat[i, df.columns.get_loc('trade')] = -1
        elif i > 0:
            df.iat[i, df.columns.get_loc('signal')] = df.iat[i-1, df.columns.get_loc('signal')]
    return df

def backtest_signals(df, hold_days=7, init_cash=100000, slippage=0, fee=0):
    df = df.copy().reset_index()
    cash = init_cash
    position = 0
    shares = 0
    trades = []
    entry_idx = None
    for i in range(len(df)-1):
        trade = df.loc[i].get('trade',0)
        next_row = df.loc[i+1]
        if trade == 1 and position == 0:  # BUY
            price = next_row['Open'] * (1 + slippage)
            shares = cash // price
            if shares:
                cash -= shares * price * (1 + fee)
                position = 1
                entry_idx = i+1
                trades.append({'date': next_row['Date'], 'type': 'BUY', 'price': price, 'shares': shares, 'cash': cash})
        if trade == -1 and position == 1:  # SELL
            price = next_row['Open'] * (1 - slippage)
            cash += shares * price * (1 - fee)
            trades.append({'date': next_row['Date'], 'type': 'SELL', 'price': price, 'shares': shares, 'cash': cash})
            shares = 0
            position = 0
            entry_idx = None
        # Optional hold-days exit
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

def plot_signals(df, trades, ticker):
    plt.figure(figsize=(12,6))
    plt.plot(df.index, df['Close'], label='Close Price', alpha=0.7)
    plt.plot(df.index, df['upper'], linestyle='--', label='Upper Channel', alpha=0.7)
    plt.plot(df.index, df['lower'], linestyle='--', label='Lower Channel', alpha=0.7)

    # mark trades
    for _, row in trades.iterrows():
        if row['type'] == 'BUY':
            plt.scatter(row['date'], row['price'], marker='^', color='green', s=100, label='BUY')
        elif row['type'] == 'SELL':
            plt.scatter(row['date'], row['price'], marker='v', color='red', s=100, label='SELL')

    plt.title(f"Channel Trading Strategy - {ticker}")
    plt.xlabel("Date")
    plt.ylabel("Price")
    plt.legend()
    plt.grid()
    plt.show()

if __name__ == "__main__":
    # Example: dynamic input
    ticker = input("Enter stock ticker (e.g., AAPL, MSFT, TSLA): ").strip().upper()
    start = input("Enter start date (YYYY-MM-DD): ").strip()
    end = input("Enter end date (YYYY-MM-DD): ").strip()

    df = get_data(ticker, start, end)
    df = generate_signals(df, period=20)
    summary, trades = backtest_signals(df)
    print(summary)
    plot_signals(df, trades, ticker)
