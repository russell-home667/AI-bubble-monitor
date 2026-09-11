#!/usr/bin/env python3
"""Canonicalize NVIDIA fiscal period-end dates to official disclosure dates.

Yahoo Finance labels NVIDIA quarterly statements with month-end dates, while
NVIDIA's official fiscal period end can be several days earlier. When both an
existing official row and a fresh Yahoo month-end row are present, keeping both
would make the Yahoo row look like the newest quarter and erase official Data
Center KPI coverage in latest.json.

For every official override, this helper collapses all observations within
+/-10 days into one canonical official row, reapplies the official fields, and
rebuilds latest.json's NVIDIA snapshot from that canonical row.
"""
from pathlib import Path
import json
import math
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ai_bubble" / "compute_fundamentals"
CSV = OUT / "nvda_quarterly.csv"
OV = OUT / "nvda_official_overrides.csv"
LATEST = OUT / "latest.json"

if not CSV.exists() or not OV.exists():
    raise SystemExit(0)


def clean(v):
    if pd.isna(v):
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v.item() if hasattr(v, "item") else v


df = pd.read_csv(CSV)
ov = pd.read_csv(OV)
df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
ov["period_end"] = pd.to_datetime(ov["period_end"], errors="coerce")
df = df.dropna(subset=["period_end"]).copy()

# Fields where official disclosures should always win.
official_fields = [
    "fiscal_year", "fiscal_quarter", "data_center_revenue_usd_bn",
    "total_revenue_usd_bn", "gross_margin_pct", "inventory_usd_bn",
    "accounts_receivable_usd_bn", "dso_days", "source", "source_url",
]

for _, r in ov.iterrows():
    d = r["period_end"]
    if pd.isna(d):
        continue

    delta = (df["period_end"] - d).abs().dt.days
    candidates = df.index[delta <= 10].tolist()
    if not candidates:
        new = {c: None for c in df.columns}
        new["period_end"] = d
        df = pd.concat([df, pd.DataFrame([new])], ignore_index=True)
        target = df.index[-1]
    else:
        exact = [i for i in candidates if df.at[i, "period_end"] == d]
        target = exact[0] if exact else min(candidates, key=lambda i: abs((df.at[i, "period_end"] - d).days))

        # Preserve useful freshly fetched standard statement fields from the
        # neighboring Yahoo row before collapsing duplicates.
        freshest = candidates[-1]
        for col in df.columns:
            if col == "period_end" or col in official_fields:
                continue
            val = df.at[freshest, col]
            if pd.notna(val):
                df.at[target, col] = val

    df.at[target, "period_end"] = d
    for col in official_fields:
        if col in r.index and col in df.columns and pd.notna(r[col]) and str(r[col]).strip() != "":
            df.at[target, col] = r[col]

    # Drop all other Yahoo/duplicate observations referring to this fiscal quarter.
    drop_idx = [i for i in candidates if i != target]
    if drop_idx:
        df = df.drop(index=drop_idx)

# Sort and calculate Data Center growth on official fiscal-quarter observations.
df = df.sort_values("period_end").reset_index(drop=True)
df["data_center_revenue_usd_bn"] = pd.to_numeric(df["data_center_revenue_usd_bn"], errors="coerce")
df["fiscal_year"] = pd.to_numeric(df["fiscal_year"], errors="coerce")

for i in df.index:
    dc = df.at[i, "data_center_revenue_usd_bn"]
    if pd.isna(dc):
        continue
    prev = df.loc[:i-1]
    prev = prev[prev["data_center_revenue_usd_bn"].notna()]
    if not prev.empty:
        pdc = float(prev.iloc[-1]["data_center_revenue_usd_bn"])
        if pdc:
            df.at[i, "data_center_qoq_pct"] = (float(dc) / pdc - 1) * 100
    fy = df.at[i, "fiscal_year"]
    fq = str(df.at[i, "fiscal_quarter"])
    if pd.notna(fy):
        old = df[(df["fiscal_year"] == float(fy) - 1) & (df["fiscal_quarter"].astype(str) == fq)]
        old = old[old["data_center_revenue_usd_bn"].notna()]
        if not old.empty:
            odc = float(old.iloc[-1]["data_center_revenue_usd_bn"])
            if odc:
                df.at[i, "data_center_yoy_pct"] = (float(dc) / odc - 1) * 100

for c in ["data_center_yoy_pct", "data_center_qoq_pct", "inventory_days", "dso_days", "gross_margin_pct"]:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce").round(2)

out = df.copy()
out["period_end"] = out["period_end"].dt.strftime("%Y-%m-%d")
out.to_csv(CSV, index=False)

# Rebuild the public NVIDIA latest snapshot from the canonical last quarter.
if LATEST.exists() and not out.empty:
    payload = json.loads(LATEST.read_text(encoding="utf-8"))
    row = out.iloc[-1]
    nv = payload.setdefault("nvda", {})
    mapping = {
        "period_end": "period_end",
        "fiscal_year": "fiscal_year",
        "fiscal_quarter": "fiscal_quarter",
        "total_revenue_usd_bn": "total_revenue_usd_bn",
        "data_center_revenue_usd_bn": "data_center_revenue_usd_bn",
        "data_center_yoy_pct": "data_center_yoy_pct",
        "data_center_qoq_pct": "data_center_qoq_pct",
        "gross_margin_pct": "gross_margin_pct",
        "inventory_usd_bn": "inventory_usd_bn",
        "inventory_days": "inventory_days",
        "accounts_receivable_usd_bn": "accounts_receivable_usd_bn",
        "dso_days": "dso_days",
        "source": "source",
        "source_url": "source_url",
    }
    for dst, src in mapping.items():
        nv[dst] = clean(row.get(src))
    payload["nvda"] = nv
    LATEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"Canonical NVDA latest period: {out.iloc[-1]['period_end']}")
