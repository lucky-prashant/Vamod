# VA‑MOD Auto Signals (Full)

**What you get**
- Flask dashboard + REST API
- POC/VAH/VAL from volume profile
- EMA(9/21/50) trend
- Rejection & breakout entries
- ATR inactivity filter
- Optional 15m higher‑TF confirmation
- CSV logging + Telegram + Webhook alerts
- Background scanner aligned to 5‑minute boundaries

## Run
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export TWELVE_DATA_API_KEY="YOUR_KEY"
python app.py
```
Open http://localhost:5000

## Configure (env vars)
PAIRS, PRIMARY_INTERVAL, CONFIRM_INTERVAL (set to `off` to disable), LOOKBACK, VALUE_AREA_PCT, MIN_BODY_PCT,
ENABLE_SCANNER, SCAN_DELAY_SEC, SCAN_INTERVAL_SEC, WEBHOOK_URL, TG_BOT_TOKEN, TG_CHAT_ID.
