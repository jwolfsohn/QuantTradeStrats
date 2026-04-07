import os
import pandas as pd
from datetime import datetime
import yfinance as yf
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY

# Symbols needed for the Multi-Regime ETF Rotation Strategy
SYMBOLS = ["SPY", "QQQ", "TLT", "BIL"]

def fetch_yfinance_data():
    print("\nAttempting to fetch data from yfinance instead...")
    os.makedirs('data', exist_ok=True)
    
    try:
        data = yf.download(SYMBOLS, start="2007-01-01", interval="1d", progress=False)
        for symbol in SYMBOLS:
            # yfinance returns a MultiIndex columns dataframe if multiple symbols are passed
            # e.g., data['Close']['SPY']
            symbol_df = pd.DataFrame()
            for col in data.columns.levels[0]:
                symbol_df[col] = data[col][symbol]
                
            filepath = f"data/{symbol}_daily.csv"
            symbol_df.to_csv(filepath)
            print(f"Saved {symbol} data from yfinance to {filepath}")
        
        print("Data fetching complete via yfinance.")
    except Exception as e:
        print(f"Failed to fetch data using yfinance: {e}")

def fetch_historical_data():
    print("Using yfinance to fetch long-term historical data (from 2007) for robustness testing...")
    fetch_yfinance_data()
    return

    print("Connecting to Alpaca Historical Data API...")
    client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)

    request_params = StockBarsRequest(
        symbol_or_symbols=SYMBOLS,
        timeframe=TimeFrame.Day,
        start=datetime(2020, 1, 1)
    )

    print(f"Fetching daily data for {SYMBOLS} from 2020-01-01 via Alpaca...")
    try:
        bars = client.get_stock_bars(request_params)
        df_bars = bars.df
        
        # Ensure the 'data' directory exists
        os.makedirs('data', exist_ok=True)
        
        # Save to csv individually
        for symbol in SYMBOLS:
            if hasattr(df_bars, 'index') and 'symbol' in df_bars.index.names: 
                symbol_df = df_bars.loc[symbol]
                filepath = f"data/{symbol}_daily.csv"
                symbol_df.to_csv(filepath)
                print(f"Saved {symbol} data to {filepath}")
            else:
                 print(f"Failed to access data for {symbol}.")
            
        print("Data fetching complete.")
    except Exception as e:
        print(f"Failed to fetch data from Alpaca: {e}")
        # Automatically fallback to yfinance
        fetch_yfinance_data()

if __name__ == "__main__":
    fetch_historical_data()
