import os
import sys
import time
import functools
import yfinance as yf
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, PAPER_TRADING

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus

# Lazy client — initialized on first use so import failures don't crash the bot
_client = None

def get_client() -> TradingClient:
    global _client
    if _client is None:
        _client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=PAPER_TRADING)
    return _client


def retry_api(max_attempts=3, delay=2):
    """Retry decorator with linear backoff for transient API failures."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    logging.warning(
                        f"{func.__name__} failed (attempt {attempt + 1}/{max_attempts}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
        return wrapper
    return decorator


def wait_for_fill(order_id, timeout=30):
    """Poll Alpaca until an order reaches a terminal status. Returns True if filled."""
    terminal_statuses = {OrderStatus.FILLED, OrderStatus.CANCELED,
                         OrderStatus.EXPIRED, OrderStatus.REJECTED}
    start = time.time()
    while time.time() - start < timeout:
        order = get_client().get_order_by_id(order_id)
        if order.status == OrderStatus.FILLED:
            logging.info(f"Order {order_id} filled.")
            return True
        if order.status in terminal_statuses:
            logging.error(f"Order {order_id} reached terminal status: {order.status}")
            return False
        time.sleep(2)
    logging.error(f"Order {order_id} timed out after {timeout}s")
    return False


def rebalance_to_target(target_allocation: dict):
    """
    Master portfolio routing. Three-phase execution:
      Phase 1: Full liquidations via close_position() — any position where target is 0
               OR crossing zero (sign flip). Does NOT open the new direction in the same
               cycle; that happens naturally next rebalance.
      Phase 2: Partial reduction sells (same-sign, reducing size but not to 0).
               wait_for_fill() ensures sells settle before buys consume buying power.
      Phase 3: Buys with buying-power pre-check and proportional scaling.
    """
    logging.info(f"Executing master portfolio rebalance: {target_allocation}")
    client = get_client()

    # Cancel existing open orders to unlock buying power
    try:
        client.cancel_orders()
        logging.info("Cancelled any pending open orders.")
        time.sleep(1)
    except Exception as e:
        logging.error(f"Could not cancel open orders: {e}")

    account = client.get_account()
    equity = float(account.equity)
    logging.info(f"Current Account Equity: ${equity:,.2f}")

    # Fetch current positions
    positions = client.get_all_positions()
    current_shares = {}
    for p in positions:
        qty = float(p.qty)
        side_str = str(getattr(p, 'side', '')).lower()
        if side_str.endswith('short') or side_str == 'short':
            qty = -abs(qty)
        else:
            qty = abs(qty)
        current_shares[p.symbol] = qty

    all_managed_symbols = set(current_shares.keys()).union(set(target_allocation.keys()))

    # Categorized order lists for three-phase execution
    to_close_fully = []   # symbols to liquidate via close_position()
    reduction_sells = []  # MarketOrderRequest for partial same-sign reductions
    new_buys = []         # MarketOrderRequest for same-sign increases or new longs
    prices = {}           # symbol -> price (for Phase 3 buying-power check)

    # Whitelist keeps residual positions (EWA/EWC from old strategy) cleanable
    WHITELIST = {"SPY", "QQQ", "TLT", "BIL", "GLD", "XLE", "EWA", "EWC", "SVXY", "TQQQ", "SQQQ"}

    for symbol in all_managed_symbols:
        if symbol.startswith("_") or symbol == "OVERNIGHT_SPY":
            if symbol == "OVERNIGHT_SPY":
                logging.error("OVERNIGHT_SPY reached rebalance_to_target — convert to SPY in main_bot.py first. Skipping.")
            continue
        if symbol not in WHITELIST:
            continue

        weight = target_allocation.get(symbol, 0.0)
        target_dollar_value = equity * weight

        if symbol in [p.symbol for p in positions]:
            position = next(p for p in positions if p.symbol == symbol)
            price = float(position.current_price)
        else:
            try:
                price = filter_yfinance_price(symbol)
            except Exception:
                logging.warning(f"Could not fetch price for {symbol}, skipping.")
                continue

        prices[symbol] = price
        target_shares = round(target_dollar_value / price)
        curr_shares = round(current_shares.get(symbol, 0))
        delta_shares = target_shares - curr_shares

        if delta_shares == 0:
            continue

        target_sign = 1 if target_shares > 0 else (-1 if target_shares < 0 else 0)
        curr_sign = 1 if curr_shares > 0 else (-1 if curr_shares < 0 else 0)

        needs_full_close = (
            (target_shares == 0 and curr_shares != 0) or
            ((curr_sign * target_sign < 0) and curr_shares != 0)
        )

        if needs_full_close:
            to_close_fully.append(symbol)
            if target_shares == 0:
                logging.info(f"Action: CLOSE entire {abs(curr_shares):,.0f} share position in {symbol} (target is 0)")
            else:
                logging.info(f"Action: CLOSE {abs(curr_shares):,.0f} shares of {symbol} (crossing zero to {target_shares:+,.0f}); will open new direction next cycle")

        elif delta_shares > 0:
            new_buys.append(MarketOrderRequest(
                symbol=symbol,
                qty=delta_shares,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY
            ))
            logging.info(f"Action: BUY {delta_shares:,.0f} shares of {symbol} (Target: {target_shares}, Current: {curr_shares})")

        elif delta_shares < 0:
            sell_amount = abs(delta_shares)
            reduction_sells.append(MarketOrderRequest(
                symbol=symbol,
                qty=sell_amount,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            ))
            logging.info(f"Action: SELL {sell_amount:,.0f} shares of {symbol} (Target: {target_shares}, Current: {curr_shares})")

    # ========== PHASE 1: Full liquidations via close_position() ==========
    for symbol in to_close_fully:
        try:
            close_order = client.close_position(symbol)
            order_id = close_order.id if hasattr(close_order, 'id') else close_order.get('id')
            logging.info(f"Submitted close_position for {symbol}, order id: {order_id}")
            wait_for_fill(order_id, timeout=30)
        except Exception as e:
            logging.error(f"close_position failed for {symbol}: {e}")

    # ========== PHASE 2: Partial reduction sells (wait for fill before Phase 3) ==========
    for order in reduction_sells:
        try:
            result = client.submit_order(order)
            order_id = result.id if hasattr(result, 'id') else result.get('id')
            logging.info(f"Submitted SELL order for {order.symbol}, order id: {order_id}")
            wait_for_fill(order_id, timeout=30)
        except Exception as e:
            logging.error(f"SELL Order failed for {order.symbol}: {e}")

    # ========== PHASE 3: Buys with buying-power pre-check ==========
    for order in new_buys:
        try:
            account = client.get_account()
            buying_power = float(account.buying_power)
            est_cost = float(order.qty) * prices.get(order.symbol, 0)

            if est_cost > buying_power * 0.95:
                price = prices.get(order.symbol, 1)
                scaled_qty = int(buying_power * 0.90 / price)
                if scaled_qty <= 0:
                    logging.error(
                        f"Insufficient buying power for {order.symbol} "
                        f"(need ~${est_cost:,.0f}, have ${buying_power:,.0f}). Skipping."
                    )
                    continue
                logging.warning(
                    f"Scaling {order.symbol} buy from {order.qty} to {scaled_qty} shares "
                    f"(buying power: ${buying_power:,.0f})"
                )
                order = MarketOrderRequest(
                    symbol=order.symbol,
                    qty=scaled_qty,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY
                )

            client.submit_order(order)
            logging.info(f"Submitted BUY order for {order.symbol}")
        except Exception as e:
            logging.error(f"BUY Order failed for {order.symbol}: {e}")

    logging.info("Rebalancing complete.")


@retry_api(max_attempts=3, delay=2)
def filter_yfinance_price(symbol):
    ticker = yf.Ticker(symbol)
    if 'lastPrice' in ticker.fast_info:
        return ticker.fast_info['lastPrice']
    if 'regularMarketPrice' in ticker.info:
        return ticker.info['regularMarketPrice']
    return ticker.history(period='1d')['Close'].iloc[-1]
