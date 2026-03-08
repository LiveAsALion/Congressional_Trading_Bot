import os
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta
from apify_client import ApifyClient

# Alpaca-py Imports
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# --- CONFIG ---
LOG_FILE = 'trades_log.csv'
ALPACA_KEY = os.getenv('APCA_KEY')
ALPACA_SECRET = os.getenv('APCA_SECRET')
APIFY_TOKEN = os.getenv('APIFY_TOKEN')
# Initialize Clients
trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)
apify_client = ApifyClient(APIFY_TOKEN)

def notify(message):
    url = f"https://api.telegram.org/bot{os.getenv('TELEGRAM_TOKEN')}/sendMessage"
    payload = {'chat_id': os.getenv('TELEGRAM_CHAT_ID'), 'text': message, 'parse_mode': 'Markdown'}
    requests.post(url, data=payload)

def update_memory(ticker, action, qty=0):
    if not os.path.exists(LOG_FILE):
        pd.DataFrame(columns=['ticker', 'purchase_date', 'qty']).to_csv(LOG_FILE, index=False)
    df = pd.read_csv(LOG_FILE)
    if action == 'BUY':
        new_row = {'ticker': ticker, 'purchase_date': datetime.now().strftime('%Y-%m-%d'), 'qty': qty}
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    elif action == 'SELL':
        df = df[df['ticker'] != ticker]
    df.to_csv(LOG_FILE, index=False)

def is_passing_magic_momentum(ticker):
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1y")
        if len(hist) < 200: return False
        sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        if hist['Close'].iloc[-1] < sma200: return False
        
        info = t.info
        ebit = info.get('ebitda', 0)
        ev = info.get('enterpriseValue', 1)
        return (ebit / ev) > 0.05
    except: return False

def get_automated_clusters():
    """Runs the Apify Capitol Trades Scraper and identifies clusters."""
    try:
        # Run Actor: saswave/capitol-trades-scraper
        run = apify_client.actor("saswave/capitol-trades-scraper").call()
        items = list(apify_client.dataset(run["defaultDatasetId"]).iterate_items())
        
        df = pd.DataFrame(items)
        # Assuming the scraper returns 'txDate' and 'politician' and 'asset'
        # We look for 3+ unique politicians in last 30 days
        df['pubDate'] = pd.to_datetime(df.get('pubDate', datetime.now()))
        recent = df[df['pubDate'] >= (datetime.now() - timedelta(days=30))]
        
        buys = recent[recent['txType'].str.contains('buy', case=False)]
        sales = recent[recent['txType'].str.contains('sell', case=False)]
        
        auto_buys = buys.groupby('asset').politician.nunique()
        auto_sales = sales.groupby('asset').politician.nunique()
        
        return auto_buys[auto_buys >= 3].index.tolist(), auto_sales[auto_sales >= 3].index.tolist()
    except Exception as e:
        print(f"Apify Error: {e}")
        return [], []

def main():
    # 1. Fetch Data
    auto_buys, auto_sales = get_automated_clusters()
    manual_buys = [t.strip().upper() for t in os.getenv('MANUAL_BUYS', '').split(',') if t.strip()]
    manual_sales = [t.strip().upper() for t in os.getenv('MANUAL_SALES', '').split(',') if t.strip()]
    
    all_buys = list(set(auto_buys + manual_buys))
    all_sales = list(set(auto_sales + manual_sales))
    
    # 2. Status Report
    acc = trading_client.get_account()
    pos_list = trading_client.get_all_positions()
    positions = {p.symbol: float(p.qty) for p in pos_list}
    notify(f"🤖 *Daily Bot Run Started*\nEquity: ${float(acc.equity):,.2f}\nPositions: {len(positions)}")

    # 3. SELL FIRST (Priority)
    for ticker in list(positions.keys()):
        if ticker in all_sales:
            order = MarketOrderRequest(symbol=ticker, qty=positions[ticker], side=OrderSide.SELL, time_in_force=TimeInForce.GTC)
            trading_client.submit_order(order)
            update_memory(ticker, 'SELL')
            notify(f"🚨 *SOLD:* {ticker} (Cluster/Manual Sale)")

    # 4. ANNIVERSARY RE-EVALUATION
    if os.path.exists(LOG_FILE):
        log = pd.read_csv(LOG_FILE)
        log['purchase_date'] = pd.to_datetime(log['purchase_date'])
        for _, row in log[log['purchase_date'] <= (datetime.now() - timedelta(days=365))].iterrows():
            if not is_passing_magic_momentum(row['ticker']):
                qty = positions.get(row['ticker'], 0)
                if qty > 0:
                    order = MarketOrderRequest(symbol=row['ticker'], qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.GTC)
                    trading_client.submit_order(order)
                    update_memory(row['ticker'], 'SELL')
                    notify(f"⏳ *ANNUAL SELL:* {row['ticker']} failed screen.")

    # 5. BUY SCREENING
    for ticker in all_buys:
        if ticker not in positions:
            if is_passing_magic_momentum(ticker):
                try:
                    order = MarketOrderRequest(symbol=ticker, notional=1000, side=OrderSide.BUY, time_in_force=TimeInForce.GTC)
                    trading_client.submit_order(order)
                    update_memory(ticker, 'BUY', 0)
                    notify(f"✅ *BOUGHT:* {ticker} (Passed Logic)")
                except Exception as e: notify(f"❌ *BUY ERROR:* {ticker}: {e}")
            else:
                notify(f"⚠️ *REJECTED:* {ticker} failed Magic/Momentum filters.")

if __name__ == "__main__":
    main()
