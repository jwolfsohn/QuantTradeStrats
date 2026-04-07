import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# Flip this to False when ready to trade real money
PAPER_TRADING = os.getenv("PAPER_TRADING", "True").lower() in ('true', '1', 't')

if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
    print("WARNING: Alpaca API keys are missing. Please set them in your .env file.")
