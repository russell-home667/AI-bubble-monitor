#!/usr/bin/env python3
"""Update market/liquidity data for the AI Bubble Monitor.

Source policy:
- Market history: Yahoo Finance / yfinance.
- VIX history: Yahoo Finance ^VIX.
- 10Y/30Y Treasury official daily close layer: U.S. Treasury Daily Treasury Par Yield Curve.
- 10Y real yield official daily close layer: U.S. Treasury Daily Treasury Par Real Yield Curve.
- Credit spreads: FRED / ICE BofA (unchanged).

The file names dgs10.csv, dgs30.csv and dfii10.csv are retained for frontend
compatibility even though their providers are no longer FRED.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, time as clock_time
from pathlib import Path
from typing import Dict, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

BJT = ZoneInfo("Asia/Shanghai")
NY = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ai_bubble" / "market_liquidity"
OUT.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "AI-Bubble-Monitor/1.0 (github.com/russell-home667/AI-bubble-monitor)",
    "Accept": "application/xml,text/xml,text/csv,application/json,text/plain,*/*",
}

MARKET = {
    "ndx": {"ticker": "^NDX", "name": "Nasdaq-100", "start": "1985-01-01", "unit": "index"},
    "sox": {"ticker": "^SOX", "name": "PHLX Semiconductor Index", "start": "1994-01-01", "unit": "index"},
    "nvda": {"ticker": "NVDA", "name": "NVIDIA", "start": "1999-01-22", "unit": "USD"},
    "qqq": {"ticker": "QQQ", "name": "Invesco QQQ", "start": "1999-03-10", "unit": "USD"},
    "rsp": {"ticker": "RSP", "name": "Invesco S&P 500 Equal Weight ETF", "start": "2003-04-24", "unit": "USD"},
}

VIX = {
    "ticker": "^VIX",
    "name": "Cboe Volatility Index",
    "start": "1990-01-02",
    "unit": "index",
    "source_url": "https://finance.yahoo.com/quote/%5EVIX/history/",
}

TREASURY_XML_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
TREASURY = {
    "dgs10": {
        "name": "10-Year Treasury Par Yield Curve Rate",
        "unit": "%",
        "data_key": "daily_treasury_yield_curve",
        "field": "BC_10YEAR",
        "start_year": 1990,
        "source": "U.S. Department of the Treasury",
        "source_symbol": "BC_10YEAR",
        "source_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
    },
    "dgs30": {
        "name": "30-Year Treasury Par Yield Curve Rate",
        "unit": "%",
        "data_key": "daily_treasury_yield_curve",
        "field": "BC_30YEAR",
        "fallback_field": "BC_30YEARDISPLAY",
        "start_year": 1990,
        "source": "U.S. Department of the Treasury",
        "source_symbol": "BC_30YEAR",
        "source_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
    },
    "dfii10": {
        "name": "10-Year Treasury Par Real Yield Curve Rate",
        "unit": "%",
        "data_key": "daily_treasury_real_yield_curve",
        "field": "TC_10YEAR",
        "start_year": 2003,
        "source": "U.S. Department of the Treasury",
        "source_symbol": "TC_10YEAR",
        "source_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_real_yield_curve",
    },
}

FRED_CREDIT = {
    "hy_oas": {
        "series": "BAMLH0A0HYM2",
        "name": "ICE BofA US High Yield Index Option-Adjusted Spread",
        "unit": "%",
        "source": "ICE BofA / FRED",
    },
    "ig_oas": {
        "series": "BAMLC0A0CM",
        "name": "ICE BofA US Corporate Index Option-Adjusted Spread",
        "unit": "%",
        "source": "ICE BofA / FRED",
    },
    "baa10y_proxy": {
        "series": "BAA10Y",
        "name": "Moody's Seasoned Baa Corporate Bond Yield Relative to 10-Year Treasury",
        "unit": "%",
        "source": "Moody's / Federal Reserve / FRED",
    },
}


def now_bjt() -> str:
    return datetime.now(BJT).isoformat(timespec="seconds")


def request_with_retry(url: str, *, params=None, timeout: int = 45, attempts: int = 3) -> requests.Response:
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i + 1 < attempts:
                time.sleep(2 ** i)
    raise RuntimeError(f"GET failed after {attempts} attempts: {url}: {last}")


def read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    out = df.copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out.to_csv(tmp, index=False)
    tmp.replace(path)


def merge_by_date(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    combined = new.copy() if existing.empty else pd.concat([existing, new], ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce")
    combined = combined.dropna(subset=["date"]).sort_values("date")
    combined = combined.drop_duplicates(subset=["date"], keep="last")
    return combined.reset_index(drop=True)


def remove_incomplete_us_session(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "date" not in df.columns:
        return df
    ny_now = datetime.now(NY)
    if ny_now.time() < clock_time(17, 0):
        today_ny = pd.Timestamp(ny_now.date())
        df = df[pd.to_datetime(df["date"]) < today_ny]
    return df.reset_index(drop=True)


def yahoo_download(key: str, meta: dict) -> pd.DataFrame:
    path = OUT / f"{key}.csv"
    existing = read_csv_if_exists(path)
    existing = remove_incomplete_us_session(existing)
    start = meta["start"]
    if not existing.empty:
        latest = pd.to_datetime(existing["date"]).max()
        start = (latest - pd.Timedelta(days=14)).strftime("%Y-%m-%d")

    raw = yf.download(
        meta["ticker"],
        start=start,
        end=None,
        auto_adjust=False,
        progress=False,
        threads=False,
        timeout=30,
    )
    if raw.empty:
        raise RuntimeError(f"Yahoo Finance returned no rows for {meta['ticker']}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.reset_index()
    date_col = "Date" if "Date" in raw.columns else raw.columns[0]
    raw = raw.rename(columns={
        date_col: "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume",
    })
    keep = [c for c in ["date", "open", "high", "low", "close", "adj_close", "volume"] if c in raw.columns]
    raw = raw[keep].copy()
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce").dt.tz_localize(None)
    for c in ["open", "high", "low", "close", "adj_close", "volume"]:
        if c in raw.columns:
            raw[c] = pd.to_numeric(raw[c], errors="coerce")
    raw = raw.dropna(subset=["date", "close"])
    raw = remove_incomplete_us_session(raw)
    if raw.empty:
        raise RuntimeError(f"Yahoo Finance returned no completed sessions for {meta['ticker']}")
    raw["source"] = "Yahoo Finance"
    raw["source_symbol"] = meta["ticker"]
    raw["fetched_at_bjt"] = now_bjt()
    raw["status"] = "confirmed"

    combined = merge_by_date(existing, raw)
    combined = remove_incomplete_us_session(combined)
    atomic_write_csv(combined, path)
    return combined


def build_qqq_rsp() -> pd.DataFrame:
    qqq = read_csv_if_exists(OUT / "qqq.csv")
    rsp = read_csv_if_exists(OUT / "rsp.csv")
    if qqq.empty or rsp.empty:
        raise RuntimeError("QQQ and RSP are required before QQQ/RSP can be calculated")
    q = qqq[["date", "close"]].rename(columns={"close": "qqq_close"})
    r = rsp[["date", "close"]].rename(columns={"close": "rsp_close"})
    df = pd.merge(q, r, on="date", how="inner").sort_values("date")
    df["close"] = df["qqq_close"] / df["rsp_close"]
    df["source"] = "Derived from Yahoo Finance QQQ and RSP"
    df["source_symbol"] = "QQQ/RSP"
    df["fetched_at_bjt"] = now_bjt()
    df["status"] = "confirmed"
    atomic_write_csv(df, OUT / "qqq_rsp.csv")
    return df


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _properties_rows(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    rows: list[dict] = []
    for elem in root.iter():
        if _local_name(elem.tag).lower() != "properties":
            continue
        row: dict[str, str] = {}
        for child in list(elem):
            row[_local_name(child.tag).upper()] = (child.text or "").strip()
        if row:
            rows.append(row)
    return rows


def fetch_treasury_year(data_key: str, year: int) -> list[dict]:
    r = request_with_retry(
        TREASURY_XML_URL,
        params={"data": data_key, "field_tdr_date_value": str(year)},
        timeout=60,
    )
    rows = _properties_rows(r.text)
    if not rows:
        raise RuntimeError(f"Treasury returned no rows for {data_key} {year}")
    return rows


def update_treasury(key: str, meta: dict) -> pd.DataFrame:
    path = OUT / f"{key}.csv"
    existing = read_csv_if_exists(path)
    current_year = datetime.now(NY).year
    if existing.empty:
        years = range(int(meta["start_year"]), current_year + 1)
    else:
        latest_year = int(pd.to_datetime(existing["date"]).max().year)
        years = range(max(int(meta["start_year"]), latest_year - 1), current_year + 1)

    collected = []
    for year in years:
        rows = fetch_treasury_year(meta["data_key"], year)
        for row in rows:
            date_raw = row.get("NEW_DATE") or row.get("DATE")
            value_raw = row.get(meta["field"])
            if (value_raw is None or value_raw == "") and meta.get("fallback_field"):
                value_raw = row.get(meta["fallback_field"])
            collected.append({"date": date_raw, "value": value_raw})

    df = pd.DataFrame(collected)
    if df.empty:
        raise RuntimeError(f"No Treasury observations parsed for {key}")
    df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True).dt.tz_convert(None)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).sort_values("date")
    if df.empty:
        raise RuntimeError(f"No valid Treasury observations parsed for {key}")
    df["source"] = meta["source"]
    df["source_symbol"] = meta["source_symbol"]
    df["endpoint"] = f"Treasury XML {meta['data_key']}"
    df["fetched_at_bjt"] = now_bjt()
    df["status"] = "official_close"

    combined = merge_by_date(existing, df)
    atomic_write_csv(combined, path)
    return combined


def fred_download(key: str, meta: dict) -> pd.DataFrame:
    series = meta["series"]
    path = OUT / f"{key}.csv"
    existing = read_csv_if_exists(path)
    api_key = os.getenv("FRED_API_KEY", "").strip()
    if api_key:
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {"series_id": series, "api_key": api_key, "file_type": "json", "sort_order": "asc"}
        payload = request_with_retry(url, params=params).json()
        rows = payload.get("observations", [])
        df = pd.DataFrame({"date": [x.get("date") for x in rows], "value": [x.get("value") for x in rows]})
        endpoint = "FRED API"
    else:
        from io import StringIO
        text = request_with_retry("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series}).text
        raw = pd.read_csv(StringIO(text))
        date_col = "DATE" if "DATE" in raw.columns else ("observation_date" if "observation_date" in raw.columns else raw.columns[0])
        value_col = series if series in raw.columns else raw.columns[-1]
        df = raw[[date_col, value_col]].rename(columns={date_col: "date", value_col: "value"})
        endpoint = "FRED public CSV"

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"].replace(".", np.nan), errors="coerce")
    df = df.dropna(subset=["date", "value"]).sort_values("date")
    if not existing.empty:
        cutoff = pd.to_datetime(existing["date"]).max() - pd.Timedelta(days=35)
        df = df[df["date"] >= cutoff]
    df["source"] = meta["source"]
    df["source_symbol"] = series
    df["endpoint"] = endpoint
    df["fetched_at_bjt"] = now_bjt()
    df["status"] = "confirmed"
    combined = merge_by_date(existing, df)
    atomic_write_csv(combined, path)
    return combined


def pct_change(close: pd.Series, periods: int) -> Optional[float]:
    s = pd.to_numeric(close, errors="coerce").dropna()
    if len(s) <= periods:
        return None
    old, new = float(s.iloc[-periods - 1]), float(s.iloc[-1])
    return None if old == 0 else (new / old - 1.0) * 100.0


def _round(value, digits: int = 4):
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def summary_for_price(path: Path, *, unit: str, name: str, source_url: str) -> Optional[dict]:
    df = read_csv_if_exists(path)
    if df.empty or "close" not in df.columns:
        return None
    df = df.dropna(subset=["date", "close"]).sort_values("date")
    s = pd.to_numeric(df["close"], errors="coerce").dropna()
    if s.empty:
        return None
    last_idx = s.index[-1]
    last = float(s.loc[last_idx])
    date = pd.to_datetime(df.loc[last_idx, "date"])
    sma20 = float(s.rolling(20).mean().iloc[-1]) if len(s) >= 20 else None
    sma50 = float(s.rolling(50).mean().iloc[-1]) if len(s) >= 50 else None
    sma200 = float(s.rolling(200).mean().iloc[-1]) if len(s) >= 200 else None
    ath = float(s.max())
    age_days = (pd.Timestamp.now(tz=BJT).tz_localize(None).normalize() - date.normalize()).days
    return {
        "name": name,
        "observation_date": date.strftime("%Y-%m-%d"),
        "value": round(last, 6),
        "unit": unit,
        "change_1d_pct": _round(pct_change(s, 1)),
        "change_5d_pct": _round(pct_change(s, 5)),
        "change_20d_pct": _round(pct_change(s, 20)),
        "sma20": _round(sma20, 6),
        "sma50": _round(sma50, 6),
        "sma200": _round(sma200, 6),
        "distance_from_200dma_pct": _round((last / sma200 - 1) * 100, 4) if sma200 else None,
        "ath_drawdown_pct": _round((last / ath - 1) * 100, 4) if ath else None,
        "source": str(df.iloc[-1].get("source", "")),
        "source_symbol": str(df.iloc[-1].get("source_symbol", "")),
        "source_url": source_url,
        "fetched_at_bjt": str(df.iloc[-1].get("fetched_at_bjt", "")),
        "status": "fresh" if age_days <= 4 else "stale",
        "data_layer": "daily_close",
    }


def summary_for_series(path: Path, *, name: str, unit: str, source_url: str) -> Optional[dict]:
    df = read_csv_if_exists(path)
    if df.empty or "value" not in df.columns:
        return None
    df = df.dropna(subset=["date", "value"]).sort_values("date")
    s = pd.to_numeric(df["value"], errors="coerce").dropna()
    if s.empty:
        return None
    idx = s.index[-1]
    date = pd.to_datetime(df.loc[idx, "date"])
    age_days = (pd.Timestamp.now(tz=BJT).tz_localize(None).normalize() - date.normalize()).days
    return {
        "name": name,
        "observation_date": date.strftime("%Y-%m-%d"),
        "value": round(float(s.loc[idx]), 6),
        "unit": unit,
        "change_1obs": _round(float(s.iloc[-1] - s.iloc[-2]), 6) if len(s) >= 2 else None,
        "change_5obs": _round(float(s.iloc[-1] - s.iloc[-6]), 6) if len(s) >= 6 else None,
        "change_20obs": _round(float(s.iloc[-1] - s.iloc[-21]), 6) if len(s) >= 21 else None,
        "source": str(df.iloc[-1].get("source", "")),
        "source_symbol": str(df.iloc[-1].get("source_symbol", "")),
        "source_url": source_url,
        "fetched_at_bjt": str(df.iloc[-1].get("fetched_at_bjt", "")),
        "status": "fresh" if age_days <= 5 else "stale",
        "data_layer": "official_close",
    }


def overlay_live_quotes(indicators: Dict[str, dict]) -> None:
    path = OUT / "market_quotes.json"
    if not path.exists():
        return
    try:
        quotes = (json.loads(path.read_text(encoding="utf-8")).get("quotes") or {})
    except Exception:
        return

    for key in ("vix", "dgs10", "dgs30"):
        ind = indicators.get(key)
        q = quotes.get(key)
        if not ind or not q or q.get("price") is None:
            continue
        ind["close_value"] = ind.get("value")
        ind["close_observation_date"] = ind.get("observation_date")
        ind["close_source"] = ind.get("source")
        ind["close_source_url"] = ind.get("source_url")
        ind["value"] = q.get("price")
        ind["live_quote_timestamp"] = q.get("timestamp")
        ind["live_quote_source"] = q.get("source")
        ind["live_quote_status"] = q.get("quote_status")
        ind["live_change_1d_pct"] = q.get("change_1d_pct")
        ind["display_layer"] = "live_quote"


def write_latest(errors: Dict[str, str]) -> None:
    indicators: Dict[str, dict] = {}
    price_defs = {
        "ndx": ("Nasdaq-100", "index", "https://finance.yahoo.com/quote/%5ENDX/history/"),
        "sox": ("PHLX Semiconductor Index", "index", "https://finance.yahoo.com/quote/%5ESOX/history/"),
        "nvda": ("NVIDIA", "USD", "https://finance.yahoo.com/quote/NVDA/history/"),
        "qqq_rsp": ("QQQ / RSP concentration ratio", "ratio", "https://finance.yahoo.com/"),
        "vix": (VIX["name"], VIX["unit"], VIX["source_url"]),
    }
    for key, (name, unit, source_url) in price_defs.items():
        x = summary_for_price(OUT / f"{key}.csv", unit=unit, name=name, source_url=source_url)
        if x:
            indicators[key] = x

    for key, meta in TREASURY.items():
        x = summary_for_series(
            OUT / f"{key}.csv",
            name=meta["name"],
            unit=meta["unit"],
            source_url=meta["source_url"],
        )
        if x:
            indicators[key] = x

    for key, meta in FRED_CREDIT.items():
        x = summary_for_series(
            OUT / f"{key}.csv",
            name=meta["name"],
            unit=meta["unit"],
            source_url=f"https://fred.stlouisfed.org/series/{meta['series']}",
        )
        if x:
            indicators[key] = x

    overlay_live_quotes(indicators)

    payload = {
        "module": "AI Bubble Monitor - Market & Liquidity",
        "step": 5,
        "timezone": "Asia/Shanghai",
        "generated_at_bjt": now_bjt(),
        "indicators": indicators,
        "errors": errors,
        "notes": {
            "market_close_policy": "Yahoo current-session daily bars are excluded until 17:00 America/New_York; stored Yahoo histories are completed sessions only.",
            "treasury_nominal": "dgs10/dgs30 CSV history is rebuilt from the U.S. Treasury Daily Treasury Par Yield Curve. Latest dashboard values may be overlaid by Yahoo ^TNX/^TYX intraday quotes; close_* fields preserve the official Treasury daily close.",
            "treasury_real": "dfii10 CSV history is rebuilt from the U.S. Treasury Daily Treasury Par Real Yield Curve (10-year field TC_10YEAR). No intraday proxy is substituted.",
            "vix": "VIX history and current quote use Yahoo Finance ^VIX. Cboe historical CSV is no longer used by this module.",
            "hy_ig_history": "ICE BofA/FRED credit-spread series remain unchanged.",
            "qqq_rsp": "Derived daily from QQQ close divided by RSP close; higher values indicate stronger mega-cap/tech concentration relative to equal-weight S&P 500.",
        },
    }
    tmp = OUT / "latest.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT / "latest.json")


def run_group(group: str) -> Dict[str, str]:
    errors: Dict[str, str] = {}

    if group in {"all", "market"}:
        for key, meta in MARKET.items():
            try:
                yahoo_download(key, meta)
                print(f"OK market {key}")
            except Exception as exc:  # noqa: BLE001
                errors[key] = str(exc)
                print(f"ERROR market {key}: {exc}", file=sys.stderr)
        try:
            build_qqq_rsp()
            print("OK derived qqq_rsp")
        except Exception as exc:  # noqa: BLE001
            errors["qqq_rsp"] = str(exc)
            print(f"ERROR qqq_rsp: {exc}", file=sys.stderr)

    if group in {"all", "vix"}:
        try:
            yahoo_download("vix", VIX)
            print("OK Yahoo VIX ^VIX")
        except Exception as exc:  # noqa: BLE001
            errors["vix"] = str(exc)
            print(f"ERROR vix: {exc}", file=sys.stderr)

    if group in {"all", "macro"}:
        for key in ("dgs10", "dgs30", "dfii10"):
            try:
                update_treasury(key, TREASURY[key])
                print(f"OK Treasury {key}")
            except Exception as exc:  # noqa: BLE001
                errors[key] = str(exc)
                print(f"ERROR Treasury {key}: {exc}", file=sys.stderr)

    if group in {"all", "credit"}:
        for key, meta in FRED_CREDIT.items():
            try:
                fred_download(key, meta)
                print(f"OK FRED credit {key}")
            except Exception as exc:  # noqa: BLE001
                errors[key] = str(exc)
                print(f"ERROR credit {key}: {exc}", file=sys.stderr)

    write_latest(errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=["all", "market", "vix", "macro", "credit"], default="all")
    args = parser.parse_args()
    errors = run_group(args.group)
    expected = {
        "market": {"ndx", "sox", "nvda", "qqq", "rsp", "qqq_rsp"},
        "vix": {"vix"},
        "macro": {"dfii10", "dgs10", "dgs30"},
        "credit": {"hy_oas", "ig_oas", "baa10y_proxy"},
    }
    if args.group != "all" and expected[args.group].issubset(errors.keys()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
