from flask import Flask, render_template, jsonify, request
import requests, traceback, os
from datetime import datetime, timedelta
import pytz

app = Flask(__name__)

# =================== CONFIG ===================
API_KEY = "b7ea33d435964da0b0a65b1c6a029891"   # fixed API key
PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/JPY", "AUD/CAD"]
TIMEZONE = pytz.timezone("Asia/Kolkata")  # Mumbai time

# store last results to avoid duplicate analysis
last_results = {}
last_candle_time = None


# =================== UTILS ===================
def get_current_candle_window():
    """Return current 5-min candle start and end in IST"""
    now = datetime.now(TIMEZONE)
    minute_block = now.minute - (now.minute % 5)  # round down to nearest 5
    start = now.replace(second=0, microsecond=0, minute=minute_block)
    end = start + timedelta(minutes=5)
    return start, end


def fetch_candles(pair, count=30):
    """Fetch last N candles from TwelveData"""
    symbol = pair.replace("/", "")
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=5min&outputsize={count}&apikey={API_KEY}"
    try:
        r = requests.get(url)
        data = r.json()
        return data.get("values", [])[::-1]  # reverse to oldest → newest
    except Exception as e:
        print("Error fetching:", pair, str(e))
        return []


def analyze_pair(pair, candles):
    """Apply simple VA-MOD + EMA + trend logic"""
    try:
        if not candles or len(candles) < 10:
            return {"signal": "NO DATA", "reason": "Not enough candles"}

        # Convert to float
        closes = [float(c["close"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]

        last_close = closes[-1]
        avg_price = sum(closes[-10:]) / 10
        vah = max(highs[-10:])
        val = min(lows[-10:])
        poc = sum(closes[-10:]) / 10  # midpoint

        # EMAs
        ema9 = sum(closes[-9:]) / 9
        ema21 = sum(closes[-21:]) / 21 if len(closes) >= 21 else sum(closes) / len(closes)

        # Logic
        if last_close > vah and ema9 > ema21:
            signal, reason = "CALL", "Breakout above VAH + EMA bullish"
        elif last_close < val and ema9 < ema21:
            signal, reason = "PUT", "Breakdown below VAL + EMA bearish"
        else:
            signal, reason = "NO TRADE", "Inside VA range or sideways"

        return {"signal": signal, "reason": reason}

    except Exception as e:
        return {"signal": "ERROR", "reason": str(e)}


# =================== ROUTES ===================
@app.route("/")
def index():
    return render_template("index.html", pairs=PAIRS)


@app.route("/analyze", methods=["POST"])
def analyze():
    global last_results, last_candle_time

    try:
        # Get current IST candle window
        candle_start, candle_end = get_current_candle_window()

        # If already analyzed for this candle → return stored results
        if last_candle_time == candle_start and last_results:
            return jsonify({
                "candle_start": candle_start.strftime("%H:%M"),
                "candle_end": candle_end.strftime("%H:%M"),
                "results": last_results,
                "note": "Reused last analysis"
            })

        # Fresh analysis
        results = {}
        for pair in PAIRS:
            candles = fetch_candles(pair, count=30)
            results[pair] = analyze_pair(pair, candles)

        # Save state
        last_candle_time = candle_start
        last_results = results

        return jsonify({
            "candle_start": candle_start.strftime("%H:%M"),
            "candle_end": candle_end.strftime("%H:%M"),
            "results": results,
            "note": "New analysis done"
        })

    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()})


# =================== RUN ===================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)