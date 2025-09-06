import re
import logging
from typing import Dict, Any, Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def setup_driver() -> webdriver.Chrome:
    """Initializes and returns a headless Chrome WebDriver instance."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Ensures the browser UI doesn't pop up
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Automatically downloads and manages the correct driver version
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def scrape_indian_market_data() -> Dict[str, Any]:
    """
    Scrapes key Indian market indicators from Moneycontrol using Selenium.
    """
    url = 'https://www.moneycontrol.com/indian-markets'
    driver = setup_driver()
    
    try:
        logger.info(f"Navigating to {url} with Selenium...")
        driver.get(url)
        
        # Use BeautifulSoup to parse the fully rendered page source
        soup = BeautifulSoup(driver.page_source, 'lxml')

        # --- Helper function to find and clean data from market widgets ---
        def get_market_data(index_id: str) -> Dict[str, float]:
            value_str: Optional[str] = "0"
            change_str: Optional[str] = "0"

            try:
                base_selector = f'#{index_id}'
                value_tag = soup.select_one(f'{base_selector} .lastprice')
                change_tag = soup.select_one(f'{base_selector} .change')
                
                if value_tag:
                    value_str = value_tag.get_text(strip=True)
                if change_tag:
                    change_str = change_tag.get_text(strip=True)

            except AttributeError as e:
                logger.warning(f"Could not find market data for ID {index_id}: {e}")

            # Clean the strings to get pure numbers
            value_float = float(re.sub(r'[^\d.]', '', value_str or "0"))
            change_float = float(re.sub(r'[^\d.-]', '', change_str or "0"))
            
            return {"value": value_float, "change": change_float}

        # --- Scrape Nifty 50 and Sensex ---
        nifty_data = get_market_data("market_NIFTY")
        sensex_data = get_market_data("market_SENSEX")

        # --- Scrape Advances / Declines for Market Breadth ---
        advances = 0
        declines = 0
        try:
            advances_tag = soup.select_one('#nse_advance .adv')
            declines_tag = soup.select_one('#nse_advance .dec')
            
            if advances_tag:
                advances = int(advances_tag.get_text(strip=True))
            if declines_tag:
                declines = int(declines_tag.get_text(strip=True))
        except (TypeError, ValueError) as e:
             logger.warning(f"Could not parse advances/declines data: {e}")

        adv_dec_ratio = round(advances / declines, 2) if declines > 0 else "N/A"

        return {
            "Nifty 50": nifty_data["value"],
            "Nifty 50 Change": nifty_data["change"],
            "Sensex": sensex_data["value"],
            "Sensex Change": sensex_data["change"],
            "Advances": advances,
            "Declines": declines,
            "Advance/Decline Ratio": adv_dec_ratio
        }

    except Exception as e:
        logger.error(f"Failed to scrape Moneycontrol market data: {e}")
        return {"Error": f"An error occurred: {e}"}
    finally:
        # Ensure the browser is closed to free up resources
        driver.quit()

# --- Example of how to use the function ---
if __name__ == "__main__":
    market_data = scrape_indian_market_data()
    if "Error" not in market_data:
        print("\n--- Live Indian Market Data ---")
        for key, value in market_data.items():
            print(f"{key:<25}: {value}")
        print("-----------------------------")
    else:
        print(f"\nFailed to retrieve data: {market_data['Error']}")

# import requests
# from bs4 import BeautifulSoup
# import re
# import logging

# logger = logging.getLogger(__name__)

# def scrape_indian_market_data():
#     """
#     Scrapes the main Indian market page on Moneycontrol for key indicators.
#     """
#     url = 'https://www.moneycontrol.com/indian-markets'
#     headers = {'User-Agent': 'Mozilla/5.0'}
    
#     try:
#         response = requests.get(url, headers=headers, timeout=15)
#         response.raise_for_status()
#         soup = BeautifulSoup(response.text, 'lxml')

#         # --- Helper function to find and clean data from market widgets ---
#         def get_market_data(index_id):
#             base_selector = f'#{index_id}'
#             value_tag = soup.select_one(f'{base_selector} .lastprice')
#             change_tag = soup.select_one(f'{base_selector} .change')
            
#             value_str = value_tag.get_text(strip=True) if value_tag else "0"
#             change_str = change_tag.get_text(strip=True) if change_tag else "0"
            
#             # Clean the strings to get pure numbers
#             value_float = float(re.sub(r'[^\d.]', '', value_str))
#             change_float = float(re.sub(r'[^\d.-]', '', change_str))
            
#             return {"value": value_float, "change": change_float}

#         # --- Scrape Nifty 50 and Sensex ---
#         nifty_data = get_market_data("market_NIFTY")
#         sensex_data = get_market_data("market_SENSEX")

#         # --- Scrape Advances / Declines for Market Breadth ---
#         advances = 0
#         declines = 0
#         advances_tag = soup.select_one('#nse_advance .adv')
#         declines_tag = soup.select_one('#nse_advance .dec')
        
#         if advances_tag:
#             advances = int(advances_tag.get_text(strip=True))
#         if declines_tag:
#             declines = int(declines_tag.get_text(strip=True))
            
#         adv_dec_ratio = round(advances / declines, 2) if declines > 0 else "N/A"

#         return {
#             "Nifty 50": nifty_data["value"],
#             "Nifty 50 Change": nifty_data["change"],
#             "Sensex": sensex_data["value"],
#             "Sensex Change": sensex_data["change"],
#             "Advances": advances,
#             "Declines": declines,
#             "Advance/Decline Ratio": adv_dec_ratio
#         }

#     except Exception as e:
#         logger.error(f"Error scraping Moneycontrol market data: {e}")
#         return {"Error": f"Failed to scrape Moneycontrol: {e}"}

