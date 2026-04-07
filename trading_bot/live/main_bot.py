import os
import sys
import schedule
import time
import json
import pandas as pd
import yfinance as yf
import logging
import glob

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy import get_daily_macro_allocation, get_hourly_statarb_allocation
from live.execute_trades import rebalance_to_target

# Configure absolute logging & state paths
BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BOT_DIR, 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

# 1. Rotate active logs
active_logs = glob.glob(os.path.join(LOGS_DIR, "bot_*_to_-.log"))
for active_log in active_logs:
    try:
        base = os.path.basename(active_log)
        start_date_str = base.replace("bot_", "").replace("_to_-.log", "")
        mtime = os.path.getmtime(active_log)
        end_date_str = pd.Timestamp.fromtimestamp(mtime, tz="America/New_York").strftime("%Y%m%d_%H%M")
        archived_name = os.path.join(LOGS_DIR, f"bot_{start_date_str}_to_{end_date_str}.log")
        os.rename(active_log, archived_name)
    except Exception as e:
        print(f"Log rotation error: {e}")

# 2. Handle legacy bot.log
legacy_log = os.path.join(LOGS_DIR, "bot.log")
if os.path.exists(legacy_log):
    mtime = os.path.getmtime(legacy_log)
    end_date_str = pd.Timestamp.fromtimestamp(mtime, tz="America/New_York").strftime("%Y%m%d_%H%M")
    os.rename(legacy_log, os.path.join(LOGS_DIR, f"bot_legacy_to_{end_date_str}.log"))

# 3. Create new active log
current_time_str = pd.Timestamp.now(tz="America/New_York").strftime("%Y%m%d_%H%M")
NEW_LOG_FILE = os.path.join(LOGS_DIR, f"bot_{current_time_str}_to_-.log")

logging.basicConfig(
    filename=NEW_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

STATE_FILE = os.path.join(LOGS_DIR, "target_state.json")

def load_master_state():
    """Loads the resilient state so the bot knows what the other strategies did."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"QQQ": 0.0, "TLT": 0.0, "BIL": 0.3333, "SVXY": 0.0, "EWA": 0.0, "EWC": 0.0, "TQQQ": 0.0, "SQQQ": 0.0}

def save_master_state(state):
    """Saves the absolute master portfolio weight matrix."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def is_market_open():
    """Simple safety check - optional enhancements to strict holiday calendars later."""
    now = pd.Timestamp.now(tz="America/New_York")
    if now.weekday() >= 5: # Sat/Sun
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close

def run_daily_macro_check():
    """Run ONLY at market close to determine End-Of-Day macro allocations."""
    logging.info("Starting Daily Macro evaluation...")
    print("\nExecuting End-of-Day Macro, VRP, and TSMOM Evaluation...")
    try:
        # Added QQQ to the matrix
        data = yf.download(["SPY", "^VIX", "QQQ"], period="1y", interval="1d", progress=False)
        close_data = data['Close']
        if isinstance(data.columns, pd.MultiIndex):
            spy_df = pd.DataFrame({'Close': close_data['SPY']})
            vix_df = pd.DataFrame({'Close': close_data['^VIX']})
            qqq_df = pd.DataFrame({'Close': close_data['QQQ']})
        else:
            return

        macro_targets = get_daily_macro_allocation(spy_df, vix_df, qqq_df)

        # Merge with master state
        state = load_master_state()
        state.update(macro_targets) 
        
        # Save and Execute
        save_master_state(state)
        print_state(state)
        rebalance_to_target(state)

    except Exception as e:
        logging.error(f"Error in macro check: {e}")

def run_hourly_statarb_check():
    """Run hourly during market hours to hunt for intraday pairs divergence."""
    if not is_market_open() and "--now" not in sys.argv:
        print("Market is closed. Skipping intraday StatArb execution.")
        return

    logging.info("Starting Hourly StatArb hunt...")
    print("\nExecuting Intraday StatArb Evaluation...")
    try:
        data = yf.download(["EWA", "EWC"], period="1mo", interval="1h", progress=False)
        close_data = data['Close']
        pair_df = pd.DataFrame({'EWA': close_data['EWA'], 'EWC': close_data['EWC']})

        statarb_targets = get_hourly_statarb_allocation(pair_df)

        state = load_master_state()
        state["EWA"] = statarb_targets["EWA"]
        state["EWC"] = statarb_targets["EWC"]
        
        save_master_state(state)
        print_state(state)
        rebalance_to_target(state)

    except Exception as e:
        logging.error(f"Error in statarb check: {e}")

def print_state(state):
    print("-" * 30)
    print("CURRENT MASTER SECURE STATE WEIGHTS:")
    for sym, w in state.items():
        if w != 0:
            print(f"{sym:5} | {w*100:6.2f}%")
    print("-" * 30)

# ================================
# SCHEDULER
# ================================
for day in [schedule.every().monday, schedule.every().tuesday, 
            schedule.every().wednesday, schedule.every().thursday, schedule.every().friday]:
    day.at("15:45", "America/New_York").do(run_daily_macro_check)

schedule.every().hour.at(":15").do(run_hourly_statarb_check)


def manual_run():
    print("Executing force tests...")
    run_hourly_statarb_check()
    run_daily_macro_check()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--now":
        manual_run()
    else:
        print("Bot decoupled scheduler started.")
        print("- StatArb bounds checking: Every hour at X:15")
        print("- Macro/VRP/TSMOM evaluation: Weekdays at 15:45 ET")
        logging.info("Bot scheduler started.")
        while True:
            schedule.run_pending()
            time.sleep(60)
