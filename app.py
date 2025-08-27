from flask import Flask, render_template, jsonify
import requests, os, traceback
from datetime import datetime
import pytz
import numpy as np
import pandas as pd

app = Flask(__name__)

# =================== CONFIG ===================
API_KEY = "b7ea33d435964da0b0a65b1c6a029891"
PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/JPY", "AUD/CAD"]
INTERVAL = "5min"
CANDLES = 30
TIMEZONE = pytz.timezone("Asia/Kolkata")

# =================== STORAGE ===================
cached_data = {}   # {pair: DataFrame}
last_analysis = {} # {pair: {candle_time: result}}

# =================== HELPERS ===================
def fetch_candles(symbol):
    try:
        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={INTERVAL}&outputsize={CANDLES}&apikey={API_KEY}"
        r = requests.get(url).json()
        if "values" not in r: return None
        df = pd.DataFrame(r["values"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        df[["open","high","low","close","volume"]] = df[["open","high","low","close","volume"]].astype(float)
        return df
    except Exception as e:
        print("Fetch error:", e)
        return None

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def detect_profile(df):
    """ Detect B/D/P/b volume profile type """
    try:
        closes = df["close"].values
        vols = df["volume"].values
        # bucket prices into ~10 bins
        bins = np.linspace(min(closes), max(closes), 10)
        hist, _ = np.histogram(closes, bins=bins, weights=vols)
        peak_idx = np.argmax(hist)

        # crude shape detection
        if peak_idx in [0, len(hist)-1]:
            return "B"  # breakout
        elif peak_idx < len(hist)//3:
            return "b"  # bearish
        elif peak_idx > 2*len(hist)//3:
            return "P"  # bullish
        else:
            return "D"  # balanced
    except:
        return "D"

def analyze_pair(symbol):
    global cached_data, last_analysis

    now = datetime.now(TIMEZONE)
    current_candle_time = now.replace(second=0, microsecond=0, minute=(now.minute//5)*5)

    # reuse if already analyzed
    if symbol in last_analysis and last_analysis[symbol]["candle_time"] == current_candle_time:
        return last_analysis[symbol]["result"]

    # fetch new if not cached
    if symbol not in cached_data:
        df = fetch_candles(symbol)
        if df is None: return {"error": "Data fetch failed"}
        cached_data[symbol] = df
    else:
        # check if a new candle formed
        latest_df = fetch_candles(symbol)
        if latest_df is not None and latest_df["datetime"].iloc[-1] > cached_data[symbol]["datetime"].iloc[-1]:
            cached_data[symbol] = pd.concat([cached_data[symbol], latest_df.tail(1)], ignore_index=True)

    df = cached_data[symbol].copy()
    if len(df) < 20: return {"error": "Not enough candles"}

    # trend filters
    df["ema9"] = ema(df["close"], 9)
    df["ema21"] = ema(df["close"], 21)
    df["ema50"] = ema(df["close"], 50)

    last = df.iloc[-1]
    direction = "No Trade"
    reason = []

    # EMA logic
    if last["ema9"] > last["ema21"] and last["ema21"] > last["ema50"]:
        trend = "up"
        reason.append("EMA bullish alignment")
    elif last["ema9"] < last["ema21"] and last["ema21"] < last["ema50"]:
        trend = "down"
        reason.append("EMA bearish alignment")
    else:
        trend = "side"
        reason.append("EMA mixed")

    # Volume profile
    profile = detect_profile(df)
    reason.append(f"Volume Profile = {profile}")

    if profile == "P" and trend == "up":
        direction = "CALL"
    elif profile == "b" and trend == "down":
        direction = "PUT"
    elif profile == "D":
        direction = "No Trade"
    elif profile == "B":
        direction = "Breakout Watch"

    result = {
        "pair": symbol,
        "time": current_candle_time.strftime("%H:%M"),
        "signal": direction,
        "trend": trend,
        "profile": profile,
        "accuracy": "70%",  # placeholder
        "reason": "; ".join(reason)
    }

    last_analysis[symbol] = {"candle_time": current_candle_time, "result": result}
    return result

# =================== ROUTES ===================
@app.route("/")
def index():
    return render_template("index.html", pairs=PAIRS)

@app.route("/analyze")
def analyze():
    results = {}
    for p in PAIRS:
        try:
            results[p] = analyze_pair(p)
        except Exception as e:
            traceback.print_exc()
            results[p] = {"error": str(e)}
    return jsonify(results)

# =================== MAIN ===================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
