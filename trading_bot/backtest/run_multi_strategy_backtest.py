import pandas as pd
import numpy as np
import os
import sys
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy import get_daily_macro_allocation, get_hourly_statarb_allocation

def main():
    print("Fetching massive historical data (2007-2026) for comprehensive backtest...")
    import yfinance as yf
    tickers = ["SPY", "QQQ", "TLT", "BIL", "EWA", "EWC", "^VIX", "SVXY", "TQQQ", "SQQQ"]
    data = yf.download(tickers, start="2007-01-01", interval="1d", progress=False)
    data_close = data['Close']
    data_open = data['Open']
    
    # Process market matrix mapping
    df = data_close.dropna(subset=['SPY']).copy()
    
    # SVXY was created in 2011. Forward-fill existing series. Leave unlisted periods as NaN.
    df.ffill(inplace=True)

    portfolio_value = [100000.0]
    current_allocation = {"QQQ": 0.0, "TLT": 0.0, "BIL": 0.3333, "EWA": 0.0, "EWC": 0.0, "SVXY": 0.0, "TQQQ": 0.0, "SQQQ": 0.0}
    
    total_trading_days = len(df)
    print(f"Executing daily simulation across {total_trading_days} sequence days...")
    
    daily_returns_cache = df.pct_change()
    
    # 200 day warm-up period is required for the 200d Moving Average
    for i in range(200, total_trading_days):
        
        if i % 1000 == 0:
            print(f"Progress: Evaluated {i} days... Year: {df.index[i].year}")
            
        # 1. PnL of yesterday's target execution onto today's market curve
        pnl_pct = 0.0
        for ticker, weight in current_allocation.items():
            if weight != 0 and ticker != "OVERNIGHT_SPY":
                if pd.notna(df[ticker].iloc[i-1]) and df[ticker].iloc[i-1] != 0:
                    ret = daily_returns_cache[ticker].iloc[i]
                    if pd.notna(ret) and not np.isinf(ret):
                        pnl_pct += weight * ret
            elif weight != 0 and ticker == "OVERNIGHT_SPY":
                if pd.notna(df['SPY'].iloc[i-1]) and df['SPY'].iloc[i-1] != 0:
                    ret = (data_open['SPY'].iloc[i] / df['SPY'].iloc[i-1]) - 1
                    if pd.notna(ret) and not np.isinf(ret):
                        pnl_pct += weight * ret
                
        new_value = portfolio_value[-1] * (1 + pnl_pct)
        portfolio_value.append(new_value)
        
        # 2. Strategy Calculation Phase (Snapshot History)
        historical_slice = df.iloc[:i+1]
        spy_df = pd.DataFrame({'Close': historical_slice['SPY']})
        vix_df = pd.DataFrame({'Close': historical_slice['^VIX']})
        qqq_df = pd.DataFrame({'Close': historical_slice['QQQ']})
        pair_df = pd.DataFrame({'EWA': historical_slice['EWA'], 'EWC': historical_slice['EWC']})
        
        # Calculate algorithmic weight directives
        macro_targets = get_daily_macro_allocation(spy_df, vix_df, qqq_df)
        # NOTE: get_hourly_statarb_allocation is designed for hourly data (live uses interval="1h").
        # Here it runs on daily closes so the 20-bar rolling Z-score spans 20 days, not 20 hours.
        # This approximates position-level exposure but does NOT reflect intraday signal quality.
        # For accurate StatArb backtesting, a separate hourly simulation is required.
        statarb_targets = get_hourly_statarb_allocation(pair_df)
        
        combined_target = {}
        combined_target.update(macro_targets)
        combined_target.update(statarb_targets)
        
        current_allocation = combined_target

    # Compile validation metrics
    port_series = pd.Series([100000]*200 + portfolio_value[1:], index=df.index)
    total_return = (port_series.iloc[-1] / port_series.iloc[0] - 1) * 100
    
    spy_start = df["SPY"].iloc[200]
    spy_end = df["SPY"].iloc[-1]
    benchmark_return = (spy_end / spy_start - 1) * 100
    
    running_max = port_series.cummax()
    drawdown = (port_series / running_max) - 1
    max_dd = drawdown.min() * 100
    
    spy_running_max = df["SPY"].iloc[200:].cummax()
    spy_drawdown = (df["SPY"].iloc[200:] / spy_running_max) - 1
    spy_max_dd = spy_drawdown.min() * 100
    
    print("\n" + "="*50)
    print("COMPREHENSIVE MULTI-STRATEGY BACKTEST (2008-2026)")
    print("="*50)
    print(f"Total Return:       {total_return:,.2f}%")
    print(f"Benchmark SPY Ret:  {benchmark_return:,.2f}%")
    print(f"Max Drawdown:       {max_dd:.2f}%")
    print(f"Benchmark SPY DD:   {spy_max_dd:.2f}%")
    print(f"Final Balance:      ${port_series.iloc[-1]:,.2f}")
    print("="*50)
    
if __name__ == '__main__':
    main()
