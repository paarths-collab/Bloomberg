# support_resistance_dynamic.py
import argparse
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.signal import argrelextrema
import warnings
warnings.filterwarnings("ignore")

# --- Fetch data ---
def get_data(ticker, start, end, interval='1d'):
    df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
    return df[['Open','High','Low','Close','Volume']]

# --- Find pivot points ---
def find_pivots(df, order=5):
    highs_idx = argrelextrema(df['High'].values, np.greater_equal, order=order)[0]
    lows_idx = argrelextrema(df['Low'].values, np.less_equal, order=order)[0]
    pivot_highs = df.iloc[highs_idx]
    pivot_lows = df.iloc[lows_idx]
    return pivot_lows, pivot_highs

# --- Generate trade signals ---
def generate_signals(df, lookback=30, tolerance_pct=0.01):
    df = df.copy()
    df['signal'] = 0
    df['trade'] = 0

    for i in range(lookback, len(df)):
        window = df.iloc[i-lookback:i]
        lows, highs = find_pivots(window, order=3)
        support = lows['Low'].min() if not lows.empty else window['Low'].min()
        price = df.iloc[i]['Close']
        tol = tolerance_pct * price

        # Buy at support bounce
        if (price - support) <= tol and df.iloc[i]['Close'] > df.iloc[i]['Open']:
            df.iat[i, df.columns.get_loc('signal')] = 1
            df.iat[i, df.columns.get_loc('trade')] = 1
        elif i > 0:
            df.iat[i, df.columns.get_loc('signal')] = df.iat[i-1, df.columns.get_loc('signal')]
    return df

# --- Backtest ---
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

        # Buy
        if trade == 1 and position == 0:
            price = next_row['Open'] * (1 + slippage)
            shares = cash // price
            if shares:
                cash -= shares * price * (1 + fee)
                position = 1
                entry_idx = i+1
                trades.append({'date': next_row['Date'], 'type': 'BUY', 'price': price, 'shares': shares, 'cash': cash})

        # Sell after holding period
        if position == 1 and (i+1 - entry_idx) >= hold_days:
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

# --- Main ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, default="AAPL")
    parser.add_argument("--start", type=str, default="2019-01-01")
    parser.add_argument("--end", type=str, default="2024-01-01")
    parser.add_argument("--lookback", type=int, default=30)
    parser.add_argument("--tolerance_pct", type=float, default=0.01)
    parser.add_argument("--hold_days", type=int, default=7)
    args = parser.parse_args()

    df = get_data(args.ticker, args.start, args.end)
    df = generate_signals(df, lookback=args.lookback, tolerance_pct=args.tolerance_pct)
    summary, trades = backtest_signals(df, hold_days=args.hold_days)

    print("\n📊 Strategy Summary:", summary)
    print("\n🔑 Sample Trades:\n", trades.head())
