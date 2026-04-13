import pandas as pd
import numpy as np
import logging


def get_daily_macro_allocation(spy_df: pd.DataFrame) -> dict:
    """
    Sleeve 1 — Target Volatility Core (65% base):
    Scale SPY exposure inversely to 20-day realized vol targeting 12% annualized.
    Remainder (when under-invested) parks in BIL.

    vol_scaler capped at [0.25, 1.25] — max 65% * 1.25 = 81% SPY (intentionally
    conservative; sleeve 2 adds up to 35% more, so total can reach ~81% equities).
    """
    target = {'SPY': 0.0, 'BIL': 0.0}

    try:
        spy_closes = spy_df['Close'].dropna()
        spy_returns = spy_closes.pct_change().dropna()
        if len(spy_returns) >= 20:
            realized_vol = spy_returns.iloc[-20:].std() * np.sqrt(252)
            target_vol = 0.12  # 12% annualized target (down from 15% — structural VIX floor higher since 2022)
            realized_vol = max(0.05, realized_vol)

            vol_scaler = target_vol / realized_vol
            vol_scaler = max(0.25, min(1.25, vol_scaler))

            target['SPY'] = 0.65 * vol_scaler

            # Park unused portion in BIL when under-invested
            if vol_scaler < 1.0:
                target['BIL'] = 0.65 * (1.0 - vol_scaler)
    except Exception as e:
        logging.error(f"Target Vol calculation failed: {e}")

    return target


def get_momentum_allocation(momentum_df: pd.DataFrame) -> dict:
    """
    Sleeve 2 — Cross-Sectional Momentum (35% base):
    Ranks QQQ, TLT, GLD, XLE by 20-day cumulative return.
    Allocates equally to top 2 symbols with positive returns.
    If no symbols have positive returns, parks entire 35% in BIL.

    Rebalances on every EOD run (daily signal, monthly-scale holding period
    because the 20-day lookback only turns over ~monthly on average).
    """
    universe = ['QQQ', 'TLT', 'GLD', 'XLE']
    target = {sym: 0.0 for sym in universe}
    target['BIL'] = 0.0

    try:
        sleeve_size = 0.35
        returns = {}
        for sym in universe:
            if sym in momentum_df.columns:
                closes = momentum_df[sym].dropna()
                if len(closes) >= 21:
                    ret = (closes.iloc[-1] / closes.iloc[-21]) - 1
                    returns[sym] = ret

        positive_ranked = sorted(
            [(sym, r) for sym, r in returns.items() if r > 0],
            key=lambda x: x[1], reverse=True
        )

        top_symbols = [sym for sym, _ in positive_ranked[:2]]

        if top_symbols:
            weight_each = sleeve_size / len(top_symbols)
            for sym in top_symbols:
                target[sym] = weight_each
        else:
            # All momentum signals negative — full defensive posture
            target['BIL'] = sleeve_size

    except Exception as e:
        logging.error(f"Momentum calculation failed: {e}")

    return target
