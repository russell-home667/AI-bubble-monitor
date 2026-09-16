#!/usr/bin/env python3
"""Refresh Yahoo intraday quotes used by the AI Bubble Monitor.

The 5-minute quote layer covers NDX, SOX, NVDA, VIX, 10Y Treasury (^TNX) and
30Y Treasury (^TYX). 10Y/30Y official daily closes remain sourced from the
U.S. Treasury by update_ai_market_liquidity.py.
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
DIR = ROOT / "data" / "ai_bubble" / "market_liquidity"
OUT = DIR / "market_quotes.json"
LATEST = DIR / "latest.json"
BJT = ZoneInfo("Asia/Shanghai")

SYMBOLS = {
    "ndx": {"symbol": "^NDX", "name": "Nasdaq-100", "unit": "index"},
    "sox": {"symbol": "^SOX", "name": "PHLX Semiconductor Index", "unit": "index"},
    "nvda": {"symbol": "NVDA", "name": "NVIDIA", "unit": "USD"},
    "vix": {"symbol": "^VIX", "name": "Cboe Volatility Index", "unit": "index"},
    "dgs10": {"symbol": "^TNX", "name": "10-Year Treasury Yield", "unit": "%"},
    "dgs30": {"symbol": "^TYX", "name": "30-Year Treasury Yield", "unit": "%"},
}
LIVE_OVERLAY_KEYS = ("vix", "dgs10", "dgs30")


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


def sync_latest_quotes(quotes: dict) -> bool:
    """Overlay Yahoo VIX/10Y/30Y intraday values onto existing daily summaries."""
    if not LATEST.exists():
        return False
    try:
        payload = json.loads(LATEST.read_text(encoding="utf-8"))
    except Exception:
        return False

    indicators = payload.get("indicators") or {}
    changed = False
    for key in LIVE_OVERLAY_KEYS:
        q = quotes.get(key)
        ind = indicators.get(key)
        if not q or not ind or q.get("price") is None:
            continue

        if ind.get("display_layer") != "live_quote":
            ind["close_value"] = ind.get("value")
            ind["close_observation_date"] = ind.get("observation_date")
            ind["close_source"] = ind.get("source")
            ind["close_source_url"] = ind.get("source_url")

        new_fields = {
            "value": q["price"],
            "live_quote_timestamp": q.get("timestamp"),
            "live_quote_source": q.get("source"),
            "live_quote_status": q.get("quote_status"),
            "live_change_1d_pct": q.get("change_1d_pct"),
            "display_layer": "live_quote",
        }
        for field, value in new_fields.items():
            if ind.get(field) != value:
                ind[field] = value
                changed = True

    if changed:
        payload["generated_at_bjt"] = datetime.now(BJT).isoformat(timespec="seconds")
        LATEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


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
        except Exception as exc:
            errors[key] = str(exc)
            print(f"WARNING {meta['symbol']}: {exc}", file=sys.stderr)

    if not new_quotes:
        raise RuntimeError("No market quotes available")

    payload = {
        "generated_at_bjt": datetime.now(BJT).isoformat(timespec="seconds"),
        "timezone": "Asia/Shanghai",
        "source": "Yahoo Finance 1-minute chart bars",
        "poll_frequency": "5 minutes during U.S. regular trading hours",
        "note": "VIX/10Y/30Y latest-value tiles use Yahoo intraday quotes when available; Treasury CSV histories remain official U.S. Treasury closes.",
        "quotes": new_quotes,
        "errors": errors,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    quote_changed = not OUT.exists() or OUT.read_text(encoding="utf-8") != serialized
    if quote_changed:
        OUT.write_text(serialized, encoding="utf-8")

    latest_changed = sync_latest_quotes(new_quotes)
    if not quote_changed and not latest_changed:
        print("No new quote bars; files unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
