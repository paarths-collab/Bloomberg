from fredapi import Fred
fred = Fred(api_key="YOUR_API_KEY")
cpi = fred.get_series("CPIAUCNS")  # US CPI
print(cpi.tail())
