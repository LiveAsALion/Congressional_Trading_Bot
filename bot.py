import os
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta
from alpaca_trade_api.rest import REST, TimeInForce

# --- CONFIGURATION ---
LOG_FILE = 'trades_log.csv'
ALPACA_KEY = os.getenv('APCA_KEY')
ALPACA_SECRET = os.getenv('APCA_SECRET')
FMP_TOKEN = os.getenv('FMP_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

alpaca = REST(ALPACA_KEY, ALPACA_SECRET, base_url='https://paper-api.alpaca.markets')

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
        # Momentum filter
        sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        if hist['Close'].iloc[-1] < sma200: return False
        
        # Magic Formula Proxy
        info = t.info
        ebit = info.get('ebitda', 0)
        ev = info.get('enterpriseValue', 1)
        return (ebit / ev) > 0.05 # 5% Yield threshold
    except: return False

# --- DATA INGESTION ---
def get_clusters():
    # Fetching from Financial Modeling Prep Senate API
    url = f"https://financialmodelingprep.com/api/v3/senate_trading?apikey={FMP_TOKEN}"
    data = requests.get(url).json()
    df = pd.DataFrame(data)
    df['transactionDate'] = pd.to_datetime(df['transactionDate'])
    recent = df[df['transactionDate'] >= (datetime.now() - timedelta(days=30))]
    
    buys = recent[recent['type'].str.contains('Purchase', case=False)]
    sales = recent[recent['type'].str.contains('Sale', case=False)]
    
    # Identify 3+ member clusters
    buy_list = buys.groupby('symbol')['representative'].nunique()
    sell_list = sales.groupby('symbol')['representative'].nunique()
    
    return buy_list[buy_list >= 3].index.tolist(), sell_list[sell_list >= 3].index.tolist()

# --- MAIN EXECUTION ---
def main():
    cluster_buys, cluster_sales = get_clusters()
    positions = {p.symbol: p.qty for p in alpaca.list_positions()}

    # 1. PRIORITY: SELL CLUSTER SALES
    for ticker in list(positions.keys()):
        if ticker in cluster_sales:
            alpaca.submit_order(ticker, qty=positions[ticker], side='sell', type='market')
            update_memory(ticker, 'SELL')
            notify(f"🚨 SOLD: {ticker} (Congressional Cluster Sale detected)")

    # 2. ANNIVERSARY RE-EVALUATION
    if os.path.exists(LOG_FILE):
        log = pd.read_csv(LOG_FILE)
        log['purchase_date'] = pd.to_datetime(log['purchase_date'])
        one_year_ago = datetime.now() - timedelta(days=365)
        
        for _, row in log[log['purchase_date'] <= one_year_ago].iterrows():
            if not is_passing_magic_momentum(row['ticker']):
                alpaca.submit_order(row['ticker'], qty=row['qty'], side='sell', type='market')
                update_memory(row['ticker'], 'SELL')
                notify(f"⏳ SOLD: {row['ticker']} (Failed 1-year Magic Formula review)")

    # 3. NEW BUYS (Top 5)
    qualified_buys = [t for t in cluster_buys if t not in positions and is_passing_magic_momentum(t)]
    for ticker in qualified_buys[:5]:
        try:
            alpaca.submit_order(symbol=ticker, notional=1000, side='buy', type='market', time_in_force='gtc')
            update_memory(ticker, 'BUY', 0) # Qty will update on next run or via API
            notify(f"✅ BOUGHT: {ticker} (Cluster Buy + Magic Formula pass)")
        except Exception as e:
            notify(f"❌ FAILED: {ticker} purchase error: {e}")

if __name__ == "__main__":
    main()
