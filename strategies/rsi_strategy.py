# rsi_momentum_plot.py
import argparse
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# --- Fetch data ---
def get_data(ticker, start, end, interval='1d'):
    df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
    return df[['Open','High','Low','Close','Volume']]

# --- RSI computation ---
def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).fillna(0)
    loss = -delta.clip(upper=0).fillna(0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

# --- Generate signals ---
def generate_signals(df, rsi_period=14, lower=40, upper=60, momentum_filter=True):
    df = df.copy()
    df['rsi'] = compute_rsi(df['Close'], rsi_period)
    df['ma20'] = df['Close'].rolling(20).mean()
    df['signal'] = 0
    df['trade'] = 0

    for i in range(1, len(df)):
        # RSI crosses above lower threshold -> buy
        if df.loc[df.index[i-1], 'rsi'] < lower and df.loc[df.index[i], 'rsi'] >= lower:
            if not momentum_filter or df.loc[df.index[i], 'Close'] > df.loc[df.index[i], 'ma20']:
                df.at[df.index[i], 'trade'] = 1
                df.at[df.index[i], 'signal'] = 1
        # RSI crosses below upper threshold -> sell
        elif df.loc[df.index[i-1], 'rsi'] > upper and df.loc[df.index[i], 'rsi'] <= upper:
            df.at[df.index[i], 'trade'] = -1
            df.at[df.index[i], 'signal'] = 0
        else:
            df.at[df.index[i], 'signal'] = df.at[df.index[i-1], 'signal']
    return df

# --- Backtest ---
def backtest_signals(df, init_cash=100000, slippage=0, fee=0):
    df = df.copy().reset_index()
    position = 0
    cash = init_cash
    shares = 0
    trades = []

    for i in range(len(df)-1):
        trade = df.loc[i].get('trade', 0)
        next_row = df.loc[i+1]
        if trade == 1 and position == 0:
            price = next_row['Open'] * (1 + slippage)
            shares = cash // price
            if shares:
                cash -= shares * price * (1 + fee)
                position = 1
                trades.append({'date': next_row['Date'], 'type': 'BUY', 'price': price, 'shares': shares, 'cash': cash})
        elif trade == -1 and position == 1:
            price = next_row['Open'] * (1 - slippage)
            cash += shares * price * (1 - fee)
            trades.append({'date': next_row['Date'], 'type': 'SELL', 'price': price, 'shares': shares, 'cash': cash})
            shares = 0
            position = 0

    final_price = df.iloc[-1]['Close']
    portfolio_value = cash + shares * final_price
    summary = {
        'init_cash': init_cash,
        'final_value': portfolio_value,
        'returns_pct': (portfolio_value/init_cash - 1)*100,
        'n_trades': len(trades)
    }
    return summary, pd.DataFrame(trades)

# --- Plot ---
def plot_signals(df, ticker, lower=40, upper=60):
    plt.figure(figsize=(14, 8))

    # Price chart
    plt.subplot(2,1,1)
    plt.plot(df['Close'], label='Close Price', color='blue')
    plt.scatter(df.index[df['trade']==1], df['Close'][df['trade']==1], marker='^', color='green', s=100, label='Buy')
    plt.scatter(df.index[df['trade']==-1], df['Close'][df['trade']==-1], marker='v', color='red', s=100, label='Sell')
    plt.title(f"{ticker} Price & RSI Momentum Signals")
    plt.legend()

    # RSI chart
    plt.subplot(2,1,2)
    plt.plot(df['rsi'], label='RSI', color='orange')
    plt.axhline(upper, color='red', linestyle='--', label=f'RSI Upper ({upper})')
    plt.axhline(lower, color='green', linestyle='--', label=f'RSI Lower ({lower})')
    plt.title("RSI")
    plt.legend()

    plt.tight_layout()
    plt.show()

# --- Main ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, default="TSLA")
    parser.add_argument("--start", type=str, default="2019-01-01")
    parser.add_argument("--end", type=str, default="2024-01-01")
    parser.add_argument("--rsi_lower", type=float, default=40)
    parser.add_argument("--rsi_upper", type=float, default=60)
    parser.add_argument("--momentum_filter", type=bool, default=True)
    args = parser.parse_args()

    df = get_data(args.ticker, args.start, args.end)
    df = generate_signals(df, lower=args.rsi_lower, upper=args.rsi_upper, momentum_filter=args.momentum_filter)
    summary, trades = backtest_signals(df)

    print("\n📊 Strategy Summary:", summary)
    print("\n🔑 Sample Trades:\n", trades.head())
    plot_signals(df, args.ticker, lower=args.rsi_lower, upper=args.rsi_upper)
