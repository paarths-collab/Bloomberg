# breakout.py
"""
Breakout Strategy with Plotting
- Identify horizontal resistance (recent N-day high)
- Buy when price breaks above resistance with increased volume
- Exit after fixed holding period or condition
- Plots candlesticks with signals + equity curve
"""

import yfinance as yf
import pandas as pd
import numpy as np
import argparse
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

def get_data(ticker, start, end, interval='1d'):
    df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
    return df[['Open','High','Low','Close','Volume']]

def generate_signals(df, lookback=20, volume_multiplier=1.2):
    df = df.copy()
    df['rolling_high'] = df['High'].rolling(lookback).max().shift(1)
    df['rolling_vol'] = df['Volume'].rolling(lookback).mean().shift(1)
    df['signal'] = 0
    df['trade'] = 0
    # breakout condition
    cond = (df['Close'] > df['rolling_high']) & (df['Volume'] > volume_multiplier * df['rolling_vol'])
    df.loc[cond, 'signal'] = 1
    df['trade'] = df['signal'].diff().fillna(0)
    return df

def backtest_signals(df, signal_col='signal', init_cash=100000, slippage=0, fee=0, hold_period=10):
    df = df.copy().reset_index()
    df['portfolio'] = np.nan
    position = 0
    cash = init_cash
    shares = 0
    trades = []
    for i in range(len(df)-1):
        trade = df.loc[i].get('trade',0)
        next_row = df.loc[i+1]
        if trade == 1 and position == 0:
            price = next_row['Open'] * (1 + slippage)
            shares = cash // price
            if shares:
                cash -= shares * price * (1 + fee)
                position = 1
                trades.append({'date': next_row['Date'], 'type': 'BUY', 'price': price, 'shares': shares, 'cash': cash})
        # exit rule
        if position == 1:
            entered_date = trades[-1]['date']
            idx_enter = df[df['Date'] == entered_date].index[0]
            if (i - idx_enter) >= hold_period:
                price = next_row['Open'] * (1 - slippage)
                cash += shares * price * (1 - fee)
                trades.append({'date': next_row['Date'], 'type': 'SELL', 'price': price, 'shares': shares, 'cash': cash})
                shares = 0
                position = 0
        # portfolio value tracking
        df.loc[i, 'portfolio'] = cash + shares * df.loc[i]['Close']

    final_price = df.iloc[-1]['Close']
    df.loc[len(df)-1, 'portfolio'] = cash + shares * final_price

    portfolio_value = df['portfolio'].iloc[-1]
    summary = {
        'init_cash': init_cash,
        'final_value': portfolio_value,
        'returns_pct': (portfolio_value/init_cash - 1)*100,
        'n_trades': len(trades)
    }
    return summary, pd.DataFrame(trades), df

def plot_results(df, trades, ticker):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12,8), sharex=True, gridspec_kw={'height_ratios':[3,1]})
    
    # Price + signals
    ax1.plot(df['Date'], df['Close'], label="Close Price", color="blue")
    ax1.plot(df['Date'], df['rolling_high'], label="Rolling High", color="orange", linestyle="--")
    
    # Buy/Sell markers
    for _, row in trades.iterrows():
        if row['type'] == 'BUY':
            ax1.scatter(row['date'], row['price'], marker="^", color="green", s=100, label="Buy")
        else:
            ax1.scatter(row['date'], row['price'], marker="v", color="red", s=100, label="Sell")
    
    ax1.set_title(f"Breakout Strategy on {ticker}")
    ax1.legend()

    # Equity curve
    ax2.plot(df['Date'], df['portfolio'], color="purple", label="Portfolio Value")
    ax2.set_ylabel("Portfolio ($)")
    ax2.legend()
    
    plt.xlabel("Date")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Breakout Trading Strategy")
    parser.add_argument("--ticker", type=str, required=True, help="Stock ticker (e.g., AAPL, TSLA, RELIANCE.NS)")
    parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--lookback", type=int, default=20, help="Lookback period for breakout high")
    parser.add_argument("--volume_mult", type=float, default=1.2, help="Volume multiplier for confirmation")
    parser.add_argument("--hold", type=int, default=10, help="Holding period in days")
    args = parser.parse_args()

    df = get_data(args.ticker, args.start, args.end)
    df = generate_signals(df, lookback=args.lookback, volume_multiplier=args.volume_mult)
    summary, trades, df_bt = backtest_signals(df, hold_period=args.hold)

    print("\n📊 Strategy Summary:")
    print(summary)
    print("\n📝 Trades:")
    print(trades)

    plot_results(df_bt, trades, args.ticker)
