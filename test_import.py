import sys
import os

# Add current dir to path
sys.path.append(os.getcwd())

try:
    print("Attempting to import utils.portfolio_engine...")
    import utils.portfolio_engine
    print(f"Module imported: {utils.portfolio_engine}")
    
    print("Attributes in module:", dir(utils.portfolio_engine))
    
    from utils.portfolio_engine import PortfolioEngine
    print("Success! Imported PortfolioEngine class.")
except Exception as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()
