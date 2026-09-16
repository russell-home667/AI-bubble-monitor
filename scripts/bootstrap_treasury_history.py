#!/usr/bin/env python3
"""One-time fast bootstrap for Treasury history after a source change.

This script is intentionally separate from the normal incremental updater.
It rebuilds:
- dgs10.csv from U.S. Treasury Daily Treasury Par Yield Curve / BC_10YEAR
- dgs30.csv from U.S. Treasury Daily Treasury Par Yield Curve / BC_30YEAR
- dfii10.csv from U.S. Treasury Daily Treasury Par Real Yield Curve / TC_10YEAR

The nominal 10Y and 30Y series share the same yearly Treasury response, and
multiple years are fetched concurrently with a small worker pool.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

BJT = ZoneInfo("Asia/Shanghai")
NY = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ai_bubble" / "market_liquidity"
OUT.mkdir(parents=True, exist_ok=True)

TREASURY_XML_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
HEADERS = {
    "User-Agent": "AI-Bubble-Monitor/1.0 (github.com/russell-home667/AI-bubble-monitor)",
    "Accept": "application/xml,text/xml,text/plain,*/*",
}
MAX_WORKERS = 6


def now_bjt() -> str:
    return datetime.now(BJT).isoformat(timespec="seconds")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _properties_rows(xml_text: str) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    rows: list[dict[str, str]] = []
    for elem in root.iter():
        if _local_name(elem.tag).lower() != "properties":
            continue
        row: dict[str, str] = {}
        for child in list(elem):
            row[_local_name(child.tag).upper()] = (child.text or "").strip()
        if row:
            rows.append(row)
    return rows


def fetch_year(data_key: str, year: int) -> tuple[int, list[dict[str, str]]]:
    params = {"data": data_key, "field_tdr_date_value": str(year)}
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(
                TREASURY_XML_URL,
                params=params,
                headers=HEADERS,
                timeout=30,
            )
            response.raise_for_status()
            rows = _properties_rows(response.text)
            if not rows:
                raise RuntimeError(f"Treasury returned no rows for {data_key} {year}")
            print(f"OK Treasury {data_key} {year}: {len(rows)} rows", flush=True)
            return year, rows
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Treasury fetch failed for {data_key} {year}: {last_error}")


def fetch_years(data_key: str, start_year: int, end_year: int) -> list[dict[str, str]]:
    by_year: dict[int, list[dict[str, str]]] = {}
    years = list(range(start_year, end_year + 1))
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_year, data_key, year): year for year in years}
        for future in as_completed(futures):
            year, rows = future.result()
            by_year[year] = rows
    combined: list[dict[str, str]] = []
    for year in sorted(by_year):
        combined.extend(by_year[year])
    return combined


def build_series(
    rows: list[dict[str, str]],
    *,
    field: str,
    source_symbol: str,
    data_key: str,
    fallback_field: str | None = None,
) -> pd.DataFrame:
    records = []
    for row in rows:
        date_raw = row.get("NEW_DATE") or row.get("DATE")
        value_raw = row.get(field)
        if (value_raw is None or value_raw == "") and fallback_field:
            value_raw = row.get(fallback_field)
        records.append({"date": date_raw, "value": value_raw})

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True).dt.tz_convert(None)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).drop_duplicates(subset=["date"], keep="last").sort_values("date")
    if df.empty:
        raise RuntimeError(f"No valid observations for {source_symbol}")

    df["source"] = "U.S. Department of the Treasury"
    df["source_symbol"] = source_symbol
    df["endpoint"] = f"Treasury XML {data_key}"
    df["fetched_at_bjt"] = now_bjt()
    df["status"] = "official_close"
    return df.reset_index(drop=True)


def atomic_write(df: pd.DataFrame, filename: str) -> None:
    path = OUT / filename
    tmp = path.with_suffix(path.suffix + ".tmp")
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out.to_csv(tmp, index=False)
    tmp.replace(path)
    last = out.iloc[-1]
    print(f"WROTE {filename}: {len(out)} rows; latest {last['date']} = {last['value']}", flush=True)


def validate_latest(df: pd.DataFrame, name: str) -> None:
    latest = pd.to_datetime(df["date"]).max()
    age_days = (pd.Timestamp.now(tz=NY).tz_localize(None).normalize() - latest.normalize()).days
    if age_days > 10:
        raise RuntimeError(f"{name} latest observation is unexpectedly old: {latest.date()}")


def main() -> int:
    current_year = datetime.now(NY).year

    nominal_rows = fetch_years("daily_treasury_yield_curve", 1990, current_year)
    dgs10 = build_series(
        nominal_rows,
        field="BC_10YEAR",
        source_symbol="BC_10YEAR",
        data_key="daily_treasury_yield_curve",
    )
    dgs30 = build_series(
        nominal_rows,
        field="BC_30YEAR",
        fallback_field="BC_30YEARDISPLAY",
        source_symbol="BC_30YEAR",
        data_key="daily_treasury_yield_curve",
    )

    real_rows = fetch_years("daily_treasury_real_yield_curve", 2003, current_year)
    dfii10 = build_series(
        real_rows,
        field="TC_10YEAR",
        source_symbol="TC_10YEAR",
        data_key="daily_treasury_real_yield_curve",
    )

    validate_latest(dgs10, "10Y Treasury")
    validate_latest(dgs30, "30Y Treasury")
    validate_latest(dfii10, "10Y Real Yield")

    atomic_write(dgs10, "dgs10.csv")
    atomic_write(dgs30, "dgs30.csv")
    atomic_write(dfii10, "dfii10.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
