python
import websocket
import json
import time
from datetime import datetime
import requests
from textblob import TextBlob
import threading

# Deriv API Configuration
DERIV_API_URL = "wss://ws.deriv.com/websockets/v3"
DERIV_TOKEN = "YOUR_DERIV_API_TOKEN_HERE"  # Replace with your token
DERIV_ACCOUNT_ID = "1"  # Default account

# Trading Parameters
SYMBOL = "frxXAUUSD"  # Gold vs USD
TRADE_AMOUNT = 100  # Trade size in USD
STOP_LOSS_PIPS = 50  # Stop loss distance
TAKE_PROFIT_PIPS = 100  # Take profit distance

# Technical Indicator Settings
FAST_MA_PERIOD = 9
SLOW_MA_PERIOD = 21
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# Global Variables
ws = None
prices = []
last_trade_time = 0
in_trade = False
current_trade_id = None

def connect_deriv():
    """Connect to Deriv WebSocket API"""
    global ws
    try:
        ws = websocket.WebSocketApp(
            DERIV_API_URL,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        ws.on_open = on_open
        ws.run_forever()
    except Exception as e:
        print(f"Connection error: {e}")
        time.sleep(5)
        connect_deriv()

def on_open(ws):
    """Authenticate and subscribe to price updates"""
    print("[BOT] Connected to Deriv")
    auth_message = {
        "authorize": DERIV_TOKEN
    }
    ws.send(json.dumps(auth_message))
    time.sleep(1)
    
    # Subscribe to 1-minute candles for XAUUSD
    subscribe_message = {
        "ticks_history": SYMBOL,
        "adjust_start_time": 1,
        "count": 100,
        "granularity": 60,
        "style": "candles"
    }
    ws.send(json.dumps(subscribe_message))

def on_message(ws, message):
    """Handle incoming messages from Deriv"""
    global prices, in_trade, current_trade_id
    try:
        data = json.loads(message)
        
        # Handle price candle data
        if "candles" in data:
            for candle in data["candles"]:
                prices.append({
                    "open": candle["open"],
                    "high": candle["high"],
                    "low": candle["low"],
                    "close": candle["close"],
                    "time": candle["epoch"]
                })
            
            # Keep only last 100 candles for memory efficiency
            if len(prices) > 100:
                prices = prices[-100:]
            
            # Analyze and trade every 60 seconds
            analyze_and_trade()
        
        # Handle trade execution responses
        if "buy" in data:
            trade_response = data["buy"]
            print(f"[TRADE] Buy order executed: {trade_response}")
            in_trade = True
            current_trade_id = trade_response.get("transaction_id")
        
        if "sell" in data:
            trade_response = data["sell"]
            print(f"[TRADE] Sell order executed: {trade_response}")
            in_trade = False
    
    except Exception as e:
        print(f"Message error: {e}")

def on_error(ws, error):
    """Handle WebSocket errors"""
    print(f"[ERROR] {error}")

def on_close(ws, close_status_code, close_msg):
    """Handle WebSocket closure"""
    print("[BOT] Disconnected from Deriv. Reconnecting...")
    time.sleep(5)
    connect_deriv()

def fetch_gold_news_sentiment():
    """Fetch latest gold news and analyze sentiment"""
    try:
        # Query Google News RSS for gold price news
        url = "https://news.google.com/rss/search?q=gold+price+XAU+USD"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            # Simple sentiment extraction from headlines
            headlines = response.text.split("<title>")[1:6]  # Get first 5 headlines
            sentiments = []
            
            for headline in headlines:
                headline_text = headline.split("</title>")[0]
                blob = TextBlob(headline_text)
                polarity = blob.sentiment.polarity
                sentiments.append(polarity)
            
            if sentiments:
                avg_sentiment = sum(sentiments) / len(sentiments)
                return avg_sentiment
        
        return 0  # Neutral if no news
    except Exception as e:
        print(f"[NEWS] Error fetching news: {e}")
        return 0

def calculate_ma(period):
    """Calculate moving average"""
    if len(prices) < period:
        return None
    closes = [p["close"] for p in prices[-period:]]
    return sum(closes) / period

def calculate_rsi(period=14):
    """Calculate Relative Strength Index"""
    if len(prices) < period + 1:
        return 50
    
    closes = [p["close"] for p in prices[-(period+1):]]
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    
    gains = [d for d in deltas if d > 0]
    losses = [abs(d) for d in deltas if d < 0]
    
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    
    if avg_loss == 0:
        return 100 if avg_gain > 0 else 50
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def analyze_and_trade():
    """Analyze price action and execute trades"""
    global last_trade_time, in_trade
    
    if len(prices) < SLOW_MA_PERIOD:
        return
    
    current_time = time.time()
    
    # Trade only once per minute
    if current_time - last_trade_time < 60:
        return
    
    # Get current price
    current_price = prices[-1]["close"]
    
    # Calculate technical indicators
    fast_ma = calculate_ma(FAST_MA_PERIOD)
    slow_ma = calculate_ma(SLOW_MA_PERIOD)
    rsi = calculate_rsi(RSI_PERIOD)
    
    # Fetch news sentiment
    news_sentiment = fetch_gold_news_sentiment()
    
    # Trading signals
    bullish_signal = fast_ma > slow_ma and rsi < RSI_OVERBOUGHT and news_sentiment > 0.1
    bearish_signal = fast_ma < slow_ma and rsi > RSI_OVERSOLD and news_sentiment < -0.1
    
    print(f"[{datetime.now()}] Price: {current_price} | FastMA: {fast_ma} | SlowMA: {slow_ma} | RSI: {rsi} | Sentiment: {news_sentiment}")
    
    # Execute buy
    if bullish_signal and not in_trade:
        stop_loss = current_price - (STOP_LOSS_PIPS * 0.01)
        take_profit = current_price + (TAKE_PROFIT_PIPS * 0.01)
        
        buy_message = {
            "buy": 1,
            "price": current_price,
            "parameters": {
                "amount": TRADE_AMOUNT,
                "basis": "stake",
                "contract_type": "CALL",
                "currency": "USD",
                "duration": 1,
                "duration_unit": "m",
                "symbol": SYMBOL
            }
        }
        
        ws.send(json.dumps(buy_message))
        last_trade_time = current_time
        print(f"[BUY SIGNAL] Price: {current_price} | Stop Loss: {stop_loss} | Take Profit: {take_profit}")
    
    # Execute sell
    elif bearish_signal and not in_trade:
        stop_loss = current_price + (STOP_LOSS_PIPS * 0.01)
        take_profit = current_price - (TAKE_PROFIT_PIPS * 0.01)
        
        sell_message = {
            "sell": 1,
            "price": current_price,
            "parameters": {
                "amount": TRADE_AMOUNT,
                "basis": "stake",
                "contract_type": "PUT",
                "currency": "USD",
                "duration": 1,
                "duration_unit": "m",
                "symbol": SYMBOL
            }
        }
        
        ws.send(json.dumps(sell_message))
        last_trade_time = current_time
        print(f"[SELL SIGNAL] Price: {current_price} | Stop Loss: {stop_loss} | Take Profit: {take_profit}")

def main():
    """Start the bot"""
    print("[BOT] Starting Autonomous Gold Trading Bot for Deriv XAUUSD")
    print(f"[BOT] Trade Size: {TRADE_AMOUNT} USD | Stop Loss: {STOP_LOSS_PIPS} pips | Take Profit: {TAKE_PROFIT_PIPS} pips")
    
    # Start WebSocket connection in background thread
    ws_thread = threading.Thread(target=connect_deriv, daemon=True)
    ws_thread.start()
    
    # Keep bot running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[BOT] Shutting down...")
        if ws:
            ws.close()

if __name__ == "__main__":
    main()
