# Trading Bot Terminal Cheatsheet

Run these commands from the root directory (`/Users/jackwolfsohn/QuantTradingStrategies`).

## 1. Checking Bot Status
To check if the live bot process is currently running in the background:
```bash
ps aux | grep "[m]ain_bot.py"
```
*(If no output appears, the bot is not running. If a line appears with numbers and the script name, it is running!)*

## 2. Starting the Bot
To start the bot in your current terminal (will stop if you close the window):
```bash
python3 trading_bot/live/main_bot.py
```

To start the bot safely in the **background** so it keeps running even if you close the terminal:
```bash
nohup python3 trading_bot/live/main_bot.py > /dev/null 2>&1 &
```

## 3. Stopping the Bot
To forcefully kill any running instance of the live bot (for example, to stop it or before restarting it):
```bash
pkill -f main_bot.py
```

## 4. Restarting the Bot (Background)
Simply chain the kill and start commands:
```bash
pkill -f main_bot.py && nohup python3 trading_bot/live/main_bot.py > /dev/null 2>&1 &
```

## 5. Running the Backtester
To run the historical backtest suite and view the portfolio metrics:
```bash
python3 trading_bot/backtest/run_multi_strategy_backtest.py
```

## 6. Manual Strategy Force-Run
If for any reason you want to force an execution cycle instantly instead of waiting for the schedule:
```bash
python3 trading_bot/live/main_bot.py --now
```
