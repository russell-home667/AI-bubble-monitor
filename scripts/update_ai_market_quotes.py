#!/usr/bin/env python3
"""Refresh latest NDX, SOX and NVDA quotes without touching daily history.

Yahoo Finance provides 1-minute source bars. GitHub Actions polls this script every
5 minutes during the regular U.S. trading session. The dashboard uses these quotes
only for the large latest-value tiles; normalized history remains completed-session
only in update_ai_market_liquidity.py.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ai_bubble" / "market_liquidity" / "market_quotes.json"
BJT = ZoneInfo("Asia/Shanghai")

SYMBOLS = {
    "ndx": {"symbol": "^NDX", "name": "Nasdaq-100", "unit": "index"},
    "sox": {"symbol": "^SOX", "name": "PHLX Semiconductor Index", "unit": "index"},
    "nvda": {"symbol": "NVDA", "name": "NVIDIA", "unit": "USD"},
}


def fetch_quote(symbol: str) -> dict:
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(symbol, safe='')}?range=1d&interval=1m&includePrePost=false"
    )
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; AI-bubble-monitor/1.0)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"Yahoo Finance returned no chart result for {symbol}")

    meta = result.get("meta") or {}
    timestamps = result.get("timestamp") or []
    quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quotes.get("close") or []

    latest_ts = None
    latest_price = None
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        latest_ts = int(ts)
        latest_price = float(close)

    if latest_price is None:
        meta_price = meta.get("regularMarketPrice")
        meta_time = meta.get("regularMarketTime")
        if meta_price is not None and meta_time is not None:
            latest_price = float(meta_price)
            latest_ts = int(meta_time)

    if latest_price is None or latest_ts is None:
        raise RuntimeError(f"Yahoo Finance returned no valid quote for {symbol}")

    prev = meta.get("chartPreviousClose")
    if prev is None:
        prev = meta.get("previousClose")
    prev = float(prev) if prev not in (None, 0) else None
    change = ((latest_price / prev) - 1.0) * 100.0 if prev else None

    return {
        "price": round(latest_price, 6),
        "previous_close": round(prev, 6) if prev is not None else None,
        "change_1d_pct": round(change, 4) if change is not None else None,
        "timestamp": datetime.fromtimestamp(latest_ts, tz=BJT).isoformat(timespec="seconds"),
        "bar_interval": "1m",
        "poll_frequency": "5 minutes",
        "source": f"Yahoo Finance {symbol}",
        "quote_status": "DELAYED",
    }


def main() -> int:
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            old = {}

    old_quotes = old.get("quotes") or {}
    new_quotes = dict(old_quotes)
    errors = {}

    for key, meta in SYMBOLS.items():
        try:
            q = fetch_quote(meta["symbol"])
            q.update({"symbol": meta["symbol"], "name": meta["name"], "unit": meta["unit"]})
            new_quotes[key] = q
            print(f"{meta['symbol']}: {q['price']} @ {q['timestamp']}")
        except Exception as exc:  # preserve prior good quote on a partial provider failure
            errors[key] = str(exc)
            print(f"WARNING {meta['symbol']}: {exc}", file=sys.stderr)

    if not new_quotes:
        raise RuntimeError("No market quotes available")

    if new_quotes == old_quotes:
        print("No new market quote bars; file unchanged")
        return 0

    payload = {
        "generated_at_bjt": datetime.now(BJT).isoformat(timespec="seconds"),
        "timezone": "Asia/Shanghai",
        "source": "Yahoo Finance 1-minute chart bars",
        "poll_frequency": "5 minutes during U.S. regular trading hours",
        "note": "Latest-value tiles use these quotes. Historical normalized charts remain completed-session only. Yahoo Finance quotes may be delayed.",
        "quotes": new_quotes,
        "errors": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
