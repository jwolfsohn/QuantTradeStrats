import os
import sys
import signal
import schedule
import time
import json
import pandas as pd
import yfinance as yf
import logging
import glob
from datetime import date

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy import get_daily_macro_allocation, get_momentum_allocation
from live.execute_trades import rebalance_to_target, get_client

# ================================
# LOGGING SETUP
# ================================
BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BOT_DIR, 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

# Rotate active logs on startup
active_logs = glob.glob(os.path.join(LOGS_DIR, "bot_*_to_-.log"))
for active_log in active_logs:
    try:
        base = os.path.basename(active_log)
        start_date_str = base.replace("bot_", "").replace("_to_-.log", "")
        mtime = os.path.getmtime(active_log)
        end_date_str = pd.Timestamp.fromtimestamp(mtime, tz="America/New_York").strftime("%m-%d-%Y_%H-%M")
        archived_name = os.path.join(LOGS_DIR, f"bot_{start_date_str}_to_{end_date_str}.log")
        os.rename(active_log, archived_name)
    except Exception as e:
        print(f"Log rotation error: {e}")

legacy_log = os.path.join(LOGS_DIR, "bot.log")
if os.path.exists(legacy_log):
    mtime = os.path.getmtime(legacy_log)
    end_date_str = pd.Timestamp.fromtimestamp(mtime, tz="America/New_York").strftime("%m-%d-%Y_%H-%M")
    os.rename(legacy_log, os.path.join(LOGS_DIR, f"bot_legacy_to_{end_date_str}.log"))

current_time_str = pd.Timestamp.now(tz="America/New_York").strftime("%m-%d-%Y_%H-%M")
NEW_LOG_FILE = os.path.join(LOGS_DIR, f"bot_{current_time_str}_to_-.log")

logging.basicConfig(
    filename=NEW_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

STATE_FILE = os.path.join(LOGS_DIR, "target_state.json")


# ================================
# STATE MANAGEMENT
# ================================
def load_master_state() -> dict:
    """Loads the persistent portfolio weight matrix."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"SPY": 0.33, "QQQ": 0.0, "TLT": 0.0, "BIL": 0.67, "GLD": 0.0, "XLE": 0.0}


def save_master_state(state: dict):
    """Saves the portfolio weight matrix to disk."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def print_state(state: dict):
    logging.info("-" * 30)
    logging.info("CURRENT MASTER STATE WEIGHTS:")
    for sym, w in state.items():
        if w != 0:
            logging.info(f"{sym:5} | {w * 100:6.2f}%")
    logging.info("-" * 30)


# ================================
# MARKET CALENDAR
# ================================
def was_trading_day_today() -> bool:
    """
    Check if today is a valid NYSE trading session using the Alpaca calendar API.
    Handles holidays and early closes automatically. Falls back to weekday check.
    """
    try:
        from alpaca.trading.requests import GetCalendarRequest
        today_str = date.today().isoformat()
        calendar = get_client().get_calendar(GetCalendarRequest(start=today_str, end=today_str))
        return len(calendar) > 0
    except Exception:
        now = pd.Timestamp.now(tz="America/New_York")
        return now.weekday() < 5


# ================================
# STRATEGY EXECUTION
# ================================
def run_daily_macro_check():
    """
    Run at 16:05 ET on weekdays. Downloads EOD data, evaluates both strategy
    sleeves, merges allocations, saves state, and rebalances via Alpaca.
    """
    logging.info("Starting Daily EOD evaluation...")

    if not was_trading_day_today():
        logging.info("Market holiday detected — skipping EOD evaluation.")
        return

    try:
        # Download data for both sleeves
        tickers = ["SPY", "QQQ", "TLT", "GLD", "XLE"]
        data = yf.download(tickers, period="2mo", interval="1d", progress=False)
        close_data = data['Close'] if isinstance(data.columns, pd.MultiIndex) else data

        spy_df = pd.DataFrame({'Close': close_data['SPY']})
        momentum_df = pd.DataFrame({
            sym: close_data[sym] for sym in ['QQQ', 'TLT', 'GLD', 'XLE']
            if sym in close_data.columns
        })

        # Sleeve 1: Target Volatility Core (65%)
        macro_targets = get_daily_macro_allocation(spy_df)

        # Sleeve 2: Cross-Sectional Momentum (35%)
        momentum_targets = get_momentum_allocation(momentum_df)

        # Merge — BIL contributions from both sleeves are summed
        combined = {}
        for k, v in macro_targets.items():
            combined[k] = combined.get(k, 0.0) + v
        for k, v in momentum_targets.items():
            combined[k] = combined.get(k, 0.0) + v

        # Persist and execute
        save_master_state(combined)
        print_state(combined)
        rebalance_to_target(combined)

    except Exception as e:
        logging.error(f"Error in daily macro check: {e}")


# ================================
# GRACEFUL SHUTDOWN
# ================================
def graceful_shutdown(signum, _frame):
    logging.info(f"Received signal {signum}. Shutting down gracefully...")
    try:
        get_client().cancel_orders()
        logging.info("Cancelled all pending orders on shutdown.")
    except Exception as e:
        logging.error(f"Error cancelling orders on shutdown: {e}")
    sys.exit(0)

signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)


# ================================
# SCHEDULER
# ================================
for day in [schedule.every().monday, schedule.every().tuesday,
            schedule.every().wednesday, schedule.every().thursday, schedule.every().friday]:
    day.at("16:05", "America/New_York").do(run_daily_macro_check)


def manual_run():
    print("Executing manual force run...")
    run_daily_macro_check()


if __name__ == "__main__":
    # Startup recovery: clear any stale overnight flag left by old strategy
    stale_state = load_master_state()
    if stale_state.get("_OVERNIGHT_SPY_ACTIVE", 0.0) > 0.0:
        logging.warning(
            "Found stale _OVERNIGHT_SPY_ACTIVE in state — old strategy artifact. "
            "Merging into SPY weight and clearing flag."
        )
        stale_state["SPY"] = stale_state.get("SPY", 0.0) + stale_state.pop("_OVERNIGHT_SPY_ACTIVE")
        save_master_state(stale_state)

    if len(sys.argv) > 1 and sys.argv[1] == "--now":
        manual_run()
    else:
        logging.info("Bot scheduler started.")
        logging.info("- EOD macro + momentum evaluation: Weekdays at 16:05 ET")
        while True:
            schedule.run_pending()
            time.sleep(60)
