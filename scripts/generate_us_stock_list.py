# File: scripts/generate_us_stock_list.py

import pandas as pd
import requests
from pathlib import Path
from io import StringIO

def fetch_sp500_tickers_and_save():
    """
    Scrapes the list of S&P 500 companies from Wikipedia, formats it,
    and saves it to a CSV file in the 'data' directory.
    Columns: Company Name, Industry, Symbol
    """
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    project_root = Path(__file__).parent.parent
    output_path = project_root / "data" / "us_stocks.csv"
    backup_path = project_root / "data" / "sp500_backup.csv"

    try:
        print("🌐 Fetching S&P 500 constituents from Wikipedia...")
        html = requests.get(url, headers=headers).text
        tables = pd.read_html(StringIO(html))   # ✅ no FutureWarning
        sp500_df = tables[0].copy()             # ✅ prevents SettingWithCopyWarning

        # --- Keep only relevant columns ---
        sp500_df = sp500_df[['Security', 'GICS Sector', 'Symbol']].copy()
        sp500_df.rename(columns={
            'Security': 'Company Name',
            'GICS Sector': 'Industry'
        }, inplace=True)

        # Fix ticker symbols (BRK.B → BRK-B)
        sp500_df['Symbol'] = sp500_df['Symbol'].str.replace('.', '-', regex=False)

        # Save cleaned data
        sp500_df.to_csv(output_path, index=False)
        print(f"✅ Successfully saved {len(sp500_df)} S&P 500 stock symbols to '{output_path}'")

        # Save a backup copy
        sp500_df.to_csv(backup_path, index=False)

    except Exception as e:
        print(f"❌ An error occurred: {e}")
        if backup_path.exists():
            print(f"⚠️ Loading from local backup: {backup_path}")
            sp500_df = pd.read_csv(backup_path)
            sp500_df.to_csv(output_path, index=False)
            print(f"✅ Backup list copied to '{output_path}'")
        else:
            print("❌ No backup file found. Please provide a static CSV in /data.")

if __name__ == "__main__":
    fetch_sp500_tickers_and_save()
