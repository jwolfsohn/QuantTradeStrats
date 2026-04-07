import os
import sys
import yfinance as yf

# Ensure we can import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, PAPER_TRADING

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# Initialize TradingClient
client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=PAPER_TRADING)

def rebalance_to_target(target_allocation: dict):
    """
    Master portfolio routing. Completely robust handling for Longs, Shorts, 
    Reductions, and Covers based on the exact target_allocation weights.
    """
    print(f"Executing master portfolio rebalance: {target_allocation}")
    
    account = client.get_account()
    equity = float(account.equity)
    print(f"Current Account Equity: ${equity:,.2f}")

    # Fetch current positions
    positions = client.get_all_positions()
    current_shares = {}
    for p in positions:
        qty = float(p.qty)
        # Check if the position side signifies a short
        side_str = str(getattr(p, 'side', '')).lower()
        if side_str.endswith('short') or side_str == 'short':
            qty = -qty
        current_shares[p.symbol] = qty
    
    
    # We only want to manage symbols that are either currently held OR in our target map.
    all_managed_symbols = set(current_shares.keys()).union(set(target_allocation.keys()))
    
    orders_to_execute = []

    for symbol in all_managed_symbols:
        # Prevent attempting to touch non-strategy holdings if the user holds personal stocks
        # Add new symbols to this whitelist as needed
        if symbol not in ["SPY", "QQQ", "TLT", "BIL", "EWA", "EWC", "SVXY", "TQQQ", "SQQQ"]:
            continue
            
        weight = target_allocation.get(symbol, 0.0)
        target_dollar_value = equity * weight
        
        # Use existing position price, otherwise fallback to yfinance for new positions
        if symbol in [p.symbol for p in positions]:
            position = next(p for p in positions if p.symbol == symbol)
            price = float(position.current_price)
        else:
            try:
                price = filter_yfinance_price(symbol)
            except:
                print(f"Could not fetch price for {symbol}, skipping.")
                continue

        # Calculate exact number of shares we *want* to hold (can be negative for shorts)
        target_shares = int(target_dollar_value / price)
        curr_shares = int(current_shares.get(symbol, 0))
        
        delta_shares = target_shares - curr_shares

        # Generate orders to cover the delta
        if delta_shares != 0:
            target_sign = 1 if target_shares > 0 else (-1 if target_shares < 0 else 0)
            curr_sign = 1 if curr_shares > 0 else (-1 if curr_shares < 0 else 0)

            # Check if crossing zero
            if (curr_sign * target_sign < 0) and target_shares != 0 and curr_shares != 0:
                # We are crossing zero. Two legs needed.
                close_qty = abs(curr_shares)
                close_side = OrderSide.SELL if curr_shares > 0 else OrderSide.BUY
                orders_to_execute.append(MarketOrderRequest(
                    symbol=symbol,
                    qty=close_qty,
                    side=close_side,
                    time_in_force=TimeInForce.DAY
                ))
                print(f"Action: {close_side.name} {close_qty:,.0f} shares of {symbol} to CLOSE existing position")
                
                open_qty = abs(target_shares)
                open_side = OrderSide.SELL if target_shares < 0 else OrderSide.BUY
                orders_to_execute.append(MarketOrderRequest(
                    symbol=symbol,
                    qty=open_qty,
                    side=open_side,
                    time_in_force=TimeInForce.DAY
                ))
                print(f"Action: {open_side.name} {open_qty:,.0f} shares of {symbol} to OPEN new target position")
                
            else:
                # Same sign or starting/ending at zero
                if delta_shares > 0:
                    orders_to_execute.append(MarketOrderRequest(
                        symbol=symbol,
                        qty=delta_shares,
                        side=OrderSide.BUY,
                        time_in_force=TimeInForce.DAY
                    ))
                    print(f"Action: BUY {delta_shares:,.0f} shares of {symbol} (Target: {target_shares}, Current: {curr_shares})")
                elif delta_shares < 0:
                    sell_amount = abs(delta_shares)
                    orders_to_execute.append(MarketOrderRequest(
                        symbol=symbol,
                        qty=sell_amount,
                        side=OrderSide.SELL,
                        time_in_force=TimeInForce.DAY
                    ))
                    print(f"Action: SELL (or SHORT) {sell_amount:,.0f} shares of {symbol} (Target: {target_shares}, Current: {curr_shares})")

    # Execute all orders
    for order in orders_to_execute:
        try:
            client.submit_order(order)
            print(f"Submitted order for {order.symbol}")
        except Exception as e:
            print(f"Order failed for {order.symbol}: {e}")

    print("Rebalancing complete.")

def filter_yfinance_price(symbol):
    ticker = yf.Ticker(symbol)
    if 'lastPrice' in ticker.fast_info:
        return ticker.fast_info['lastPrice']
    if 'regularMarketPrice' in ticker.info:
        return ticker.info['regularMarketPrice']
    return ticker.history(period='1d')['Close'].iloc[-1]
