#!/usr/bin/env python3
"""Ensure the latest Chicago Fed NFCI observation is present in market_liquidity/latest.json.

This is intentionally local-only: it reads the already maintained nfci.csv and does
not call FRED or any other external API. It gives the dashboard a stable JSON fallback
in addition to the direct CSV loader used by the chart/card frontend.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "ai_bubble" / "market_liquidity"
NFCI = BASE / "nfci.csv"
LATEST = BASE / "latest.json"
SGT = ZoneInfo("Asia/Singapore")


def delta(values: pd.Series, periods: int):
    if len(values) <= periods:
        return None
    return round(float(values.iloc[-1] - values.iloc[-1 - periods]), 6)


def main() -> int:
    if not NFCI.exists():
        raise SystemExit("nfci.csv missing")
    if not LATEST.exists():
        raise SystemExit("market_liquidity/latest.json missing")

    df = pd.read_csv(NFCI)
    if "date" not in df.columns or "value" not in df.columns:
        raise SystemExit(f"nfci.csv missing required columns: {list(df.columns)}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)
    if df.empty:
        raise SystemExit("nfci.csv has no valid observations")

    last = df.iloc[-1]
    values = df["value"]
    obs_date = pd.Timestamp(last["date"])
    age_days = (datetime.now(SGT).date() - obs_date.date()).days

    indicator = {
        "name": "Chicago Fed National Financial Conditions Index",
        "observation_date": obs_date.strftime("%Y-%m-%d"),
        "value": round(float(last["value"]), 6),
        "unit": "index",
        "change_1obs": delta(values, 1),
        "change_5obs": delta(values, 5),
        "change_20obs": delta(values, 20),
        "source": str(last.get("source", "Federal Reserve Bank of Chicago / FRED")),
        "source_symbol": str(last.get("source_symbol", "NFCI")),
        "source_url": "https://fred.stlouisfed.org/series/NFCI",
        "fetched_at_sgt": str(last.get("fetched_at_bjt", "")),
        "frequency": "weekly",
        "status": "fresh" if age_days <= 10 else "stale",
        "data_layer": "official_weekly",
    }

    payload = json.loads(LATEST.read_text(encoding="utf-8"))
    payload.setdefault("indicators", {})["nfci"] = indicator
    payload.setdefault("source_notes", {})["nfci"] = (
        "Chicago Fed National Financial Conditions Index (NFCI), weekly; "
        "negative values indicate looser-than-average financial conditions."
    )
    payload["nfci_summary_updated_at_sgt"] = datetime.now(SGT).isoformat(timespec="seconds")

    tmp = LATEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(LATEST)

    print(
        "NFCI summary:",
        indicator["observation_date"],
        indicator["value"],
        indicator["status"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
