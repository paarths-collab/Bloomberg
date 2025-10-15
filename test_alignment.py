import sys
sys.path.append('.')
from utils.risk_metrics import calculate_all_metrics
import pandas as pd
import numpy as np

print('Testing calculate_all_metrics function after the fix...')

# Test 1: Normal aligned data
portfolio1 = pd.Series([0.01, 0.02, -0.01, 0.015, 0.005], index=[0, 1, 2, 3, 4])
benchmark1 = pd.Series([0.005, 0.01, -0.005, 0.01, 0.002], index=[0, 1, 2, 3, 4])
try:
    results1 = calculate_all_metrics(portfolio1, benchmark1)
    print(f'Normal aligned data: Success - Correlation: {results1["institutional"]["Correlation with Benchmark"]}')
except Exception as e:
    print(f'Normal aligned data: Error - {e}')

# Test 2: Misaligned indexes that should be handled by inner join
portfolio2 = pd.Series([0.01, 0.02, -0.01, 0.015, 0.005], index=[1, 2, 3, 4, 5])
benchmark2 = pd.Series([0.005, 0.01, -0.005, 0.01], index=[2, 3, 4, 6])  # Only indexes 2, 3, 4 overlap
try:
    results2 = calculate_all_metrics(portfolio2, benchmark2)
    print(f'Misaligned data with overlap: Success - Correlation: {results2["institutional"]["Correlation with Benchmark"]}')
except Exception as e:
    print(f'Misaligned data with overlap: Error - {e}')

# Test 3: No overlapping indexes
portfolio3 = pd.Series([0.01, 0.02, -0.01], index=[1, 2, 3])
benchmark3 = pd.Series([0.005, 0.01, -0.005], index=[4, 5, 6])  # No overlap
try:
    results3 = calculate_all_metrics(portfolio3, benchmark3)
    print(f'No overlapping data: Success - Correlation: {results3["institutional"]["Correlation with Benchmark"]}')
except Exception as e:
    print(f'No overlapping data: Error - {e}')

# Test 4: Empty series
portfolio4 = pd.Series([], dtype=float)
benchmark4 = pd.Series([], dtype=float)
try:
    results4 = calculate_all_metrics(portfolio4, benchmark4)
    print(f'Empty series: Success - Correlation: {results4["institutional"]["Correlation with Benchmark"]}')
except Exception as e:
    print(f'Empty series: Error - {e}')

# Test 5: One empty, one with data
portfolio5 = pd.Series([0.01, 0.02, -0.01], index=[0, 1, 2])
benchmark5 = pd.Series([], dtype=float)
try:
    results5 = calculate_all_metrics(portfolio5, benchmark5)
    print(f'One empty series: Success - Correlation: {results5["institutional"]["Correlation with Benchmark"]}')
except Exception as e:
    print(f'One empty series: Error - {e}')

print('All tests completed successfully!')