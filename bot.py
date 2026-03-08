import os
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta

# New Alpaca-py imports
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus

# --- CONFIGURATION ---
LOG_FILE = 'trades_log.csv'
ALPACA_KEY = os.getenv('APCA_KEY')
ALPACA_SECRET = os.getenv('APCA_SECRET')
FMP_TOKEN = os.getenv('FMP_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Initialize Modern Trading Client (Paper=True for testing)
trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)

def notify(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={message}"
    requests.get(url)

# --- MEMORY LOGIC ---
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

# --- SCREENING LOGIC ---
def is_passing_magic_momentum(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        hist = t.history(period="1y")
        if hist.empty: return False
        
        sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        if hist['Close'].iloc[-1] < sma200: return False
        
        info = t.info
        ebit = info.get('ebitda', 0)
        ev = info.get('enterpriseValue', 1)
        return (ebit / ev) > 0.05 
    except: return False

def get_clusters():
    url = f"https://financialmodelingprep.com/api/v3/senate_trading?apikey={FMP_TOKEN}"
    try:
        response = requests.get(url)
        data = response.json()
        df = pd.DataFrame(data)
        df['transactionDate'] = pd.to_datetime(df['transactionDate'])
        recent = df[df['transactionDate'] >= (datetime.now() - timedelta(days=30))]
        
        buys = recent[recent['type'].str.contains('Purchase', case=False)]
        sales = recent[recent['type'].str.contains('Sale', case=False)]
        
        buy_list = buys.groupby('symbol')['representative'].nunique()
        sell_list = sales.groupby('symbol')['representative'].nunique()
        
        return buy_list[buy_list >= 3].index.tolist(), sell_list[sell_list >= 3].index.tolist()
    except Exception as e:
        notify(f"⚠️ Data Fetch Error: {e}")
        return [], []

# --- MAIN EXECUTION ---
def main():
    cluster_buys, cluster_sales = get_clusters()
    # Updated: Use get_all_positions() for modern SDK
    positions = {p.symbol: p.qty for p in trading_client.get_all_positions()}

    # 1. PRIORITY: SELL CLUSTER SALES
    for ticker in list(positions.keys()):
        if ticker in cluster_sales:
            # New order format
            order_data = MarketOrderRequest(symbol=ticker, qty=positions[ticker], side=OrderSide.SELL, time_in_force=TimeInForce.GTC)
            trading_client.submit_order(order_data=order_data)
            update_memory(ticker, 'SELL')
            notify(f"🚨 SOLD: {ticker} (Cluster Sale)")

    # 2. ANNIVERSARY RE-EVALUATION
    if os.path.exists(LOG_FILE):
        log = pd.read_csv(LOG_FILE)
        log['purchase_date'] = pd.to_datetime(log['purchase_date'])
        one_year_ago = datetime.now() - timedelta(days=365)
        
        for _, row in log[log['purchase_date'] <= one_year_ago].iterrows():
            if not is_passing_magic_momentum(row['ticker']):
                order_data = MarketOrderRequest(symbol=row['ticker'], qty=row['qty'], side=OrderSide.SELL, time_in_force=TimeInForce.GTC)
                trading_client.submit_order(order_data=order_data)
                update_memory(row['ticker'], 'SELL')
                notify(f"⏳ SOLD: {row['ticker']} (1yr Review Fail)")

    # 3. NEW BUYS (Top 5)
    qualified_buys = [t for t in cluster_buys if t not in positions and is_passing_magic_momentum(t)]
    for ticker in qualified_buys[:5]:
        try:
            # Using notional ($1000) for fractional entry
            order_data = MarketOrderRequest(symbol=ticker, notional=1000, side=OrderSide.BUY, time_in_force=TimeInForce.GTC)
            trading_client.submit_order(order_data=order_data)
            update_memory(ticker, 'BUY', 0) 
            notify(f"✅ BOUGHT: {ticker} (Cluster + Magic Formula Pass)")
        except Exception as e:
            notify(f"❌ FAILED: {ticker} buy error: {e}")

if __name__ == "__main__":
    main()
