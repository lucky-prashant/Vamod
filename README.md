# VA‑MOD Auto Signals — Render & GitHub Ready

This repo is ready to push to GitHub and connect to Render (or any similar host). The Twelve Data API key is hardcoded in `app.py` as you requested.

## Quick deploy (Render)
1. Create a new GitHub repository and push the project files.
2. On Render, create a **Web Service** and connect to the GitHub repo.
3. Set the build command (default) and leave environment variables blank — key is already in code.
4. Render will run `gunicorn app:app` (Procfile included).

## Run locally
```bash
git clone <your-repo>
cd <repo>
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```

## Files of interest
- `app.py` — main Flask app (hardcoded API key)
- `templates/index.html`, `static/main.js`, `static/styles.css` — dashboard
- `data/signals.csv` — logged signals

## Warning
Hardcoding API keys in source is convenient but insecure for public repos. Consider using Render environment variables if the repo will be public.
