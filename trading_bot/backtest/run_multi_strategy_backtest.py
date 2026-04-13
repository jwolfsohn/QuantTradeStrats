import pandas as pd
import numpy as np
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy import get_daily_macro_allocation, get_momentum_allocation


def main():
    print("Fetching historical data (2007-2026) for comprehensive backtest...")
    import yfinance as yf

    tickers = ["SPY", "QQQ", "TLT", "BIL", "GLD", "XLE"]
    data = yf.download(tickers, start="2007-01-01", interval="1d", progress=False)
    data_close = data['Close']

    df = data_close.dropna(subset=['SPY']).copy()
    df.ffill(inplace=True)

    portfolio_value = [100000.0]
    current_allocation = {"SPY": 0.33, "QQQ": 0.0, "TLT": 0.0, "BIL": 0.67, "GLD": 0.0, "XLE": 0.0}

    total_trading_days = len(df)
    print(f"Executing daily simulation across {total_trading_days} trading days...")

    daily_returns_cache = df.pct_change()

    # 30-day warm-up (momentum needs 21 days, target vol needs 20)
    for i in range(30, total_trading_days):

        if i % 1000 == 0:
            print(f"Progress: {i} days evaluated... Year: {df.index[i].year}")

        # 1. Compute P&L from yesterday's allocation applied to today's returns
        pnl_pct = 0.0
        for ticker, weight in current_allocation.items():
            if weight != 0 and ticker in df.columns:
                if pd.notna(df[ticker].iloc[i - 1]) and df[ticker].iloc[i - 1] != 0:
                    ret = daily_returns_cache[ticker].iloc[i]
                    if pd.notna(ret) and not np.isinf(ret):
                        pnl_pct += weight * ret

        new_value = portfolio_value[-1] * (1 + pnl_pct)
        portfolio_value.append(new_value)

        # 2. Recompute allocations using historical slice up to today
        historical_slice = df.iloc[:i + 1]
        spy_df = pd.DataFrame({'Close': historical_slice['SPY']})
        momentum_df = pd.DataFrame({
            sym: historical_slice[sym]
            for sym in ['QQQ', 'TLT', 'GLD', 'XLE']
            if sym in historical_slice.columns
        })

        macro_targets = get_daily_macro_allocation(spy_df)
        momentum_targets = get_momentum_allocation(momentum_df)

        combined = {}
        for k, v in macro_targets.items():
            combined[k] = combined.get(k, 0.0) + v
        for k, v in momentum_targets.items():
            combined[k] = combined.get(k, 0.0) + v

        current_allocation = combined

    # ================================
    # PERFORMANCE METRICS
    # ================================
    port_series = pd.Series([100000] * 30 + portfolio_value[1:], index=df.index)
    total_return = (port_series.iloc[-1] / port_series.iloc[0] - 1) * 100

    spy_start = df["SPY"].iloc[30]
    spy_end = df["SPY"].iloc[-1]
    benchmark_return = (spy_end / spy_start - 1) * 100

    running_max = port_series.cummax()
    drawdown = (port_series / running_max) - 1
    max_dd = drawdown.min() * 100

    spy_running_max = df["SPY"].iloc[30:].cummax()
    spy_drawdown = (df["SPY"].iloc[30:] / spy_running_max) - 1
    spy_max_dd = spy_drawdown.min() * 100

    # Sharpe: use BIL daily returns as time-varying risk-free rate proxy
    bil_daily_returns = df["BIL"].pct_change().dropna()
    port_daily_returns = port_series.pct_change().dropna()

    # Align indexes
    aligned_idx = port_daily_returns.index.intersection(bil_daily_returns.index)
    excess_returns = port_daily_returns[aligned_idx] - bil_daily_returns[aligned_idx]
    sharpe_ratio = (excess_returns.mean() / excess_returns.std() * np.sqrt(252)) if excess_returns.std() > 0 else 0

    spy_daily_returns = df["SPY"].iloc[30:].pct_change().dropna()
    spy_excess = spy_daily_returns[aligned_idx.intersection(spy_daily_returns.index)] - bil_daily_returns[aligned_idx.intersection(spy_daily_returns.index)]
    spy_sharpe = (spy_excess.mean() / spy_excess.std() * np.sqrt(252)) if spy_excess.std() > 0 else 0

    print("\n" + "=" * 50)
    print("BACKTEST RESULTS: TARGET VOL + MOMENTUM (2007-2026)")
    print("=" * 50)
    print(f"Total Return:       {total_return:,.2f}%")
    print(f"Benchmark SPY Ret:  {benchmark_return:,.2f}%")
    print(f"Max Drawdown:       {max_dd:.2f}%")
    print(f"Benchmark SPY DD:   {spy_max_dd:.2f}%")
    print(f"Sharpe Ratio:       {sharpe_ratio:.2f}")
    print(f"Benchmark Sharpe:   {spy_sharpe:.2f}")
    print(f"Final Balance:      ${port_series.iloc[-1]:,.2f}")
    print("=" * 50)

    # ================================
    # BEAR MARKET STRESS TESTS
    # ================================
    bear_periods = [
        ("2007-10-01", "2009-03-31", "Global Financial Crisis"),
        ("2020-02-01", "2020-04-30", "COVID Crash"),
        ("2022-01-01", "2022-12-31", "2022 Rate Hike Bear Market"),
    ]

    for start_str, end_str, label in bear_periods:
        start_date = pd.Timestamp(start_str)
        end_date = pd.Timestamp(end_str)

        if port_series.index.tz is not None:
            start_date = start_date.tz_localize(port_series.index.tz)
            end_date = end_date.tz_localize(port_series.index.tz)

        mask = (port_series.index >= start_date) & (port_series.index <= end_date)
        bear_port = port_series[mask]
        bear_spy = df["SPY"][mask]

        if len(bear_port) < 20:
            print(f"\n{label}: Insufficient data ({len(bear_port)} days), skipping.")
            continue

        bear_port_return = (bear_port.iloc[-1] / bear_port.iloc[0] - 1) * 100
        bear_spy_return = (bear_spy.iloc[-1] / bear_spy.iloc[0] - 1) * 100
        bear_port_dd = ((bear_port / bear_port.cummax()) - 1).min() * 100
        bear_spy_dd = ((bear_spy / bear_spy.cummax()) - 1).min() * 100

        bear_daily_ret = bear_port.pct_change().dropna()
        bear_bil = bil_daily_returns[bear_daily_ret.index.intersection(bil_daily_returns.index)]
        bear_excess = bear_daily_ret[bear_bil.index] - bear_bil
        bear_sharpe = (bear_excess.mean() / bear_excess.std() * np.sqrt(252)) if bear_excess.std() > 0 else 0

        print(f"\n{'=' * 50}")
        print(f"BEAR MARKET: {label} ({start_str} to {end_str})")
        print(f"{'=' * 50}")
        print(f"Strategy Return:    {bear_port_return:,.2f}%")
        print(f"SPY Return:         {bear_spy_return:,.2f}%")
        print(f"Strategy Max DD:    {bear_port_dd:.2f}%")
        print(f"SPY Max DD:         {bear_spy_dd:.2f}%")
        print(f"Sharpe Ratio:       {bear_sharpe:.2f}")
        print(f"{'=' * 50}")


if __name__ == '__main__':
    main()
