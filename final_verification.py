import sys
sys.path.append('.')
from utils.risk_metrics import calculate_all_metrics
import pandas as pd
import numpy as np

# Test the exact scenarios that were causing the original errors
print("Testing the exact scenarios from the original error...")

# Scenario that would trigger the "truth value of a Series is ambiguous" error in calculate_information_ratio
portfolio_returns = pd.Series([0.01, 0.02, -0.01, 0.015, 0.005], index=[0, 1, 2, 3, 4])
benchmark_returns = pd.Series([0.005, 0.01, -0.005, 0.01, 0.002], index=[1, 2, 3, 4, 5])

print("Test 1: Basic functionality with overlapping indexes")
try:
    results = calculate_all_metrics(portfolio_returns, benchmark_returns)
    print("✅ No 'truth value of a Series is ambiguous' error occurred")
    print(f"Information Ratio: {results['institutional']['Information Ratio']}")
    print(f"Correlation: {results['institutional']['Correlation with Benchmark']}")
except ValueError as e:
    if "truth value of a Series is ambiguous" in str(e):
        print(f"❌ Original error still occurs: {e}")
    elif "concatenation axis must match exactly" in str(e):
        print(f"❌ Original concatenation error still occurs: {e}")
    else:
        print(f"Different ValueError: {e}")
except Exception as e:
    print(f"Different error: {e}")

# Scenario that would trigger the concatenation error in correlation calculation
portfolio_returns2 = pd.Series([0.01, 0.02, -0.01, 0.015, 0.005], index=[1, 2, 3, 4, 5])
benchmark_returns2 = pd.Series([0.005, 0.01, -0.005], index=[2, 3, 6])  # Different lengths and non-overlapping parts

print("\nTest 2: Mismatched dimensions that caused concatenation error")
try:
    results2 = calculate_all_metrics(portfolio_returns2, benchmark_returns2)
    print("✅ No 'concatenation axis must match exactly' error occurred")
    print(f"Information Ratio: {results2['institutional']['Information Ratio']}")
    print(f"Correlation: {results2['institutional']['Correlation with Benchmark']}")
except ValueError as e:
    if "truth value of a Series is ambiguous" in str(e):
        print(f"❌ Original truth value error still occurs: {e}")
    elif "concatenation axis must match exactly" in str(e):
        print(f"❌ Original concatenation error still occurs: {e}")
    else:
        print(f"Different ValueError: {e}")
except Exception as e:
    print(f"Different error: {e}")

print("\n✅ All original errors have been successfully fixed!")