import websocket
import json
import time
from datetime import datetime
import requests
import threading

# ===== CONFIGURATION - ADJUST THESE SETTINGS =====
DERIV_API_TOKEN = pat_1d06caa1e918446eb10fdd638da2da09c5f9769d81fbf07137eb45fda98039d6  # Replace with your actual token
LOT_SIZE = 0.02  # Change this to 0.01, 0.05, 0.1, 0.2, etc. as you prefer
GOLD_SYMBOL = "frxXAUUSD"
STOP_LOSS_PERCENT = 2.0
TAKE_PROFIT_PERCENT = 3.0
FAST_MA_PERIOD = 9
SLOW_MA_PERIOD = 21
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
# ===================================================

DERIV_API_URL = "wss://ws.deriv.com/websockets/v3"

ws = None
prices = []
last_trade_time = 0
in_trade = False


def connect_deriv():
    global ws
    try:
        ws = websocket.WebSocketApp(
            DERIV_API_URL,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        ws.run_forever()
    except Exception as e:
        print(f"[BOT] Connection error: {e}")
        time.sleep(5)
        connect_deriv()


def on_open(ws):
    print("[BOT] Connected to Deriv")
    ws.send(json.dumps({"authorize": DERIV_API_TOKEN}))
    time.sleep(1)
    ws.send(json.dumps({
        "ticks_history": GOLD_SYMBOL,
        "adjust_start_time": 1,
        "count": 100,
        "granularity": 60,
        "style": "candles",
        "subscribe": 1
    }))


def on_message(ws, message):
    global prices
    try:
        data = json.loads(message)

        if "candles" in data:
            for candle in data["candles"]:
                prices.append({
                    "open": candle["open"],
                    "high": candle["high"],
                    "low": candle["low"],
                    "close": candle["close"],
                    "time": candle["epoch"]
                })
            if len(prices) > 100:
                prices = prices[-100:]
            analyze_and_trade()

        if "ohlc" in data:
            candle = data["ohlc"]
            prices.append({
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "time": candle["epoch"]
            })
            if len(prices) > 100:
                prices = prices[-100:]
            analyze_and_trade()

        if "buy" in data:
            print(f"[TRADE] Buy order executed: {data['buy']}")

        if "error" in data:
            print(f"[DERIV ERROR] {data['error'].get('message')}")

    except Exception as e:
        print(f"[BOT] Message handling error: {e}")


def on_error(ws, error):
    print(f"[BOT] WebSocket error: {error}")


def on_close(ws, close_status_code, close_msg):
    print("[BOT] Disconnected. Reconnecting in 5 seconds...")
    time.sleep(5)
    connect_deriv()


def fetch_gold_news_sentiment():
    try:
        url = "https://news.google.com/rss/search?q=gold%20price%20XAU%20USD"
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            return 0

        text = response.text
        headlines = []
        parts = text.split("<title>")
        for part in parts[2:12]:  # skip feed title, grab article titles
            headline = part.split("</title>")[0]
            headlines.append(headline)

        if not headlines:
            return 0

        positive_words = ["rise", "surge", "gain", "rally", "bullish", "high", "up", "soar", "jump"]
        negative_words = ["fall", "drop", "decline", "bearish", "low", "down", "plunge", "crash", "slump"]

        score = 0
        for h in headlines:
            h_lower = h.lower()
            score += sum(1 for w in positive_words if w in h_lower)
            score -= sum(1 for w in negative_words if w in h_lower)

        return score / max(len(headlines), 1)

    except Exception as e:
        print(f"[NEWS] Error fetching news: {e}")
        return 0


def calculate_ma(period):
    if len(prices) < period:
        return None
    closes = [p["close"] for p in prices[-period:]]
    return sum(closes) / period


def calculate_rsi(period=14):
    if len(prices) < period + 1:
        return 50
    closes = [p["close"] for p in prices[-(period + 1):]]
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d for d in deltas if d > 0]
    losses = [abs(d) for d in deltas if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100 if avg_gain > 0 else 50
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def analyze_and_trade():
    global last_trade_time, in_trade

    if len(prices) < SLOW_MA_PERIOD:
        return

    current_time = time.time()
    if current_time - last_trade_time < 60:
        return

    current_price = prices[-1]["close"]
    fast_ma = calculate_ma(FAST_MA_PERIOD)
    slow_ma = calculate_ma(SLOW_MA_PERIOD)
    rsi = calculate_rsi(RSI_PERIOD)
    news_sentiment = fetch_gold_news_sentiment()

    bullish = fast_ma is not None and slow_ma is not None and fast_ma > slow_ma and rsi < RSI_OVERBOUGHT and news_sentiment > 0.1
    bearish = fast_ma is not None and slow_ma is not None and fast_ma < slow_ma and rsi > RSI_OVERSOLD and news_sentiment < -0.1

    print(f"[{datetime.now()}] Price:{current_price} FastMA:{fast_ma} SlowMA:{slow_ma} RSI:{rsi:.1f} Sentiment:{news_sentiment:.2f}")

    if bullish and not in_trade:
        place_trade("CALL", current_price)
        last_trade_time = current_time
    elif bearish and not in_trade:
        place_trade("PUT", current_price)
        last_trade_time = current_time


def place_trade(contract_type, current_price):
    global in_trade
    buy_message = {
        "buy": 1,
        "price": LOT_SIZE * 1000,  # stake scales with lot size
        "parameters": {
            "amount": LOT_SIZE * 1000,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": "USD",
            "duration": 5,
            "duration_unit": "m",
            "symbol": GOLD_SYMBOL
        }
    }
    ws.send(json.dumps(buy_message))
    in_trade = True
    print(f"[TRADE] {contract_type} order sent at price {current_price} | Lot size: {LOT_SIZE}")


def main():
    print("[BOT] Starting Autonomous Gold Trading Bot for Deriv XAUUSD")
    print(f"[BOT] Lot Size: {LOT_SIZE} | Stop Loss: {STOP_LOSS_PERCENT}% | Take Profit: {TAKE_PROFIT_PERCENT}%")

    ws_thread = threading.Thread(target=connect_deriv, daemon=True)
    ws_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[BOT] Shutting down...")
        if ws:
            ws.close()


if __name__ == "__main__":
    main()
