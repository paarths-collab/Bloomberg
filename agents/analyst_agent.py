import yfinance as yf

ticker = yf.Ticker("AAPL")
recs = ticker.recommendations
print(recs.tail(5))  # Analyst ratings
