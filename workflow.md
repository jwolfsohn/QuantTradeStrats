# Implementation Workflow: Multi-Regime ETF Rotation Bot

This is a step-by-step guide to go from zero to a live, profitable trading bot running the Multi-Regime ETF Rotation strategy (with optional crypto funding rate arbitrage overlay).

---

## Phase 0: Prerequisites

### What You Need
- Python 3.11+ installed
- A brokerage account (Alpaca recommended for beginners; Interactive Brokers for advanced)
- Optionally: A crypto exchange account (Binance or Bybit) for the funding rate overlay
- ~$5,000 minimum capital for ETF rotation; $2,000+ additional for crypto arb
- A computer or VPS that stays online (see Phase 5)

### Time Commitment
- Setup: 1–2 weekends
- Testing: 1–2 weeks of paper trading
- Ongoing maintenance: 1–2 hours/week

---

## Phase 1: Data Access — APIs and Setup

### 1A. Market Data for ETF Rotation Strategy

**Option 1 (Free, Recommended to Start): yfinance**
```bash
pip install yfinance
```
```python
import yfinance as yf

# Download daily OHLCV data
spy = yf.download("SPY", start="2020-01-01", interval="1d")
qqq = yf.download("QQQ", start="2020-01-01", interval="1d")
tlt = yf.download("TLT", start="2020-01-01", interval="1d")
bil = yf.download("BIL", start="2020-01-01", interval="1d")
```
- **Limitations**: 15-minute delay on intraday; daily data is fine for this strategy
- **Cost**: Free
- **Use for**: Backtesting and daily signal generation (the strategy only acts at market close/open)

**Option 2 (Paid, More Reliable): Alpaca Data API**
- Sign up at alpaca.markets
- Free tier: Unlimited IEX data; Paid tier ($29/mo): SIP (consolidated tape) data
- Better for live trading since it integrates directly with their brokerage

```bash
pip install alpaca-py
```
```python
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime

client = StockHistoricalDataClient(API_KEY, API_SECRET)

request_params = StockBarsRequest(
    symbol_or_symbols=["SPY", "QQQ", "TLT", "BIL"],
    timeframe=TimeFrame.Day,
    start=datetime(2020, 1, 1)
)

bars = client.get_stock_bars(request_params)
```

**Option 3 (Free, Federal Reserve): FRED API for Macro Data**
- Sign up at fred.stlouisfed.org/docs/api/api_key.html (free API key)
- Use for: VIX data, credit spreads (HYG-LQD), Treasury yields
```bash
pip install fredapi
```
```python
from fredapi import Fred
fred = Fred(api_key='YOUR_FRED_API_KEY')

vix = fred.get_series('VIXCLS')  # VIX daily
hys = fred.get_series('BAMLH0A0HYM2')  # HY credit spread
```

### 1B. Crypto Data for Funding Rate Arbitrage

**Binance API (Free)**
- Sign up at binance.com
- Create API key (read-only for data, trade permissions for live)
- Key data: spot prices, perpetual funding rates, order book depth

```bash
pip install ccxt
```
```python
import ccxt

exchange = ccxt.binance({
    'apiKey': 'YOUR_API_KEY',
    'secret': 'YOUR_SECRET',
    'enableRateLimit': True,
})

# Get current funding rate
funding_rate = exchange.fetch_funding_rate('BTC/USDT:USDT')
print(f"Current 8hr rate: {funding_rate['fundingRate']:.4%}")
print(f"Annualized: {funding_rate['fundingRate'] * 3 * 365:.2%}")

# Get historical funding rates
history = exchange.fetch_funding_rate_history('BTC/USDT:USDT', limit=100)
```

**Bybit API (Free, Alternative)**
```python
exchange = ccxt.bybit({
    'apiKey': 'YOUR_BYBIT_KEY',
    'secret': 'YOUR_BYBIT_SECRET',
})
```

---

## Phase 2: Backtesting

### 2A. Set Up Your Backtesting Environment

```bash
pip install vectorbt pandas numpy matplotlib
```

**Project Structure:**
```
trading_bot/
├── data/               # Cached historical data
├── backtest/           # Backtest scripts
├── live/               # Live trading scripts
├── config.py           # API keys, parameters
├── strategy.py         # Core strategy logic
├── risk.py             # Kelly sizing, position limits
└── requirements.txt
```

### 2B. Implement the Regime Classifier

```python
# strategy.py
import pandas as pd
import numpy as np

def classify_regime(spy_prices: pd.Series) -> str:
    """
    Classify market regime as BULL, MILD_BULL, MILD_BEAR, or BEAR
    based on trend + dual-momentum confirmation.
    """
    close = spy_prices

    # Trend filter: price vs 200-day SMA
    sma200 = close.rolling(200).mean()
    above_200 = close.iloc[-1] > sma200.iloc[-1]

    # Momentum: 20-day and 60-day returns
    ret_20d = (close.iloc[-1] / close.iloc[-21] - 1)
    ret_60d = (close.iloc[-1] / close.iloc[-61] - 1)
    momentum_positive = (ret_20d > 0) and (ret_60d > 0)

    # Volatility context (optional refinement)
    daily_returns = close.pct_change().dropna()
    realized_vol = daily_returns.iloc[-20:].std() * np.sqrt(252)
    high_vol = realized_vol > 0.20

    # Regime assignment
    if above_200 and momentum_positive:
        regime = "BULL"
    elif above_200 and not momentum_positive:
        regime = "MILD_BULL"
    elif not above_200 and momentum_positive:
        regime = "MILD_BEAR"
    else:
        regime = "BEAR"

    # Downgrade one level if high volatility
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
```

### 2C. Run a Backtest

```python
# backtest/run_backtest.py
import yfinance as yf
import pandas as pd
import numpy as np
from strategy import classify_regime, get_target_allocation

# Download data
tickers = ["SPY", "QQQ", "TLT", "BIL"]
data = yf.download(tickers, start="2018-01-01", end="2026-01-01")["Close"]

portfolio_value = [100000]  # Starting capital
current_allocation = {"QQQ": 0, "TLT": 0, "BIL": 1.0}

for i in range(200, len(data)):
    date = data.index[i]
    spy_prices = data["SPY"].iloc[:i+1]

    regime = classify_regime(spy_prices)
    target = get_target_allocation(regime)

    # Calculate daily P&L
    daily_returns = {}
    for ticker in ["QQQ", "TLT", "BIL"]:
        if i > 0:
            daily_returns[ticker] = (
                data[ticker].iloc[i] / data[ticker].iloc[i-1] - 1
            )

    pnl = sum(current_allocation.get(t, 0) * r for t, r in daily_returns.items())
    new_value = portfolio_value[-1] * (1 + pnl)
    portfolio_value.append(new_value)
    current_allocation = target

# Results
returns = pd.Series(portfolio_value)
total_return = (returns.iloc[-1] / returns.iloc[0] - 1) * 100
max_dd = ((returns / returns.cummax()) - 1).min() * 100
print(f"Total Return: {total_return:.2f}%")
print(f"Max Drawdown: {max_dd:.2f}%")
```

### 2D. Key Backtest Sanity Checks (Before Going Live)
- [ ] Does the strategy beat SPY buy-and-hold on a **risk-adjusted** basis (Sharpe > 1.0)?
- [ ] Does the max drawdown stay below your personal tolerance?
- [ ] Walk-forward test: Train on 2018–2022, test on 2023–2025. Does it still work?
- [ ] Sensitivity check: Does performance collapse if you change the 200d window to 180d or 220d? (It shouldn't — if it does, you're overfitting)
- [ ] Include transaction costs: $0 commission but assume 0.05% slippage per trade

---

## Phase 3: Brokerage Account & Trading API

### 3A. Alpaca (Recommended for Beginners)

**Setup:**
1. Go to alpaca.markets → Create account
2. Complete identity verification (SSN required for US residents)
3. Fund account (minimum ~$2,000 for meaningful positions; $25,000 for PDT rule exemption if you plan >3 day trades/week)
4. Generate API keys at app.alpaca.markets/paper-trading (paper) or app.alpaca.markets/live

**Important**: Start with **paper trading** (simulated money) for at least 2 weeks before going live.

```bash
pip install alpaca-py
```

```python
# config.py
ALPACA_API_KEY = "your_key_here"
ALPACA_SECRET_KEY = "your_secret_here"
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"  # Change to live when ready
```

```python
# live/execute_trades.py
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)

def rebalance_to_target(target_allocation: dict, total_capital: float):
    """Sell positions not in target, buy new targets."""

    # Get current positions
    positions = {p.symbol: p for p in client.get_all_positions()}
    account = client.get_account()
    equity = float(account.equity)

    # Liquidate positions not in target or overweight
    for symbol, position in positions.items():
        target_weight = target_allocation.get(symbol, 0)
        current_value = float(position.market_value)
        target_value = equity * target_weight

        if current_value - target_value > equity * 0.02:  # >2% drift threshold
            # Sell excess
            shares_to_sell = int((current_value - target_value) / float(position.current_price))
            if shares_to_sell > 0:
                order = MarketOrderRequest(
                    symbol=symbol,
                    qty=shares_to_sell,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY
                )
                client.submit_order(order)

    # Buy new positions
    for symbol, weight in target_allocation.items():
        if weight > 0:
            target_value = equity * weight
            current_value = float(positions.get(symbol, type('obj', (object,), {'market_value': 0})()).market_value or 0)

            if target_value - current_value > equity * 0.02:
                # Get current price
                latest_price = float(client.get_open_position(symbol).current_price if symbol in positions else yf.Ticker(symbol).fast_info['lastPrice'])
                shares_to_buy = int((target_value - current_value) / latest_price)

                if shares_to_buy > 0:
                    order = MarketOrderRequest(
                        symbol=symbol,
                        qty=shares_to_buy,
                        side=OrderSide.BUY,
                        time_in_force=TimeInForce.DAY
                    )
                    client.submit_order(order)
```

### 3B. Interactive Brokers (Advanced, More Markets)

- Better for options, futures, and international markets
- More complex setup but more powerful
- Use `ib_insync` library: `pip install ib_insync`
- Requires installing TWS (Trader Workstation) or IB Gateway locally
- Minimum account: $0 (but $2,000+ recommended)

### 3C. Crypto Exchange Setup (Funding Rate Arb)

**Binance (Recommended for Funding Rate Arb):**
1. Go to binance.com → Create account
2. Complete KYC (passport or driver's license)
3. Deposit USDT (start with $1,000–$2,000)
4. Enable futures trading (separate section from spot)
5. Generate API key: Account → API Management → Create API
   - Enable: "Enable Reading", "Enable Spot & Margin Trading", "Enable Futures"
   - Disable: "Enable Withdrawals" (security best practice)
   - Whitelist your IP address

**Note on US Residents**: Binance is restricted for US users. Use:
- **Binance.US** (limited futures)
- **Bybit** (full futures, available in most US states except NY, TX, VT, HI)
- **Kraken** (futures available)

---

## Phase 4: Building the Live Bot

### 4A. Main Bot Loop

```python
# live/main_bot.py
import schedule
import time
import yfinance as yf
from datetime import datetime
from strategy import classify_regime, get_target_allocation
from execute_trades import rebalance_to_target
import logging

logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def run_regime_check():
    """Run daily at market close to determine next day's allocation."""
    try:
        # Download latest SPY data
        spy = yf.download("SPY", period="1y", interval="1d", progress=False)

        if spy.empty:
            logging.error("Failed to fetch SPY data")
            return

        regime = classify_regime(spy["Close"])
        target = get_target_allocation(regime)

        logging.info(f"Current regime: {regime}")
        logging.info(f"Target allocation: {target}")

        # Execute rebalance (paper or live depending on config)
        rebalance_to_target(target, total_capital=None)  # Uses account equity

        logging.info("Rebalancing complete")

    except Exception as e:
        logging.error(f"Error in regime check: {e}")
        # Send alert (see Phase 4B)

# Schedule: Run at 3:45 PM ET on weekdays (15 min before close)
schedule.every().monday.at("15:45").do(run_regime_check)
schedule.every().tuesday.at("15:45").do(run_regime_check)
schedule.every().wednesday.at("15:45").do(run_regime_check)
schedule.every().thursday.at("15:45").do(run_regime_check)
schedule.every().friday.at("15:45").do(run_regime_check)

if __name__ == "__main__":
    logging.info("Bot started")
    while True:
        schedule.run_pending()
        time.sleep(60)
```

### 4B. Alerts and Monitoring

```bash
pip install python-telegram-bot
```

```python
# notifications.py
import asyncio
from telegram import Bot

TELEGRAM_TOKEN = "your_bot_token"  # Get from @BotFather on Telegram
TELEGRAM_CHAT_ID = "your_chat_id"  # Your personal chat ID

async def send_alert(message: str):
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

def notify(message: str):
    asyncio.run(send_alert(message))

# Usage in main bot:
# notify(f"Regime changed to {regime}. Rebalancing to {target}")
```

**To get your Telegram bot token:**
1. Open Telegram → Search "@BotFather"
2. Send `/newbot` → Follow instructions → Get API token
3. Send a message to your bot → Get your chat ID from `api.telegram.org/bot<TOKEN>/getUpdates`

### 4C. Crypto Funding Rate Bot

```python
# live/funding_arb_bot.py
import ccxt
import schedule
import logging

exchange = ccxt.binance({
    'apiKey': 'YOUR_KEY',
    'secret': 'YOUR_SECRET',
    'options': {'defaultType': 'future'},  # For futures operations
    'enableRateLimit': True,
})

ENTRY_THRESHOLD = 0.00548  # 0.548% per 8hr = ~15% annualized
EXIT_THRESHOLD = 0.00137   # 0.137% per 8hr = ~5% annualized
POSITION_SIZE_USD = 1000   # Start small

def check_funding_opportunity(symbol='BTC/USDT:USDT'):
    rate_data = exchange.fetch_funding_rate(symbol)
    rate = rate_data['fundingRate']
    annualized = rate * 3 * 365  # 3 payments/day * 365 days

    logging.info(f"{symbol} 8hr rate: {rate:.4%}, annualized: {annualized:.2%}")
    return rate, annualized

def open_arb_position(symbol='BTC/USDT:USDT'):
    """Open delta-neutral position: spot long + perp short."""
    ticker = exchange.fetch_ticker(symbol.replace(':USDT', ''))
    price = ticker['last']
    qty = POSITION_SIZE_USD / price

    # 1. Buy on spot
    spot_symbol = symbol.replace(':USDT', '')
    exchange.options['defaultType'] = 'spot'
    spot_order = exchange.create_market_buy_order(spot_symbol, qty)

    # 2. Short on perp
    exchange.options['defaultType'] = 'future'
    perp_order = exchange.create_market_sell_order(symbol, qty)

    logging.info(f"Opened arb: spot long {qty:.4f} + perp short {qty:.4f} at ${price:,.2f}")
    return spot_order, perp_order

def monitor_and_manage():
    rate, annualized = check_funding_opportunity('BTC/USDT:USDT')

    if annualized > ENTRY_THRESHOLD * 365 * 3 * 100:  # Simplified check
        logging.info("Funding rate attractive - opening/maintaining position")
    elif annualized < EXIT_THRESHOLD * 365 * 3 * 100:
        logging.info("Funding rate too low - consider closing position")

# Run every 8 hours (before funding payment)
schedule.every(8).hours.do(monitor_and_manage)
```

---

## Phase 5: Deployment & Infrastructure

### 5A. Where to Host Your Bot

**Option 1 (Free/Cheap): AWS EC2 t2.micro**
- Free tier for 12 months
- Steps:
  1. Create AWS account → EC2 → Launch Instance → Ubuntu 22.04
  2. Choose t2.micro (free tier eligible)
  3. Download key pair (.pem file)
  4. Connect via SSH: `ssh -i key.pem ubuntu@YOUR_IP`
  5. Install Python, copy your code, run bot

```bash
# On your EC2 instance
sudo apt update && sudo apt install python3 python3-pip git -y
pip3 install yfinance alpaca-py ccxt schedule python-telegram-bot
# Copy your code via git or scp
git clone https://github.com/you/trading_bot.git
cd trading_bot
python3 live/main_bot.py &  # Run in background
```

**Keep it running with screen or systemd:**
```bash
# Using screen (simplest)
screen -S trading_bot
python3 live/main_bot.py
# Ctrl+A, D to detach; screen -r trading_bot to reattach

# OR using systemd (more robust)
# Create /etc/systemd/system/trading-bot.service
```

**Option 2 (Simpler): Railway.app or Render.com**
- Free tier available, deploy from GitHub repo
- No server management needed

**Option 3 (Simplest for Daily Bot): GitHub Actions**
- Schedule a GitHub Action to run your bot script daily
- Completely free for public repos
- Store API keys as GitHub Secrets

```yaml
# .github/workflows/daily_trade.yml
name: Daily Trading Signal
on:
  schedule:
    - cron: '45 19 * * 1-5'  # 3:45 PM ET (19:45 UTC) Mon-Fri
jobs:
  trade:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install yfinance alpaca-py
      - run: python live/main_bot.py
        env:
          ALPACA_API_KEY: ${{ secrets.ALPACA_API_KEY }}
          ALPACA_SECRET_KEY: ${{ secrets.ALPACA_SECRET_KEY }}
```

### 5B. Security Best Practices
- Never commit API keys to git → Use environment variables or `.env` files
- Add `.env` to `.gitignore`
- Use read-only API keys for data, separate keys with trade permissions
- Enable IP whitelisting on crypto exchanges
- Set withdrawal limits to zero on all exchange API keys

```python
# Load keys safely with python-dotenv
from dotenv import load_dotenv
import os

load_dotenv()
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
```

---

## Phase 6: Going Live — Checklist

### Before You Touch Real Money

- [ ] **Backtest complete**: Strategy shows consistent edge on walk-forward test
- [ ] **Paper trade for 2+ weeks**: Bot runs in paper mode, results match expectations
- [ ] **Alerts working**: Telegram notifications confirmed on regime changes and errors
- [ ] **Error handling tested**: What happens if API is down? Data missing? Exchange error?
- [ ] **Position sizing set**: Using Quarter-Kelly or fixed % (never >5% per position to start)
- [ ] **Stop-loss set**: Max portfolio drawdown trigger (-15% → pause bot, review manually)
- [ ] **Log files working**: Every trade, regime change, and error is logged with timestamp
- [ ] **API keys secured**: No keys in git, IP whitelisted, withdrawals disabled on crypto

### Going Live

1. Switch `paper=True` to `paper=False` in Alpaca client
2. Change `ALPACA_BASE_URL` from paper to live endpoint
3. Start with **50% of intended capital** for first month
4. Monitor daily for first 2 weeks

### Ongoing Monitoring (Weekly)
- Review log files for errors or unexpected behavior
- Check that executed trades match the expected regime
- Track P&L vs expected (large deviations indicate slippage or data issues)
- Check funding rates weekly for crypto arb (rates change with market conditions)

---

## Phase 7: Iteration and Improvement

### Month 1–3: Baseline
- Run the basic Four Corners regime strategy
- Collect live trade data
- Don't touch parameters

### Month 3–6: Enhancement
- Add cross-sectional momentum layer (compare regime ETFs vs sector ETFs)
- Add VIX filter (downgrade regime when VIX > 25)
- Add credit spread filter (downgrade when HYG spread widens >200bps)

### Month 6–12: Advanced
- Add sentiment signal from Reddit/news API as secondary confirmation
- Explore crypto funding rate arb as non-correlated overlay
- Run Monte Carlo simulations on live data to validate edge persistence

### Signals the Strategy is Breaking Down
- Win rate drops below 45% over 60 trading days
- Max drawdown exceeds 25% (pause and review)
- Regime classifications feel "wrong" relative to what you observe in markets
- Sharpe drops below 0.8 on trailing 6-month basis

---

## Cost Summary

| Item | Cost |
|------|------|
| Python + libraries | Free |
| yfinance data | Free |
| FRED API | Free |
| Alpaca brokerage | Free (commissions $0 for stocks/ETFs) |
| Alpaca data (SIP) | $29/month (optional; free IEX tier works) |
| AWS EC2 t2.micro | Free (12 months), then ~$9/month |
| Binance/Bybit account | Free to open |
| Telegram bot | Free |
| **Total monthly** | **$0–$38/month** |

---

## Quick Start (TL;DR — Do This First)

```bash
# 1. Install everything
pip install yfinance alpaca-py ccxt pandas numpy schedule python-telegram-bot python-dotenv

# 2. Sign up for Alpaca (paper trading) at alpaca.markets

# 3. Create .env file with your keys:
echo "ALPACA_API_KEY=your_key" > .env
echo "ALPACA_SECRET_KEY=your_secret" >> .env

# 4. Copy strategy.py and main_bot.py from above

# 5. Run your first backtest:
python backtest/run_backtest.py

# 6. If Sharpe > 1.0, run paper trading for 2 weeks:
python live/main_bot.py

# 7. After 2 weeks of paper trading with good results, go live
```
