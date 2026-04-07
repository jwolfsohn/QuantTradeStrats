import pandas as pd
import numpy as np
import os
import sys

# Ensure we can import strategy.py from the parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy import classify_regime, get_target_allocation

def load_data(ticker):
    filepath = f"data/{ticker}_daily.csv"
    if not os.path.exists(filepath):
        # Fallback to relative path if run from backtest dir
        filepath = f"../data/{ticker}_daily.csv" 
    
    if not os.path.exists(filepath):
        print(f"Data file for {ticker} not found at {filepath}. Did you run fetch_data.py?")
        return None
        
    try:
        # Alpaca uses 'timestamp', yfinance uses 'Date'
        df = pd.read_csv(filepath)
        
        # Try to find date column
        date_col = next((col for col in ['timestamp', 'Date', 'date'] if col in df.columns), df.columns[0])
        df[date_col] = pd.to_datetime(df[date_col], utc=True)
        df.set_index(date_col, inplace=True)
        
        # Determine close column ('close' vs 'Close')
        close_col = 'close' if 'close' in df.columns else 'Close'
        return df[close_col]
    except Exception as e:
        print(f"Error loading {ticker}: {e}")
        return None

def main():
    print("Loading data for SPY, QQQ, TLT, BIL...")
    tickers = ["SPY", "QQQ", "TLT", "BIL"]
    data = {}
    for t in tickers:
        series = load_data(t)
        if series is None:
            return
        data[t] = series
        
    # Align data to same dates
    df = pd.DataFrame(data).dropna()
    print(f"Data loaded successfully. Date range: {df.index[0].date()} to {df.index[-1].date()}")
    
    portfolio_value = [100000] # Starting capital
    current_allocation = {"QQQ": 0, "TLT": 0, "BIL": 1.0}
    regime_history = []
    
    # Start simulating from day 200 (need 200 days for SMA)
    print("Running backtest... This may take a moment.")
    for i in range(200, len(df)):
        date = df.index[i]
        spy_prices = df["SPY"].iloc[:i+1] # All data up to today
        
        regime = classify_regime(spy_prices)
        regime_history.append((date, regime))
        target = get_target_allocation(regime)
        
        # Calculate daily P&L. i is today's close, i-1 is yesterday's close
        pnl = 0
        if i > 0:
            for ticker in ["QQQ", "TLT", "BIL"]:
                ret = (df[ticker].iloc[i] / df[ticker].iloc[i-1]) - 1
                pnl += current_allocation.get(ticker, 0) * ret
                
        new_value = portfolio_value[-1] * (1 + pnl)
        portfolio_value.append(new_value)
        
        # Update allocation for NEXT day's return
        current_allocation = target
        
    # Pad portfolio value to match dataframe length
    port_series = pd.Series([100000]*200 + portfolio_value[1:], index=df.index)
    
    # Calculate performance metrics
    total_return = (port_series.iloc[-1] / port_series.iloc[0] - 1) * 100
    
    # Benchmark return (SPY Buy & Hold over the exact same period, starting at day 200)
    spy_start = df["SPY"].iloc[200]
    spy_end = df["SPY"].iloc[-1]
    benchmark_return = (spy_end / spy_start - 1) * 100
    
    # Drawdown
    running_max = port_series.cummax()
    drawdown = (port_series / running_max) - 1
    max_dd = drawdown.min() * 100
    
    # Benchmark Drawdown
    spy_series = df["SPY"].iloc[200:]
    spy_running_max = spy_series.cummax()
    spy_drawdown = (spy_series / spy_running_max) - 1
    spy_max_dd = spy_drawdown.min() * 100
    
    # Regime stats
    regimes = pd.Series([r for _, r in regime_history])
    regime_counts = regimes.value_counts()
    
    print("\n" + "="*40)
    print("BACKTEST RESULTS (Out-of-Sample from Day 200)")
    print("="*40)
    print(f"Total Return:       {total_return:.2f}%")
    print(f"Benchmark SPY Return: {benchmark_return:.2f}%")
    print(f"Max Drawdown:       {max_dd:.2f}%")
    print(f"Benchmark SPY Max DD: {spy_max_dd:.2f}%")
    print("-" * 40)
    print("Regime Frequency:")
    for r, count in regime_counts.items():
        print(f"  {r}: {count/len(regimes)*100:.1f}%")
    print("="*40)
    
if __name__ == "__main__":
    main()
