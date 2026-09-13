#!/usr/bin/env python3
import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from curl_cffi import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ai_bubble" / "macro" / "gold_xauusd.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

PAIR_ID = "68"  # Investing.com XAU/USD - Gold Spot US Dollar
SOURCE_URL = "https://www.investing.com/currencies/xau-usd"
HISTORICAL_URL = "https://www.investing.com/currencies/xau-usd-historical-data"
API_URL = f"https://api.investing.com/api/financialdata/historical/{PAIR_ID}"
TZ_BJT = ZoneInfo("Asia/Shanghai")

HEADERS = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9",
    "referer": HISTORICAL_URL,
    "domain-id": "www",
}


def clean_number(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    s = re.sub(r"[^0-9.\-]", "", s)
    if not s or s in {"-", "."}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def parse_date(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        ts = float(v)
        if ts > 10_000_000_000:
            ts /= 1000
        return datetime.utcfromtimestamp(ts).date().isoformat()
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            pass
    m = re.search(r"(20\d{2}|19\d{2})-(\d{2})-(\d{2})", s)
    return m.group(0) if m else None


def row_to_record(row):
    if not isinstance(row, dict):
        return None
    d = None
    for k in ("rowDateRaw", "rowDate", "date", "Date", "datetime"):
        if k in row:
            d = parse_date(row.get(k))
            if d:
                break
    price = None
    for k in ("last_close", "price", "Price", "close", "Close", "price_close", "value", "last"):
        if k in row:
            price = clean_number(row.get(k))
            if price is not None:
                break
    if not d or price is None:
        return None
    out = {"date": d, "value": round(price, 2)}
    for src, dst in (("price_open", "open"), ("price_high", "high"), ("price_low", "low"), ("open", "open"), ("high", "high"), ("low", "low")):
        if src in row and dst not in out:
            n = clean_number(row.get(src))
            if n is not None:
                out[dst] = round(n, 2)
    return out


def extract_rows(payload):
    candidates = []
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        for key in ("data", "results", "rows"):
            x = payload.get(key)
            if isinstance(x, list):
                candidates = x
                break
            if isinstance(x, dict):
                for sub in ("data", "rows", "results"):
                    if isinstance(x.get(sub), list):
                        candidates = x[sub]
                        break
                if candidates:
                    break
    rows = []
    for row in candidates:
        r = row_to_record(row)
        if r:
            rows.append(r)
    return rows


def fetch_period(start, end):
    params = {
        "start-date": start.isoformat(),
        "end-date": end.isoformat(),
        "time-frame": "Daily",
        "add-missing-rows": "false",
    }
    resp = requests.get(API_URL, params=params, headers=HEADERS, impersonate="chrome", timeout=35)
    if resp.status_code != 200:
        raise RuntimeError(f"Investing historical HTTP {resp.status_code}: {resp.text[:180]}")
    payload = resp.json()
    rows = extract_rows(payload)
    if not rows:
        raise RuntimeError(f"Investing historical response contained no parseable rows: {str(payload)[:400]}")
    return rows


def fetch_full_history():
    # Spot-gold USD history is meaningful from the post-Bretton-Woods era onward.
    start = date(1970, 1, 1)
    end_all = date.today()
    rows = []
    cur = start
    while cur <= end_all:
        end = min(date(cur.year + 4, 12, 31), end_all)
        print(f"Fetching XAU/USD {cur} -> {end} ...")
        try:
            rows.extend(fetch_period(cur, end))
        except Exception as exc:
            print(f"Chunk failed: {exc}", file=sys.stderr)
        cur = end + timedelta(days=1)
    return rows


def fetch_page_quote():
    try:
        h = dict(HEADERS)
        h["accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        resp = requests.get(SOURCE_URL, headers=h, impersonate="chrome", timeout=30)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        selectors = [
            '[data-test="instrument-price-last"]',
            '[data-test="instrument-price-last"] span',
            '.instrument-price_last__KQzyA',
        ]
        for sel in selectors:
            node = soup.select_one(sel)
            if node:
                n = clean_number(node.get_text(" ", strip=True))
                if n and n > 100:
                    return n
        # Conservative fallback: look near the XAU/USD heading, not arbitrary numbers.
        text = soup.get_text(" ", strip=True)
        m = re.search(r"XAU/USD.{0,700}?([1-9][0-9]{2,4}(?:,[0-9]{3})*(?:\.[0-9]+)?)", text)
        if m:
            n = clean_number(m.group(1))
            if n and n > 100:
                return n
    except Exception as exc:
        print(f"Live page quote unavailable: {exc}", file=sys.stderr)
    return None


def load_existing():
    if not OUT.exists():
        return {}
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="force full historical backfill")
    args = ap.parse_args()

    existing = load_existing()
    old_rows = existing.get("data", []) if isinstance(existing, dict) else []

    if args.full or not old_rows:
        fetched = fetch_full_history()
    else:
        latest = max((parse_date(r.get("date")) for r in old_rows if isinstance(r, dict)), default=None)
        start = date.today() - timedelta(days=90)
        if latest:
            try:
                start = min(start, datetime.strptime(latest, "%Y-%m-%d").date() - timedelta(days=10))
            except Exception:
                pass
        fetched = fetch_period(start, date.today())

    by_date = {}
    for r in old_rows + fetched:
        if isinstance(r, dict) and r.get("date") and r.get("value") is not None:
            by_date[r["date"]] = r
    merged = sorted(by_date.values(), key=lambda x: x["date"])
    if not merged:
        raise RuntimeError("No XAU/USD history available after merge")

    live = fetch_page_quote()
    latest_daily = merged[-1]
    now_bjt = datetime.now(TZ_BJT)
    payload = {
        "name": "Gold Spot / US Dollar",
        "ticker": "XAU/USD",
        "unit": "USD/oz",
        "instrument_id": PAIR_ID,
        "source": "Investing.com",
        "source_url": SOURCE_URL,
        "historical_source_url": HISTORICAL_URL,
        "frequency": "Daily history + public page quote check",
        "price_field": "XAU/USD spot price",
        "status": "LIVE" if live is not None else "DAILY_CLOSE",
        "history_scope": "Maximum Investing.com XAU/USD daily history obtainable by the updater; no synthetic weekend/interpolated rows",
        "latest_quote": {
            "price": round(live if live is not None else float(latest_daily["value"]), 2),
            "timestamp": now_bjt.isoformat(timespec="seconds"),
            "quote_status": "INVESTING_PAGE" if live is not None else "LATEST_DAILY_CLOSE",
        },
        "data": merged,
        "updated_at_bjt": now_bjt.isoformat(timespec="seconds"),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    old = OUT.read_text(encoding="utf-8") if OUT.exists() else None
    if old == text:
        print(f"No gold change. {merged[0]['date']} -> {merged[-1]['date']} ({len(merged)} rows)")
        return
    OUT.write_text(text, encoding="utf-8")
    print(f"Gold updated: {merged[0]['date']} -> {merged[-1]['date']} ({len(merged)} rows), latest={payload['latest_quote']['price']}")


if __name__ == "__main__":
    main()
