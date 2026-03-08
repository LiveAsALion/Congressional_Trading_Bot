import os
import requests
import pandas as pd
import yfinance as yf
from alpaca_trade_api.rest import REST, TimeInForce

# API Configuration
ALPACA_CLIENT = REST(os.getenv('APCA_KEY'), os.getenv('APCA_SECRET'), base_url='https://paper-api.alpaca.markets')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def notify(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={message}"
    requests.get(url)

def get_capitol_trades_data():
    """
    Scrapes or fetches the latest cluster data. 
    Note: For production, use an Apify actor or CapitolTrades API key.
    """
    # Logic to identify stocks with 3+ unique congress members trading
    return {"buys": ["NVDA", "MSFT", "AAPL"], "sales": ["GOOGL", "TSLA"]} 

def magic_formula_momentum_screen(tickers):
    qualified = []
    for symbol in tickers:
        try:
            ticker = yf.Ticker(symbol)
            # 1. Momentum Check (Price > 200 SMA)
            hist = ticker.history(period="1y")
            sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
            current_price = hist['Close'].iloc[-1]
            
            if current_price > sma200:
                # 2. Magic Formula (Simplified EBIT/EV and ROC)
                info = ticker.info
                ebit = info.get('ebitda', 0) # Proxy for EBIT
                ev = info.get('enterpriseValue', 1)
                yield_score = ebit / ev
                
                if yield_score > 0.05: # Threshold for 'cheap'
                    qualified.append(symbol)
        except: continue
    return qualified[:5]

def main():
    data = get_capitol_trades_data()
    positions = [p.symbol for p in ALPACA_CLIENT.list_positions()]

    # --- STEP 1: SELL CLUSTER SALES (Priority) ---
    for ticker in positions:
        if ticker in data['sales']:
            ALPACA_CLIENT.submit_order(ticker, qty=1, side='sell', type='market')
            notify(f"🚨 CLUSTER SALE: Liquidated {ticker} based on CapitolTrades signal.")

    # --- STEP 2: ANNIVERSARY RE-EVALUATION ---
    # (Requires a local CSV/JSON to track purchase dates)

    # --- STEP 3: EXECUTE CLUSTER BUYS ---
    buy_candidates = magic_formula_momentum_screen(data['buys'])
    for ticker in buy_candidates:
        if ticker not in positions:
            try:
                ALPACA_CLIENT.submit_order(symbol=ticker, notional=1000, side='buy', type='market', time_in_force='gtc')
                notify(f"✅ PURCHASE: {ticker} passed Cluster + Magic Formula screen.")
            except Exception as e:
                notify(f"❌ FAILURE: Could not purchase {ticker}. Error: {e}")

if __name__ == "__main__":
    main()
