import pandas as pd
import numpy as np

def get_daily_macro_allocation(spy_df: pd.DataFrame, vix_df: pd.DataFrame, qqq_df: pd.DataFrame) -> dict:
    """
    Evaluates End-of-Day Logic:
    - Target Volatility Core (SPY/BIL): 33.33% Base, scaled to 15% Realized Volatility.
    - VRP Harvesting (SVXY): 33.34% Allocation.
    - Night Effect (SPY): 18.33% Dedicated Overnight Hold.
    """
    target = {'SPY': 0.0, 'SVXY': 0.0, 'QQQ': 0.0, 'TQQQ': 0.0, 'SQQQ': 0.0, 'TLT': 0.0, 'BIL': 0.0}
    
    spy_closes = spy_df['Close'].dropna()
    vix_closes = vix_df['Close'].dropna()

    # SLEEVE 1: Target Volatility Core (33.33% Base)
    try:
        spy_returns = spy_closes.pct_change().dropna()
        if len(spy_returns) >= 20:
            realized_vol = spy_returns.iloc[-20:].std() * np.sqrt(252)
            target_vol = 0.15  # 15% annualized target
            
            # Floor to prevent divide by zero
            realized_vol = max(0.05, realized_vol)
                
            vol_scaler = target_vol / realized_vol
            # Cap the multiplier at 1.5x, floor at 0.25x for extreme limits
            vol_scaler = max(0.25, min(1.5, vol_scaler))
            
            target['SPY'] += 0.3333 * vol_scaler
            
            # Balance un-leveraged portion into BIL (Cash equivalent)
            if vol_scaler < 1.0:
                target['BIL'] += 0.3333 * (1.0 - vol_scaler)
    except Exception as e:
        print(f"Target Vol calculation failed: {e}")
        
    # SLEEVE 2: Volatility Risk Premium Harvesting (33.34% Capital)
    try:
        implied_vol = float(vix_closes.iloc[-1])
        spy_returns_vrp = spy_closes.pct_change().dropna()
        realized_vol_vrp = float(spy_returns_vrp.iloc[-20:].std() * np.sqrt(252) * 100)
        vrp = implied_vol - realized_vol_vrp
        
        # VIX CIRCUIT BREAKER
        vix_spike = False
        if len(vix_closes) >= 2:
            vix_change = (vix_closes.iloc[-1] / vix_closes.iloc[-2]) - 1
            if vix_change > 0.15:
                vix_spike = True
                
        if implied_vol > 35.0:
            vix_spike = True
        
        # Deploy unless breaker tripped
        if vrp > 3.0 and not vix_spike:
            target['SVXY'] = 0.3334
    except Exception as e:
        print(f"VRP calculation failed: {e}")
        
    # SLEEVE 3: The Night Effect / Overnight Premium (18.33% Capital)
    # Passed as a pseudo-ticker to decouple it perfectly for the execution/backtest suites
    target['OVERNIGHT_SPY'] = 0.1833
        
    return target

def get_hourly_statarb_allocation(pair_df: pd.DataFrame) -> dict:
    """
    Evaluates Intraday Statistical Arbitrage.
    Allocates 15.00% capital neutrally between EWA/EWC.
    Z-score threshold lowered to 1.5 to capture substantially MORE trades.
    """
    target = {"EWA": 0.0, "EWC": 0.0}
    try:
        ratio = pair_df['EWA'] / pair_df['EWC']
        ratio = ratio.dropna()
        
        if len(ratio) >= 20:
            mean = ratio.rolling(20).mean()
            std = ratio.rolling(20).std()
            z_score = (ratio.iloc[-1] - mean.iloc[-1]) / std.iloc[-1]
            
            # Dollar neutral sizing (7.5% Long, 7.5% Short) = 15.00% total
            branch_size = 0.15 / 2.0 
            
            # Lower threshold takes roughly 2x-3x more trades than Z=2.0
            if z_score > 1.5:
                # EWA overpriced
                target['EWA'] = -branch_size
                target['EWC'] = branch_size
            elif z_score < -1.5:
                # EWC overpriced
                target['EWA'] = branch_size
                target['EWC'] = -branch_size
    except Exception as e:
        print(f"StatArb calculation failed: {e}")

    return target
