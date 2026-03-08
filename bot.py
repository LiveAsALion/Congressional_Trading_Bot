import os
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta

# Modern Alpaca-py imports
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# --- CONFIG ---
LOG_FILE = 'trades_log.csv'
ALPACA_KEY = os.getenv('APCA_KEY')
ALPACA_SECRET = os.getenv('APCA_SECRET')
# Initialize Client
trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)

def notify(message):
    """Sends a formatted Markdown message to Telegram."""
    url = f"https://api.telegram.org/bot{os.getenv('TELEGRAM_TOKEN')}/sendMessage"
    payload = {
        'chat_id': os.getenv('CHAT_ID'),
        'text': message,
        'parse_mode': 'Markdown'
    }
    requests.post(url, data=payload)

def get_status_report():
    """Generates a summary of current holdings and account value."""
    try:
        account = trading_client.get_account()
        positions = trading_client.get_all_positions()
        
        report = f"📊 *Morning Portfolio Report*\n"
        report += f"💰 *Buying Power:* ${float(account.buying_power):,.2f}\n"
        report += f"📈 *Equity:* ${float(account.equity):,.2f}\n"
        report += "---" * 3 + "\n"
        
        if not positions:
            report += "No active positions."
        else:
            for p in positions:
                # Calculate simple P/L %
                pl_pct = (float(p.unrealized_plpc) * 100)
                emoji = "🟢" if pl_pct >= 0 else "🔴"
                report += f"{emoji} *{p.symbol}*: {p.qty} shares | {pl_pct:+.2f}%\n"
        
        return report
    except Exception as e:
        return f"❌ Error generating report: {e}"

def get_clusters():
    # Priority 1: Manual inputs from GitHub UI
    manual_buys = [t.strip().upper() for t in os.getenv('MANUAL_BUYS', '').split(',') if t.strip()]
    manual_sales = [t.strip().upper() for t in os.getenv('MANUAL_SALES', '').split(',') if t.strip()]
    return manual_buys, manual_sales

def is_passing_magic_momentum(ticker):
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1y")
        if len(hist) < 200: return False
        
        sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        current_price = hist['Close'].iloc[-1]
        if current_price < sma200: return False
        
        ebit = t.info.get('ebitda', 0)
        ev = t.info.get('enterpriseValue', 1)
        return (ebit / ev) > 0.05
    except: return False

def main():
    # --- PHASE 1: REPORTING ---
    report = get_status_report()
    notify(report)

    # --- PHASE 2: TRADING ---
    cluster_buys, cluster_sales = get_clusters()
    positions = {p.symbol: float(p.qty) for p in trading_client.get_all_positions()}

    # SELL FIRST
    for ticker in list(positions.keys()):
        if ticker in cluster_sales:
            order = MarketOrderRequest(symbol=ticker, qty=positions[ticker], side=OrderSide.SELL, time_in_force=TimeInForce.GTC)
            trading_client.submit_order(order)
            notify(f"🚨 *SOLD:* {ticker} (Manual/Cluster Trigger)")

    # BUY SECOND
    for ticker in cluster_buys:
        if ticker not in positions:
            if is_passing_magic_momentum(ticker):
                try:
                    order = MarketOrderRequest(symbol=ticker, notional=1000, side=OrderSide.BUY, time_in_force=TimeInForce.GTC)
                    trading_client.submit_order(order)
                    notify(f"✅ *BOUGHT:* {ticker} (Passed Screen)")
                except Exception as e: notify(f"❌ *FAIL:* {ticker} - {e}")
            else:
                notify(f"⚠️ *REJECTED:* {ticker} failed Magic/Momentum filters.")

if __name__ == "__main__":
    main()
