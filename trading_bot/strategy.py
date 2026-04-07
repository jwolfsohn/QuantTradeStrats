import pandas as pd
import numpy as np

def classify_regime(spy_prices: pd.Series) -> str:
    """
    Classify market regime as BULL, MILD_BULL, MILD_BEAR, or BEAR
    based on trend + dual-momentum confirmation.
    """
    close = spy_prices.dropna()
    
    if len(close) < 200:
        return "BEAR"
        
    sma200 = close.rolling(200).mean()
    above_200 = close.iloc[-1] > sma200.iloc[-1]

    ret_20d = (close.iloc[-1] / (close.iloc[-21] if len(close) > 20 else close.iloc[0])) - 1
    ret_60d = (close.iloc[-1] / (close.iloc[-61] if len(close) > 60 else close.iloc[0])) - 1
    momentum_positive = (ret_20d > 0) and (ret_60d > 0)

    daily_returns = close.pct_change().dropna()
    realized_vol = daily_returns.iloc[-20:].std() * np.sqrt(252)
    high_vol = realized_vol > 0.20

    if above_200 and momentum_positive:
        regime = "BULL"
    elif above_200 and not momentum_positive:
        regime = "MILD_BULL"
    elif not above_200 and momentum_positive:
        regime = "MILD_BEAR"
    else:
        regime = "BEAR"

    if high_vol:
        downgrade = {"BULL": "MILD_BULL", "MILD_BULL": "MILD_BEAR",
                     "MILD_BEAR": "BEAR", "BEAR": "BEAR"}
        regime = downgrade[regime]

    return regime


def get_target_allocation(regime: str) -> dict:
    """Return target ETF allocation for given regime."""
    allocations = {
        "BULL":      {"QQQ": 1.00, "TLT": 0.00, "BIL": 0.00},
        "MILD_BULL": {"QQQ": 0.60, "TLT": 0.40, "BIL": 0.00},
        "MILD_BEAR": {"QQQ": 0.00, "TLT": 0.40, "BIL": 0.60},
        "BEAR":      {"QQQ": 0.00, "TLT": 0.00, "BIL": 1.00},
    }
    return allocations[regime]

def get_daily_macro_allocation(spy_df: pd.DataFrame, vix_df: pd.DataFrame, qqq_df: pd.DataFrame) -> dict:
    """
    Evaluates End-of-Day logic.
    - Sleeve 1: ETF Rotation (33.33%)
    - Sleeve 3: VRP Harvesting (33.34%)
    - Sleeve 4: TSMOM Fast Trend (18.33%)
    """
    target = {}
    
    # SLEEVE 1: Regime Rotation (33.33% Capital)
    regime = classify_regime(spy_df['Close'])
    base_alloc = get_target_allocation(regime)
    for k, v in base_alloc.items():
        target[k] = v * 0.3333
        
    # SLEEVE 3: Volatility Risk Premium Harvesting (33.34% Capital)
    try:
        implied_vol = float(vix_df['Close'].dropna().iloc[-1])
        spy_returns = spy_df['Close'].pct_change().dropna()
        realized_vol = float(spy_returns.iloc[-20:].std() * np.sqrt(252) * 100)
        vrp = implied_vol - realized_vol
        
        # VIX CIRCUIT BREAKER ("Volmageddon" Protection)
        vix_spike = False
        vix_closes = vix_df['Close'].dropna()
        if len(vix_closes) >= 2:
            vix_change = (vix_closes.iloc[-1] / vix_closes.iloc[-2]) - 1
            if vix_change > 0.15:
                vix_spike = True
                
        if implied_vol > 25.0:
            vix_spike = True
        
        # Deploy unless in BEAR or breaker tripped
        if vrp > 3.0 and regime not in ["BEAR", "MILD_BEAR"] and not vix_spike:
            target['SVXY'] = 0.3334
        else:
            target['SVXY'] = 0.0
    except Exception as e:
        print(f"VRP calculation failed: {e}")
        target['SVXY'] = 0.0
        
    # SLEEVE 4: TSMOM Fast Trend (18.33% Capital) using TQQQ/SQQQ
    try:
        qqq_close = qqq_df['Close'].dropna()
        target['TQQQ'] = 0.0
        target['SQQQ'] = 0.0
        if len(qqq_close) >= 20:
            sma20 = qqq_close.rolling(20).mean().iloc[-1]
            current_price = qqq_close.iloc[-1]
            
            # Fast crossover logic for aggressive, frequent flips
            if current_price > sma20:
                target['TQQQ'] = 0.1833
            else:
                target['SQQQ'] = 0.1833
    except Exception as e:
        print(f"TSMOM calculation failed: {e}")
        target['TQQQ'] = 0.0
        target['SQQQ'] = 0.0

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
