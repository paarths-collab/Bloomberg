import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, Any, List

# ===================================================================
#               STREAMLIT VISUALIZATION UTILITIES
# ===================================================================

def plot_backtest_comparison(results_df: pd.DataFrame) -> go.Figure:
    """
    Plots an interactive bar chart comparing the total returns of different backtesting strategies.
    """
    if results_df.empty or 'Return [%]' not in results_df.columns:
        return go.Figure()

    results_df['Return [%]'] = pd.to_numeric(results_df['Return [%]'], errors='coerce')
    results_df.dropna(subset=['Return [%]'], inplace=True)
    
    results_df = results_df.sort_values('Return [%]', ascending=True)
    
    colors = ['#059669' if x > 0 else '#f43f5e' for x in results_df['Return [%]']]
    
    fig = px.bar(
        results_df, 
        x='Return [%]', 
        y='Strategy', 
        color='Ticker',
        barmode='group',
        orientation='h',
        title='Strategy Performance Comparison by Ticker',
        labels={'Return [%]': 'Total Return (%)', 'Strategy': 'Strategy Name'},
        text_auto='.2f'
    )
    fig.update_traces(marker_color=colors, textposition='outside')
    fig.update_layout(yaxis={'categoryorder':'total ascending'})
    return fig

def create_price_and_equity_chart(backtest_df: pd.DataFrame, trades: List[Dict[str, Any]], ticker: str, strategy_name: str, currency_symbol: str = "$") -> go.Figure:
    """
    Creates a professional, multi-layered chart showing price, signals, and equity curve with dynamic currency.
    """
    if backtest_df.empty:
        return go.Figure()

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Candlestick(
            x=backtest_df.index,
            open=backtest_df['Open'],
            high=backtest_df['High'],
            low=backtest_df['Low'],
            close=backtest_df['Close'],
            name=f'{ticker} Price'
        ),
        secondary_y=False,
    )

    if 'Equity' in backtest_df.columns:
        fig.add_trace(
            go.Scatter(
                x=backtest_df.index, y=backtest_df['Equity'], 
                name='Equity Curve', line=dict(color='purple', dash='dot')
            ),
            secondary_y=True,
        )

    trades_df = pd.DataFrame(trades)
    if not trades_df.empty:
        buy_signals = trades_df[trades_df['type'] == 'BUY']
        sell_signals = trades_df[trades_df['type'] == 'SELL']
        fig.add_trace(
            go.Scatter(
                x=buy_signals['date'], y=buy_signals['price'], mode='markers', 
                name='Buy Signal', marker=dict(color='#059669', size=10, symbol='triangle-up')
            ),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(
                x=sell_signals['date'], y=sell_signals['price'], mode='markers', 
                name='Sell Signal', marker=dict(color='#f43f5e', size=10, symbol='triangle-down')
            ),
            secondary_y=False,
        )

    fig.update_layout(
        title_text=f"{ticker} Backtest: {strategy_name}",
        xaxis_title="Date",
        yaxis_title=f"Price ({currency_symbol})",
        yaxis2_title=f"Equity ({currency_symbol})",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.update_xaxes(rangeslider_visible=False)
    
    return fig


# import pandas as pd
# import plotly.express as px
# import plotly.graph_objects as go
# from plotly.subplots import make_subplots
# from typing import Dict, Any, List

# # ===================================================================
# #                 STREAMLIT VISUALIZATION UTILITIES
# # ===================================================================

# def plot_backtest_comparison(results_df: pd.DataFrame) -> go.Figure:
#     """
#     Plots an interactive bar chart comparing the total returns of different backtesting strategies.
#     """
#     if results_df.empty or 'Total Return %' not in results_df.columns:
#         return go.Figure()

#     # Ensure the return column is numeric for proper sorting and coloring
#     results_df['Total Return %'] = pd.to_numeric(results_df['Total Return %'], errors='coerce')
#     results_df.dropna(subset=['Total Return %'], inplace=True)
    
#     results_df = results_df.sort_values('Total Return %', ascending=True)
    
#     # Assign colors based on performance
#     colors = ['#059669' if x > 0 else '#f43f5e' for x in results_df['Total Return %']]
    
#     fig = px.bar(
#         results_df, 
#         x='Total Return %', 
#         y='Strategy', 
#         color='Ticker',
#         barmode='group',
#         orientation='h',
#         title='Strategy Performance Comparison by Ticker',
#         labels={'Total Return %': 'Total Return (%)', 'Strategy': 'Strategy Name'},
#         text_auto='.2f' # Display the value on the bar
#     )
#     fig.update_traces(marker_color=colors, textposition='outside')
#     fig.update_layout(yaxis={'categoryorder':'total ascending'})
#     return fig

# def plot_historical_metrics(df: pd.DataFrame, x_col: str, y_cols: List[str], title: str, chart_type: str = 'bar') -> go.Figure:
#     """
#     Generic function to plot historical data from a DataFrame.
#     """
#     if df.empty or x_col not in df.columns or not all(y in df.columns for y in y_cols):
#         return go.Figure()

#     if chart_type == 'bar':
#         fig = px.bar(df, x=x_col, y=y_cols, title=title, barmode='group')
#     else: # Default to line chart
#         fig = px.line(df, x=x_col, y=y_cols, title=title, markers=True)
    
#     return fig

# def create_price_and_equity_chart(backtest_df: pd.DataFrame, trades: List[Dict[str, Any]], ticker: str, strategy_name: str) -> go.Figure:
#     """
#     Creates a professional, multi-layered chart showing price, signals, indicators, and equity curve.
#     """
#     if backtest_df.empty:
#         return go.Figure()

#     # Create figure with a secondary y-axis
#     fig = make_subplots(specs=[[{"secondary_y": True}]])

#     # Add Price Candlestick Trace
#     fig.add_trace(
#         go.Candlestick(
#             x=backtest_df.index,
#             open=backtest_df['Open'],
#             high=backtest_df['High'],
#             low=backtest_df['Low'],
#             close=backtest_df['Close'],
#             name=f'{ticker} Price'
#         ),
#         secondary_y=False,
#     )

#     # Add Equity Curve Trace on the secondary axis
#     if 'equity' in backtest_df.columns:
#         fig.add_trace(
#             go.Scatter(
#                 x=backtest_df.index, y=backtest_df['equity'], 
#                 name='Equity Curve', line=dict(color='purple', dash='dot')
#             ),
#             secondary_y=True,
#         )

#     # Add Buy/Sell Markers from the trades list
#     trades_df = pd.DataFrame(trades)
#     if not trades_df.empty:
#         buy_signals = trades_df[trades_df['type'] == 'BUY']
#         sell_signals = trades_df[trades_df['type'] == 'SELL']
#         fig.add_trace(
#             go.Scatter(
#                 x=buy_signals['date'], y=buy_signals['price'], mode='markers', 
#                 name='Buy Signal', marker=dict(color='#059669', size=10, symbol='triangle-up')
#             ),
#             secondary_y=False,
#         )
#         fig.add_trace(
#             go.Scatter(
#                 x=sell_signals['date'], y=sell_signals['price'], mode='markers', 
#                 name='Sell Signal', marker=dict(color='#f43f5e', size=10, symbol='triangle-down')
#             ),
#             secondary_y=False,
#         )

#     # Update layout
#     fig.update_layout(
#         title_text=f"{ticker} Backtest: {strategy_name}",
#         xaxis_title="Date",
#         yaxis_title="Price ($)",
#         yaxis2_title="Equity ($)",
#         legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
#     )
#     fig.update_xaxes(rangeslider_visible=False)
    
#     return fig