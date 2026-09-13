#!/usr/bin/env python3
import argparse
import json
import random
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

PAIR_ID = "68"  # Investing.com XAU/USD - Gold Spot US Dollar (spot, not Gold Futures 8830)
CANONICAL_URL = "https://www.investing.com/currencies/xau-usd"
CANONICAL_HISTORICAL_URL = "https://www.investing.com/currencies/xau-usd-historical-data"
# www.investing.com blocks GitHub cloud IPs. The UK/Canada regional sites expose the
# same Investing.com instrument/data and are reachable from GitHub Actions.
REGIONAL_HOSTS = ["https://uk.investing.com", "https://ca.investing.com"]
TZ_BJT = ZoneInfo("Asia/Shanghai")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"


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
    # Investing table data-real-value is often a Unix timestamp stored as a string.
    if re.fullmatch(r"\d{9,13}(?:\.0+)?", s):
        ts = float(s)
        if ts > 10_000_000_000:
            ts /= 1000
        return datetime.utcfromtimestamp(ts).date().isoformat()
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%m/%d/%Y", "%d/%m/%Y", "%b %d, %y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            pass
    m = re.search(r"(20\d{2}|19\d{2})-(\d{2})-(\d{2})", s)
    return m.group(0) if m else None


def extract_html_rows(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table#curr_table") or soup.select_one("table.historicalTbl")
    if not table:
        return []
    out = []
    for tr in table.select("tbody tr"):
        td = tr.find_all("td")
        if len(td) < 2:
            continue
        raw_date = td[0].get("data-real-value") or td[0].get_text(" ", strip=True)
        d = parse_date(raw_date)
        raw_price = td[1].get("data-real-value") or td[1].get_text(" ", strip=True)
        price = clean_number(raw_price)
        if not d or price is None:
            continue
        rec = {"date": d, "value": round(price, 2)}
        if len(td) >= 5:
            for idx, key in ((2, "open"), (3, "high"), (4, "low")):
                n = clean_number(td[idx].get("data-real-value") or td[idx].get_text(" ", strip=True))
                if n is not None:
                    rec[key] = round(n, 2)
        out.append(rec)
    return out


def discover_sml_id(html):
    for pat in (
        r"histDataExcessInfo\s*=\s*\{[^}]*?smlID?\s*:\s*['\"]?(\d+)",
        r"smlID\s*[:=]\s*['\"]?(\d+)",
        r"smlId\s*[:=]\s*['\"]?(\d+)",
    ):
        m = re.search(pat, html, re.I | re.S)
        if m:
            return m.group(1)
    # The endpoint accepts an opaque smlID; this keeps the call browser-shaped if the page
    # no longer exposes the old variable.
    return str(random.randint(1_000_000, 99_999_999))


def fetch_period_from_host(host, start, end):
    hist_url = host + "/currencies/xau-usd-historical-data"
    ajax_url = host + "/instruments/HistoricalDataAjax"
    session = requests.Session(impersonate="chrome")
    base_headers = {
        "user-agent": UA,
        "accept-language": "en-GB,en;q=0.9",
        "referer": hist_url,
    }
    page_headers = dict(base_headers)
    page_headers["accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    page = session.get(hist_url, headers=page_headers, timeout=45)
    if page.status_code != 200:
        raise RuntimeError(f"page HTTP {page.status_code}")

    sml_id = discover_sml_id(page.text)
    ajax_headers = dict(base_headers)
    ajax_headers.update({
        "accept": "text/html, */*; q=0.01",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
        "origin": host,
    })
    payload = {
        "curr_id": PAIR_ID,
        "smlID": sml_id,
        "header": "XAU/USD Historical Data",
        "st_date": start.strftime("%m/%d/%Y"),
        "end_date": end.strftime("%m/%d/%Y"),
        "interval_sec": "Daily",
        "sort_col": "date",
        "sort_ord": "DESC",
        "action": "historical_data",
    }
    resp = session.post(ajax_url, headers=ajax_headers, data=payload, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"ajax HTTP {resp.status_code}")
    rows = extract_html_rows(resp.text)
    if not rows:
        raise RuntimeError("ajax returned no parseable rows")
    return rows, host


def fetch_period(start, end):
    errors = []
    for host in REGIONAL_HOSTS:
        try:
            rows, used = fetch_period_from_host(host, start, end)
            print(f"Investing.com {used}: {len(rows)} rows for {start} -> {end}")
            return rows, used
        except Exception as exc:
            errors.append(f"{host}: {exc}")
    raise RuntimeError(" | ".join(errors))


def fetch_full_history():
    # UK Investing describes XAU/USD as having 40+ years of history. Start in 1970 so
    # we capture the earliest rows it will return without inventing pre-source data.
    cur = date(1970, 1, 1)
    end_all = date.today()
    rows = []
    used_hosts = set()
    while cur <= end_all:
        end = min(date(cur.year + 4, 12, 31), end_all)
        print(f"Fetching XAU/USD {cur} -> {end} ...")
        try:
            chunk, host = fetch_period(cur, end)
            rows.extend(chunk)
            used_hosts.add(host)
        except Exception as exc:
            print(f"Chunk failed: {exc}", file=sys.stderr)
        cur = end + timedelta(days=1)
    return rows, sorted(used_hosts)


def fetch_page_quote():
    for host in REGIONAL_HOSTS:
        try:
            url = host + "/currencies/xau-usd"
            h = {"user-agent": UA, "accept-language": "en-GB,en;q=0.9"}
            resp = requests.get(url, headers=h, impersonate="chrome", timeout=35)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for sel in ('[data-test="instrument-price-last"]', '[data-test="instrument-price-last"] span'):
                node = soup.select_one(sel)
                if node:
                    n = clean_number(node.get_text(" ", strip=True))
                    if n and n > 100:
                        return n, host
        except Exception as exc:
            print(f"Live quote failed on {host}: {exc}", file=sys.stderr)
    return None, None


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
    used_hosts = set(existing.get("retrieval_hosts", [])) if isinstance(existing, dict) else set()

    if args.full or not old_rows:
        fetched, hosts = fetch_full_history()
        used_hosts.update(hosts)
    else:
        fetched, host = fetch_period(date.today() - timedelta(days=90), date.today())
        used_hosts.add(host)

    by_date = {}
    for r in old_rows + fetched:
        if isinstance(r, dict) and r.get("date") and r.get("value") is not None:
            by_date[r["date"]] = r
    merged = sorted(by_date.values(), key=lambda x: x["date"])
    if not merged:
        raise RuntimeError("No XAU/USD history available after merge")

    live, live_host = fetch_page_quote()
    if live_host:
        used_hosts.add(live_host)
    latest_daily = merged[-1]
    now_bjt = datetime.now(TZ_BJT)
    payload = {
        "name": "Gold Spot / US Dollar",
        "ticker": "XAU/USD",
        "unit": "USD/oz",
        "instrument_id": PAIR_ID,
        "source": "Investing.com",
        "source_url": CANONICAL_URL,
        "historical_source_url": CANONICAL_HISTORICAL_URL,
        "retrieval_hosts": sorted(used_hosts),
        "frequency": "Daily history + public page quote check",
        "price_field": "XAU/USD spot price",
        "status": "LIVE" if live is not None else "DAILY_CLOSE",
        "history_scope": "Maximum Investing.com XAU/USD daily history obtainable from regional Investing.com endpoints; no synthetic weekend/interpolated rows",
        "latest_quote": {
            "price": round(live if live is not None else float(latest_daily["value"]), 2),
            "timestamp": now_bjt.isoformat(timespec="seconds"),
            "quote_status": "INVESTING_PAGE" if live is not None else "LATEST_DAILY_CLOSE",
        },
        "data": merged,
        "updated_at_bjt": now_bjt.isoformat(timespec="seconds"),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Gold updated: {merged[0]['date']} -> {merged[-1]['date']} ({len(merged)} rows), latest={payload['latest_quote']['price']}")


if __name__ == "__main__":
    main()
