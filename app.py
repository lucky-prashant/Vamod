from flask import Flask, render_template, jsonify, send_file, request
import os, time, math, csv, traceback, threading, requests
from collections import defaultdict, deque
from datetime import datetime, timedelta

# ---------- Config (hardcoded for GitHub/Render deploy) ----------
API_KEY = "b7ea33d435964da0b0a65b1c6a029891"  # hardcoded Twelve Data API key as requested
PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/JPY", "AUD/CAD"]
PRIMARY_INTERVAL = "5min"
CONFIRM_INTERVAL = "15min"  # set to "off" to disable confirmation
CONFIRM_ENABLE = CONFIRM_INTERVAL.lower() not in ("", "off", "none")
LOOKBACK = 80
VALUE_AREA_PCT = 0.70
MIN_BODY_PCT = 0.35
IST_OFFSET_HOURS = 5.5  # IST offset used if zoneinfo not available

# Scanner settings
ENABLE_SCANNER = True
SCAN_DELAY_SEC = 3
SCAN_INTERVAL_SEC = 15

# Alerts (leave empty to disable)
WEBHOOK_URL = ""
TG_BOT_TOKEN = ""
TG_CHAT_ID = ""

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# ---------- App Init ----------
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = None

def ist_now():
    if IST:
        return datetime.now(IST)
    return datetime.utcnow() + timedelta(hours=IST_OFFSET_HOURS)

def ist_now_str():
    return ist_now().strftime("%Y-%m-%d %H:%M:%S IST")

app = Flask(__name__)
STATE = {
    "series": {p: [] for p in PAIRS},
    "last_ts": {p: None for p in PAIRS},
    "errors": deque(maxlen=200),
    "last_scan_ist": None
}

# ---------- Data Fetch ----------
def td_fetch(symbol, interval, outputsize):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "order": "ASC",
        "format": "JSON",
        "dp": 6,
        "apikey": API_KEY
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if "values" not in data:
        raise RuntimeError(f"TwelveData error for {symbol} {interval}: {data}")
    out = []
    for row in data["values"]:
        try:
            out.append({
                "time": row["datetime"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 1.0)) if row.get("volume") not in (None, "", "None") else 1.0
            })
        except Exception:
            continue
    out.sort(key=lambda x: x["time"])
    return out

def ensure_series(symbol, interval, lookback):
    if interval != PRIMARY_INTERVAL:
        return td_fetch(symbol, interval, lookback)
    ser = STATE["series"][symbol]
    last_ts = STATE["last_ts"][symbol]
    if not ser:
        ser = td_fetch(symbol, interval, lookback)
        STATE["series"][symbol] = ser
        STATE["last_ts"][symbol] = ser[-1]["time"] if ser else None
        return ser
    latest = td_fetch(symbol, interval, 4)
    if not latest:
        return ser
    latest_ts = latest[-1]["time"]
    if last_ts is None or latest_ts > last_ts:
        have = {c["time"] for c in ser}
        for c in latest:
            if c["time"] not in have:
                ser.append(c)
        STATE["series"][symbol] = ser[-lookback:]
        STATE["last_ts"][symbol] = STATE["series"][symbol][-1]["time"]
    return STATE["series"][symbol]

# ---------- Indicators & Helpers ----------
def round_tick(symbol, price):
    tick = 0.01 if "JPY" in symbol else 0.0001
    return round(round(price / tick) * tick, 2 if tick == 0.01 else 4)

def compute_emas(closes, periods=(9,21,50)):
    out = {}
    for p in periods:
        k = 2/(p+1); ema = None; arr = []
        for px in closes:
            ema = px if ema is None else (px * k + ema * (1 - k))
            arr.append(ema)
        out[p] = arr
    return out

def atr14(candles):
    if len(candles) < 15:
        return 0.0
    trs = []
    prev = candles[0]["close"]
    for c in candles[1:]:
        trs.append(max(c["high"] - c["low"], abs(c["high"] - prev), abs(c["low"] - prev)))
        prev = c["close"]
    use = trs[-14:] if len(trs) >= 14 else trs
    return sum(use) / len(use) if use else 0.0

def build_volume_profile(symbol, candles, value_area_pct):
    from collections import defaultdict
    bins = defaultdict(float)
    for c in candles:
        typ = (c["high"] + c["low"] + c["close"]) / 3.0
        bins[round_tick(symbol, typ)] += float(c.get("volume", 1.0))
    if not bins:
        return { "bins": {}, "poc": None, "vah": None, "val": None }
    poc = max(bins.items(), key=lambda kv: kv[1])[0]
    total = sum(bins.values())
    levels = sorted(bins.keys())
    idx = levels.index(poc); used = {poc}; cum = bins[poc]
    left = idx - 1; right = idx + 1
    while cum < value_area_pct * total and (left >= 0 or right < len(levels)):
        lvol = bins[levels[left]] if left >= 0 else -1
        rvol = bins[levels[right]] if right < len(levels) else -1
        if rvol >= lvol:
            if right < len(levels):
                used.add(levels[right]); cum += bins[levels[right]]; right += 1
        else:
            if left >= 0:
                used.add(levels[left]); cum += bins[levels[left]]; left -= 1
    return { "bins": dict(bins), "poc": poc, "vah": max(used), "val": min(used) }

def candle_svg(c):
    import base64
    w, h, m = 40, 80, 6
    hi, lo, op, cl = c["high"], c["low"], c["open"], c["close"]
    top = max(hi, op, cl); bot = min(lo, op, cl)
    def y(px): return m + (top - px) * (h - 2*m) / (top - bot + 1e-9)
    btop = y(max(op, cl)); bbot = y(min(op, cl)); bh = max(2, abs(btop - bbot))
    wx = 20; wy1 = y(hi); wy2 = y(lo)
    fill = "#2ecc71" if cl >= op else "#e74c3c"
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>" + \
        f"<line x1='{wx}' y1='{wy1:.2f}' x2='{wx}' y2='{wy2:.2f}' stroke='#333' stroke-width='2'/>" + \
        f"<rect x='14' y='{min(btop,bbot):.2f}' width='12' height='{bh:.2f}' fill='{fill}' stroke='#222'/>" + "</svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()

# ---------- Strategy ----------
def trend_flag(emas):
    e9, e21, e50 = emas[9][-1], emas[21][-1], emas[50][-1]
    if e9 > e21 > e50: return "up"
    if e9 < e21 < e50: return "down"
    if e9 > e21 >= e50: return "half_up"
    if e9 < e21 <= e50: return "half_down"
    return "sideways"

def generate_signal(symbol, candles):
    if len(candles) < max(LOOKBACK, 55):
        return {"signal":"NO TRADE","reason":"Not enough data","trend":"sideways"}
    closes = [c["close"] for c in candles]
    emas = compute_emas(closes, periods=(9,21,50))
    tf = trend_flag(emas)
    profile = build_volume_profile(symbol, candles[-LOOKBACK:], VALUE_AREA_PCT)
    poc, vah, val = profile["poc"], profile["vah"], profile["val"]
    last = candles[-1]; open_ = last["open"]; close = last["close"]; high = last["high"]; low = last["low"]
    green = close >= open_
    rng = max(1e-9, high - low); body = abs(close - open_); body_pct = body / rng
    atr = atr14(candles)
    if rng < 0.3 * atr:
        return {"signal":"NO TRADE","reason":"Low volatility (range<0.3*ATR)","trend":tf,"poc":poc,"vah":vah,"val":val,"svg":candle_svg(last)}
    signal = "NO TRADE"; reason = []
    # Rejection
    if (low <= val <= close) and (not green) and tf in ("down","half_down"):
        signal = "PUT"; reason.append("Bearish rejection at VAL in downtrend")
    if (high >= vah >= close) and (not green) and tf in ("down","half_down") and signal == "NO TRADE":
        signal = "PUT"; reason.append("Touched VAH, closed below in downtrend")
    if (low <= val <= close) and green and tf in ("up","half_up") and signal == "NO TRADE":
        signal = "CALL"; reason.append("Touched VAL, closed above in uptrend")
    # Breakouts
    if close > vah and tf in ("up","half_up"):
        signal = "CALL"; reason.append("Breakout above VAH")
    if close < val and tf in ("down","half_down"):
        signal = "PUT"; reason.append("Breakout below VAL")
    if signal in ("CALL","PUT") and body_pct < MIN_BODY_PCT:
        reason.append("Weak body — filtered"); signal = "NO TRADE"
    return {"signal":signal,"reason":"; ".join(reason) if reason else "No clear setup","trend":tf,"poc":poc,"vah":vah,"val":val,"svg":candle_svg(last)}

def confirm_htf(symbol):
    if not CONFIRM_ENABLE: return True
    try:
        candles = td_fetch(symbol, CONFIRM_INTERVAL, max(60, LOOKBACK // 3))
        res = generate_signal(symbol, candles)
        return res["signal"] in ("CALL","PUT")
    except Exception:
        return True

# ---------- Alerts & Logging ----------
def log_signal(symbol, res):
    path = os.path.join(DATA_DIR, "signals.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new: w.writerow(["time_ist","symbol","signal","trend","poc","vah","val","reason"]) 
        w.writerow([ist_now_str(), symbol, res.get("signal"), res.get("trend"), res.get("poc"), res.get("vah"), res.get("val"), res.get("reason")])

def send_webhook(symbol, res):
    if not WEBHOOK_URL: return
    try:
        requests.post(WEBHOOK_URL, json={"time_ist": ist_now_str(), "symbol": symbol, **res}, timeout=8)
    except Exception as e:
        STATE["errors"].append(f"Webhook: {e}")

def send_telegram(symbol, res):
    if not (TG_BOT_TOKEN and TG_CHAT_ID): return
    msg = f"VA-MOD {symbol}: {res['signal']} ({res['trend']})\nPOC {res['poc']} VAH {res['vah']} VAL {res['val']}\n{res['reason']}\n{ist_now_str()}"
    try:
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", data={"chat_id":TG_CHAT_ID,"text":msg}, timeout=8)
    except Exception as e:
        STATE["errors"].append(f"Telegram: {e}")

# ---------- Scanner ----------
def next_boundary_5m(now=None):
    now = now or ist_now()
    minute = (now.minute // 5) * 5
    return now.replace(second=0, microsecond=0, minute=minute) + timedelta(minutes=5)

def scan_once():
    out = {}
    for sym in PAIRS:
        try:
            candles = ensure_series(sym, PRIMARY_INTERVAL, LOOKBACK)
            res = generate_signal(sym, candles)
            if res["signal"] in ("CALL","PUT") and CONFIRM_ENABLE and not confirm_htf(sym):
                res["reason"] += "; HTF confirm failed"; res["signal"] = "NO TRADE"
            out[sym] = res
            log_signal(sym, res)
            if res["signal"] in ("CALL","PUT"):
                send_webhook(sym, res); send_telegram(sym, res)
        except Exception as e:
            out[sym] = {"signal":"ERROR","reason":str(e)}
            STATE["errors"].append(f"{sym}: {e}")
    STATE["last_scan_ist"] = ist_now_str()
    return out

def scanner_loop():
    while ENABLE_SCANNER:
        now = ist_now()
        boundary = next_boundary_5m(now)
        wait = (boundary - now).total_seconds() + SCAN_DELAY_SEC
        if wait > 0:
            time.sleep(min(wait, 30)); continue
        try:
            scan_once()
        except Exception as e:
            STATE["errors"].append(f"scan: {e}")
        time.sleep(SCAN_INTERVAL_SEC)

if ENABLE_SCANNER:
    threading.Thread(target=scanner_loop, daemon=True).start()

# ---------- Routes ----------
@app.route("/")
def index():
    return render_template("index.html", pairs=PAIRS, primary=PRIMARY_INTERVAL, confirm=(CONFIRM_INTERVAL if CONFIRM_ENABLE else "off"))

@app.route("/results")
def results():
    try:
        out = {}
        for sym in PAIRS:
            candles = ensure_series(sym, PRIMARY_INTERVAL, LOOKBACK)
            out[sym] = generate_signal(sym, candles)
        return jsonify({"ok": True, "time_ist": ist_now_str(), "results": out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        res = scan_once()
        return jsonify({"ok": True, "time_ist": STATE.get("last_scan_ist"), "results": res})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()})

@app.route("/export")
def export_csv():
    path = os.path.join(DATA_DIR, "signals.csv")
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["time_ist","symbol","signal","trend","poc","vah","val","reason"]) 
    return send_file(path, as_attachment=True, download_name="signals.csv")

@app.route("/health")
def health():
    return jsonify({"ok": True, "scanner": ENABLE_SCANNER, "last_scan_ist": STATE.get("last_scan_ist"), "errors": list(STATE["errors"])})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
