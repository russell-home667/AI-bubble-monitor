#!/usr/bin/env python3
"""Refresh intraday quote overlays used by the AI Bubble Monitor.

Policy:
- NDX / SOX / NVDA / GOOGL / MSFT / AMZN / VIX: Yahoo Finance intraday bars.
- US 10Y / 30Y headline yields: Investing.com public quote pages are primary.
- Treasury fallbacks: TradingView public scanner, then Trading Economics public pages.
- Official Treasury daily histories remain untouched in dgs10.csv / dgs30.csv.

The script is deliberately defensive: it validates instrument identity and yield ranges,
uses several Investing.com page variants, keeps the previous stored quote if every live
source is temporarily unavailable, and never overwrites the official Treasury history.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as curl_requests
except Exception:  # optional hardening transport
    curl_requests = None

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data" / "ai_bubble" / "market_liquidity"
OUT = DIR / "market_quotes.json"
BJT = ZoneInfo("Asia/Shanghai")

YAHOO_SYMBOLS = {
    "ndx": {"symbol": "^NDX", "name": "Nasdaq-100", "unit": "index"},
    "sox": {"symbol": "^SOX", "name": "PHLX Semiconductor Index", "unit": "index"},
    "nvda": {"symbol": "NVDA", "name": "NVIDIA", "unit": "USD"},
    "googl": {"symbol": "GOOGL", "name": "Alphabet", "unit": "USD"},
    "msft": {"symbol": "MSFT", "name": "Microsoft", "unit": "USD"},
    "amzn": {"symbol": "AMZN", "name": "Amazon", "unit": "USD"},
    "vix": {"symbol": "^VIX", "name": "Cboe Volatility Index", "unit": "index"},
}

TREASURY = {
    "dgs10": {
        "name": "10-Year Treasury Yield",
        "unit": "%",
        "tenor": "10Y",
        "tv_symbol": "TVC:US10Y",
        "investing_urls": [
            "https://www.investing.com/rates-bonds/u.s.-10-year-bond-yield",
            "https://www.investing.com/rates-bonds/u.s.-10-year-bond-yield-opinion",
            "https://www.investing.com/rates-bonds/u.s.-10-year-bond-yield-historical-data",
            "https://www.investing.com/rates-bonds/u.s.-10-year-bond-yield-streaming-chart",
        ],
        "te_url": "https://tradingeconomics.com/united-states/government-bond-yield",
    },
    "dgs30": {
        "name": "30-Year Treasury Yield",
        "unit": "%",
        "tenor": "30Y",
        "tv_symbol": "TVC:US30Y",
        "investing_urls": [
            "https://www.investing.com/rates-bonds/u.s.-30-year-bond-yield",
            "https://www.investing.com/rates-bonds/u.s.-30-year-bond-yield-opinion",
            "https://www.investing.com/rates-bonds/u.s.-30-year-bond-yield-historical-data",
            "https://www.investing.com/rates-bonds/u.s.-30-year-bond-yield-streaming-chart",
        ],
        "te_url": "https://tradingeconomics.com/united-states/30-year-bond-yield",
    },
}

LIVE_OVERLAY_KEYS = ("vix", "dgs10", "dgs30")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

TV_CACHE: dict | None = None


def now_bjt() -> str:
    return datetime.now(BJT).isoformat(timespec="seconds")


def validate_yield(value: float, label: str) -> float:
    value = float(value)
    if not 0.01 < value < 20.0:
        raise RuntimeError(f"{label} implausible Treasury yield: {value}")
    return value


def first_number(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?", str(text))
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


def browser_get(url: str, timeout: int = 25) -> tuple[str, str]:
    """Fetch public HTML with two independent transports.

    curl_cffi is used first because Investing.com is Cloudflare-fronted; ordinary
    requests remains a clean fallback. No login, cookies, CAPTCHA solving or private
    endpoints are used.
    """
    errors = []
    if curl_requests is not None:
        try:
            r = curl_requests.get(
                url,
                headers=BROWSER_HEADERS,
                timeout=timeout,
                impersonate="chrome",
                allow_redirects=True,
            )
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text, "curl_cffi/chrome"
            errors.append(f"curl_cffi HTTP {r.status_code} len={len(r.text)}")
        except Exception as exc:
            errors.append(f"curl_cffi {exc}")

    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code == 200 and len(r.text) > 1000:
            return r.text, "requests"
        errors.append(f"requests HTTP {r.status_code} len={len(r.text)}")
    except Exception as exc:
        errors.append(f"requests {exc}")

    raise RuntimeError("; ".join(errors))


def fetch_yahoo_quote(symbol: str) -> dict:
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
        "poll_frequency": "10 minutes",
        "source": f"Yahoo Finance {symbol}",
        "source_url": f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}/",
        "quote_status": "DELAYED",
    }


def parse_investing_quote(html: str, meta: dict, source_url: str, transport: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    tenor = meta["tenor"]

    # Guard against a challenge/interstitial or the wrong instrument page.
    expected = f"United States {tenor[:-1]}-Year Bond Yield"
    if expected.lower() not in text.lower() and f"U.S. {tenor}".lower() not in text.lower():
        raise RuntimeError(f"unexpected page identity; missing {expected!r}")

    price = None
    el = soup.select_one('[data-test="instrument-price-last"]')
    if el:
        price = first_number(el.get_text(" ", strip=True))

    # Defensive fallback for markup changes while keeping the extraction anchored
    # to Investing.com's named last-price field.
    if price is None:
        m = re.search(
            r'data-test=["\']instrument-price-last["\'][^>]*>\s*([^<]+)',
            html,
            flags=re.I | re.S,
        )
        if m:
            price = first_number(m.group(1))

    if price is None:
        raise RuntimeError("instrument-price-last not found")
    price = validate_yield(price, f"Investing.com {tenor}")

    prev = None
    m = re.search(r"Prev\.\s*Close\s+([0-9]+(?:\.[0-9]+)?)", text, flags=re.I)
    if m:
        prev = validate_yield(float(m.group(1)), f"Investing.com {tenor} prev close")

    change_pct = ((price / prev) - 1.0) * 100.0 if prev else None

    if "Real-time Data" in text:
        status = "INVESTING_REALTIME"
        state_text = "Real-time Data"
    elif re.search(r"\bDelayed\b", text, flags=re.I):
        status = "INVESTING_DELAYED"
        state_text = "Delayed"
    elif re.search(r"\bClosed\b", text, flags=re.I):
        status = "INVESTING_CLOSED"
        state_text = "Closed"
    else:
        status = "INVESTING_LIVE_PAGE"
        state_text = "Unknown"

    market_time = None
    m = re.search(
        r"(?:Real-time Data|Delayed|Closed)\s*[·•]?\s*(\d{1,2}:\d{2}:\d{2})",
        text,
        flags=re.I,
    )
    if m:
        market_time = m.group(1)

    return {
        "price": round(price, 6),
        "previous_close": round(prev, 6) if prev is not None else None,
        "change_1d_pct": round(change_pct, 4) if change_pct is not None else None,
        "timestamp": now_bjt(),
        "source_market_time_text": market_time,
        "bar_interval": "live quote",
        "poll_frequency": "10 minutes",
        "source": f"Investing.com US {tenor} Bond Yield",
        "source_url": source_url,
        "quote_status": status,
        "source_state": state_text,
        "transport": transport,
    }


def fetch_investing_treasury(meta: dict) -> dict:
    errors = []
    for idx, url in enumerate(meta["investing_urls"]):
        try:
            html, transport = browser_get(url, timeout=25)
            quote_data = parse_investing_quote(html, meta, url, transport)
            quote_data["provider_rank"] = 1
            quote_data["provider"] = "Investing.com"
            return quote_data
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            if idx < len(meta["investing_urls"]) - 1:
                time.sleep(0.6)
    raise RuntimeError(" | ".join(errors))


def fetch_tradingview_cache() -> dict:
    global TV_CACHE
    if TV_CACHE is not None:
        return TV_CACHE

    symbols = [m["tv_symbol"] for m in TREASURY.values()]
    endpoints = [
        "https://scanner.tradingview.com/global/scan",
        "https://scanner.tradingview.com/bond/scan",
    ]
    column_sets = [
        ["close", "change", "change_abs", "update_mode"],
        ["close", "change", "update_mode"],
        ["close", "change"],
    ]
    errors = []

    for endpoint in endpoints:
        for columns in column_sets:
            payload = {
                "symbols": {"tickers": symbols, "query": {"types": []}},
                "columns": columns,
            }
            try:
                r = requests.post(
                    endpoint,
                    json=payload,
                    headers={
                        "User-Agent": BROWSER_HEADERS["User-Agent"],
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Origin": "https://www.tradingview.com",
                        "Referer": "https://www.tradingview.com/",
                    },
                    timeout=20,
                )
                r.raise_for_status()
                data = r.json().get("data") or []
                out = {}
                for item in data:
                    symbol = item.get("s")
                    values = item.get("d") or []
                    row = dict(zip(columns, values))
                    if symbol in symbols and row.get("close") is not None:
                        out[symbol] = row
                if out:
                    TV_CACHE = out
                    return out
            except Exception as exc:
                errors.append(f"{endpoint} {columns}: {exc}")

    raise RuntimeError("TradingView scanner failed: " + " | ".join(errors))


def fetch_tradingview_treasury(meta: dict) -> dict:
    rows = fetch_tradingview_cache()
    row = rows.get(meta["tv_symbol"])
    if not row:
        raise RuntimeError(f"TradingView returned no {meta['tv_symbol']}")
    price = validate_yield(float(row["close"]), f"TradingView {meta['tenor']}")
    return {
        "price": round(price, 6),
        "previous_close": None,
        "change_1d_pct": round(float(row["change"]), 4) if row.get("change") is not None else None,
        "timestamp": now_bjt(),
        "bar_interval": "live scanner quote",
        "poll_frequency": "10 minutes",
        "source": f"TradingView {meta['tv_symbol']}",
        "source_url": f"https://www.tradingview.com/symbols/{meta['tv_symbol'].replace(':', '-')}/",
        "quote_status": "TRADINGVIEW_FALLBACK",
        "source_state": row.get("update_mode"),
        "provider_rank": 2,
        "provider": "TradingView",
    }


def fetch_tradingeconomics_treasury(meta: dict) -> dict:
    html, transport = browser_get(meta["te_url"], timeout=25)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Trading Economics public bond pages expose a headline 'Actual' value.
    patterns = [
        r"\bActual\s+([0-9]+(?:\.[0-9]+)?)",
        rf"US\s+{re.escape(meta['tenor'])}\s+[^0-9]{{0,80}}([0-9]+(?:\.[0-9]+)?)",
    ]
    price = None
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I | re.S)
        if m:
            candidate = float(m.group(1))
            if 0.01 < candidate < 20.0:
                price = candidate
                break
    if price is None:
        raise RuntimeError("Trading Economics headline Actual yield not found")

    return {
        "price": round(validate_yield(price, f"Trading Economics {meta['tenor']}"), 6),
        "previous_close": None,
        "change_1d_pct": None,
        "timestamp": now_bjt(),
        "bar_interval": "public webpage quote",
        "poll_frequency": "10 minutes",
        "source": f"Trading Economics US {meta['tenor']}",
        "source_url": meta["te_url"],
        "quote_status": "TRADING_ECONOMICS_FALLBACK",
        "transport": transport,
        "provider_rank": 3,
        "provider": "Trading Economics",
    }


def fetch_treasury_quote(meta: dict) -> tuple[dict, list[str]]:
    errors = []
    providers = (
        ("Investing.com", fetch_investing_treasury),
        ("TradingView", fetch_tradingview_treasury),
        ("Trading Economics", fetch_tradingeconomics_treasury),
    )
    for name, fn in providers:
        try:
            q = fn(meta)
            if errors:
                q["fallback_reason"] = " | ".join(errors)
            return q, errors
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("all Treasury live sources failed: " + " | ".join(errors))


def same_quote(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False
    return (
        a.get("price") == b.get("price")
        and a.get("source") == b.get("source")
        and a.get("quote_status") == b.get("quote_status")
        and a.get("source_market_time_text") == b.get("source_market_time_text")
    )


def stable_merge(old_quote: dict | None, new_quote: dict) -> dict:
    # If the externally reported quote is unchanged, preserve the previous timestamp.
    # This avoids a meaningless Git commit every ten minutes while still polling every run.
    if same_quote(old_quote, new_quote):
        merged = dict(old_quote)
        merged["last_checked_bjt"] = now_bjt()
        return merged
    new_quote = dict(new_quote)
    new_quote["last_checked_bjt"] = now_bjt()
    return new_quote


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

    for key, meta in YAHOO_SYMBOLS.items():
        try:
            q = fetch_yahoo_quote(meta["symbol"])
            q.update({"symbol": meta["symbol"], "name": meta["name"], "unit": meta["unit"]})
            new_quotes[key] = stable_merge(old_quotes.get(key), q)
            print(f"{meta['symbol']}: {q['price']} @ {q['timestamp']} via Yahoo")
        except Exception as exc:
            errors[key] = str(exc)
            print(f"WARNING {meta['symbol']}: {exc}", file=sys.stderr)

    for key, meta in TREASURY.items():
        try:
            q, provider_errors = fetch_treasury_quote(meta)
            q.update({
                "symbol": meta["tv_symbol"],
                "name": meta["name"],
                "unit": meta["unit"],
            })
            new_quotes[key] = stable_merge(old_quotes.get(key), q)
            if provider_errors:
                errors[key] = provider_errors
            print(
                f"{meta['tenor']}: {q['price']} @ {q['timestamp']} "
                f"via {q.get('provider')} [{q.get('quote_status')}]"
            )
        except Exception as exc:
            errors[key] = str(exc)
            prior = old_quotes.get(key)
            if prior and prior.get("price") is not None:
                stale = dict(prior)
                stale["quote_status"] = "STALE_STORED_QUOTE"
                stale["last_checked_bjt"] = now_bjt()
                stale["fallback_reason"] = str(exc)
                new_quotes[key] = stale
                print(f"WARNING {meta['tenor']}: {exc}; retained previous stored quote", file=sys.stderr)
            else:
                print(f"WARNING {meta['tenor']}: {exc}", file=sys.stderr)

    if not new_quotes:
        raise RuntimeError("No market quotes available")

    payload = {
        "generated_at_bjt": now_bjt(),
        "timezone": "Asia/Shanghai",
        "source": "Mixed intraday sources",
        "poll_frequency": "10 minutes",
        "treasury_source_priority": ["Investing.com", "TradingView", "Trading Economics"],
        "note": (
            "US 10Y/30Y headline values use Investing.com public real-time bond-yield pages first, "
            "then TradingView and Trading Economics fallbacks. Treasury historical CSVs remain "
            "official U.S. Treasury daily closes."
        ),
        "quotes": new_quotes,
        "errors": errors,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    quote_changed = not OUT.exists() or OUT.read_text(encoding="utf-8") != serialized
    if quote_changed:
        OUT.write_text(serialized, encoding="utf-8")

    if not quote_changed:
        print("Quotes checked; no externally visible changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
