import os
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta

# Modern Alpaca-py imports
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# --- CONFIGURATION ---
LOG_FILE = 'trades_log.csv'
ALPACA_KEY = os.getenv('APCA_KEY')
ALPACA_SECRET = os.getenv('APCA_SECRET')
FMP_TOKEN = os.getenv('FMP_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)

def notify(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={message}"
    requests.get(url)

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

def is_passing_magic_momentum(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        hist = t.history(period="1y")
        if hist.empty or len(hist) < 200: return False
        
        sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        current_price = hist['Close'].iloc[-1]
        if current_price < sma200: return False
        
        info = t.info
        ebit = info.get('ebitda', 0)
        ev = info.get('enterpriseValue', 1)
        return (ebit / ev) > 0.05 
    except Exception: return False

def get_clusters():
    # Attempt FMP Premium. Fallback to empty if unauthorized.
    url = f"https://financialmodelingprep.com/api/v3/senate_trading?apikey={FMP_TOKEN}"
    try:
        r = requests.get(url)
        if r.status_code != 200: return [], []
        df = pd.DataFrame(r.json())
        df['transactionDate'] = pd.to_datetime(df['transactionDate'])
        recent = df[df['transactionDate'] >= (datetime.now() - timedelta(days=30))]
        buys = recent[recent['type'].str.contains('Purchase', case=False)].groupby('symbol')['representative'].nunique()
        sales = recent[recent['type'].str.contains('Sale', case=False)].groupby('symbol')['representative'].nunique()
        return buys[buys >= 3].index.tolist(), sales[sales >= 3].index.tolist()
    except: return [], []

def main():
    cluster_buys, cluster_sales = get_clusters()
    positions = {p.symbol: p.qty for p in trading_client.get_all_positions()}

    # 1. SELL CLUSTER SALES (Priority)
    for ticker in list(positions.keys()):
        if ticker in cluster_sales:
            order = MarketOrderRequest(symbol=ticker, qty=positions[ticker], side=OrderSide.SELL, time_in_force=TimeInForce.GTC)
            trading_client.submit_order(order)
            update_memory(ticker, 'SELL')
            notify(f"🚨 CLUSTER SELL: Liquidated {ticker}")

    # 2. ANNIVERSARY RE-EVALUATION
    if os.path.exists(LOG_FILE):
        log = pd.read_csv(LOG_FILE)
        log['purchase_date'] = pd.to_datetime(log['purchase_date'])
        for _, row in log[log['purchase_date'] <= (datetime.now() - timedelta(days=365))].iterrows():
            if not is_passing_magic_momentum(row['ticker']):
                order = MarketOrderRequest(symbol=row['ticker'], qty=positions.get(row['ticker'], 0), side=OrderSide.SELL, time_in_force=TimeInForce.GTC)
                trading_client.submit_order(order)
                update_memory(row['ticker'], 'SELL')
                notify(f"⏳ REVIEW SELL: {row['ticker']} failed annual screen.")

    # 3. CLUSTER BUYS
    for ticker in [t for t in cluster_buys if t not in positions][:5]:
        if is_passing_magic_momentum(ticker):
            try:
                order = MarketOrderRequest(symbol=ticker, notional=1000, side=OrderSide.BUY, time_in_force=TimeInForce.GTC)
                trading_client.submit_order(order)
                update_memory(ticker, 'BUY', 0)
                notify(f"✅ CLUSTER BUY: {ticker} purchased.")
            except Exception as e: notify(f"❌ BUY FAIL: {ticker} - {e}")

if __name__ == "__main__":
    main()
