import re
import logging
from typing import Dict, Any, Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# --- Logging configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Helper Functions ---
def setup_driver() -> webdriver.Chrome:
    """
    Initializes a headless Chrome WebDriver using selenium and ChromeDriverManager.
    """
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run Chrome in the background
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def clean_numeric(text: Optional[str]) -> Optional[str]:
    """
    Removes non-numeric characters from a string, keeping decimal points.
    """
    if text is None:
        return None
    return re.sub(r"[^\d.]", "", text)

# --- Scraper Function ---
# In utils/moneycontrol_scraper.py

def scrape_moneycontrol_data(moneycontrol_url: str) -> Dict[str, Any]:
    """
    Scrapes key financial data from a Moneycontrol URL using Selenium.
    This version uses the latest selectors for the current website structure.
    """
    driver = setup_driver()
    scraped_data: Dict[str, Any] = {"url": moneycontrol_url}
    
    try:
        logging.info(f"Fetching {moneycontrol_url} with Selenium...")
        driver.get(moneycontrol_url)
        driver.implicitly_wait(5)
        
        soup = BeautifulSoup(driver.page_source, 'lxml')

        def get_value(selector: str, clean_fn=None) -> Optional[str]:
            element = soup.select_one(selector)
            if element:
                value = element.get_text(strip=True)
                return clean_fn(value) if clean_fn else value
            logging.warning(f"Selector '{selector}' not found on page {moneycontrol_url}")
            return None

        # --- LATEST, MOST RELIABLE SELECTOR ---
        scraped_data['nse_price'] = get_value('#Nse_Prc_tick > strong', clean_numeric)
        scraped_data['bse_price'] = get_value('#Bse_Prc_tick > strong', clean_numeric)
        
        market_stats = { 'market_cap_cr': "Market Cap (Cr.)", 'pe_ratio': "P/E", 'book_value_inr': "Book Value (Rs)", 'dividend_yield_pct': "Div (%)", 'industry_pe': "Ind P/E" }

        for key, label in market_stats.items():
            try:
                label_element = soup.find('div', class_='text_1', string=re.compile(label, re.I))
                if label_element:
                    value_element = label_element.find_next_sibling('div', class_='text_2')
                    scraped_data[key] = clean_numeric(value_element.get_text(strip=True))
            except AttributeError:
                logging.warning(f"Could not find '{label}' for {moneycontrol_url}")
                scraped_data[key] = None
        
        return scraped_data

    except Exception as e:
        logging.error(f"An error occurred during scraping: {e}")
        return {"error": str(e)}
    finally:
        driver.quit()
# import requests
# from bs4 import BeautifulSoup
# import pandas as pd
# import re
# import logging

# # ... inside the function ...


# def scrape_moneycontrol_data(moneycontrol_url: str) -> dict:
#     """
#     Scrapes key financial data for a stock from its Moneycontrol URL.

#     Args:
#         moneycontrol_url: The full URL to the stock's page on Moneycontrol.
#                           e.g., 'https://www.moneycontrol.com/india/stockpricequote/computers-software/infosys/IT'

#     Returns:
#         A dictionary containing the scraped financial data.
#     """
#     scraped_data = {"url": moneycontrol_url}
    
#     try:
#         # Set headers to mimic a real browser visit
#         headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
#         response = requests.get(moneycontrol_url, headers=headers, timeout=15)
#         response.raise_for_status()  # Will raise an exception for bad status codes (4xx or 5xx)

#         soup = BeautifulSoup(response.text, 'lxml')

#         # --- Helper function to safely extract and clean data ---
#         def get_value_from_id(element_id, clean_fn=None):
#             element = soup.find(id=element_id)
#             if element:
#                 value = element.get_text(strip=True)
#                 return clean_fn(value) if clean_fn else value
#             return 'N/A'

#         def clean_numeric(text):
#             return re.sub(r'[^\d.]', '', text)

#         # --- Scraping Key Data Points using known IDs from Moneycontrol ---
#         scraped_data['nse_price'] = get_value_from_id('nsecp', clean_numeric)
#         scraped_data['bse_price'] = get_value_from_id('bsecp', clean_numeric)
        
#         # Find the main market stats table
#         market_stats_div = soup.find('div', class_='market_stats')
#         if market_stats_div:
#             # Find all the rows in the stats table
#             rows = market_stats_div.find_all('div', class_='FR')
#             for row in rows:
#                 label_elem = row.find('div', class_='text_1')
#                 value_elem = row.find('div', class_='text_2')
#                 if label_elem and value_elem:
#                     label = label_elem.get_text(strip=True).lower()
#                     value = value_elem.get_text(strip=True)
                    
#                     if 'market cap' in label:
#                         scraped_data['market_cap_cr'] = clean_numeric(value)
#                     elif 'p/e' in label:
#                         scraped_data['pe_ratio'] = clean_numeric(value)
#                     elif 'book value' in label:
#                         scraped_data['book_value_inr'] = clean_numeric(value)
#                     elif 'dividend' in label:
#                         scraped_data['dividend_yield_pct'] = clean_numeric(value)
#                     elif 'industry p/e' in label:
#                         scraped_data['industry_pe'] = clean_numeric(value)
        
#         return scraped_data

#    except requests.exceptions.RequestException as e:
#         logging.error(f"Error fetching URL {moneycontrol_url}: {e}")
#     # ...
#     except Exception as e:
#         logging.error(f"An error occurred during scraping: {e}")

# # --- Example of how to use the function ---
# if __name__ == "__main__":
#     # URL for Infosys on Moneycontrol
#     infy_url = 'https://www.moneycontrol.com/india/stockpricequote/computers-software/infosys/IT'
    
#     print(f"Scraping data for Infosys from: {infy_url}")
#     data = scrape_moneycontrol_data(infy_url)
    
#     # Print the results in a readable format
#     if "error" not in data:
#         print("\n--- Scraped Data ---")
#         for key, value in data.items():
#             print(f"{key.replace('_', ' ').title():<20}: {value}")
#         print("--------------------")
#     else:
#         print(f"\nFailed to scrape data: {data['error']}")
