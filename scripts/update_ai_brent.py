#!/usr/bin/env python3
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ai_bubble" / "macro" / "brent.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
AVIATION_SOURCE = "https://raw.githubusercontent.com/russell-home667/aviation-leasing-dashboard/main/data/market_data.json"


def load_existing():
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    try:
        payload = requests.get(AVIATION_SOURCE, timeout=30).json()
        brent = payload.get("brent") or {}
        if brent:
            return brent
    except Exception:
        pass
    return {}


brent = load_existing()
old_records = brent.get("data", [])

print("Downloading maximum Brent daily history from Yahoo Finance...")
history = yf.Ticker("BZ=F").history(period="max", interval="1d", auto_adjust=False, actions=False)
if history.empty:
    raise RuntimeError("Yahoo Finance returned no Brent data.")
history = history.dropna(subset=["Close"])

now_ny = datetime.now(ZoneInfo("America/New_York"))
max_date = now_ny.date() if now_ny.hour >= 18 else now_ny.date() - timedelta(days=1)

fetched = []
for index, row in history.iterrows():
    d = index.date()
    if d > max_date:
        continue
    fetched.append({"date": d.isoformat(), "value": round(float(row["Close"]), 2)})
if not fetched:
    raise RuntimeError("No completed Brent daily bars found.")

by_date = {r["date"]: r for r in old_records if r.get("date") and r.get("value") is not None}
for r in fetched:
    by_date[r["date"]] = r
merged = sorted(by_date.values(), key=lambda x: x["date"])

brent.update({
    "name": "Brent Crude",
    "ticker": "BZ=F",
    "unit": "USD/bbl",
    "source": "Yahoo Finance",
    "source_url": "https://finance.yahoo.com/quote/BZ=F/",
    "frequency": "Daily",
    "price_field": "Daily Close",
    "status": "LIVE",
    "history_scope": "Maximum daily history available from Yahoo Finance BZ=F, seeded from the aviation dashboard archive",
    "data": merged,
    "updated_at_bjt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
})

new_text = json.dumps(brent, ensure_ascii=False, indent=2) + "\n"
old_text = OUT.read_text(encoding="utf-8") if OUT.exists() else None
if old_text == new_text:
    print(f"No Brent history change. Coverage {merged[0]['date']} to {merged[-1]['date']} ({len(merged)} rows).")
    sys.exit(0)
OUT.write_text(new_text, encoding="utf-8")
print(f"Brent history updated: {merged[0]['date']} to {merged[-1]['date']} ({len(merged)} rows).")
