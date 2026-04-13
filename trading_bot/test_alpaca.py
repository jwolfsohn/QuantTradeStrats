import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, PAPER_TRADING
from alpaca.trading.client import TradingClient

client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=PAPER_TRADING)
positions = client.get_all_positions()
for p in positions:
    print(p.symbol, "qty:", p.qty, "side:", p.side, "type of qty:", type(p.qty))
