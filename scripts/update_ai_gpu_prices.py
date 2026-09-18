#!/usr/bin/env python3
"""Step 8: GPU rental price monitor for the AI Bubble Monitor.

Primary source: Vast.ai verified on-demand marketplace offers when VAST_API_KEY
is configured. Fallback/reference source: Runpod Community Cloud published
prices, so the pipeline can run before a Vast API key is added.

Outputs:
  data/ai_bubble/gpu_rental_prices/snapshots.csv
  data/ai_bubble/gpu_rental_prices/daily.csv
  data/ai_bubble/gpu_rental_prices/composite_daily.csv
  data/ai_bubble/gpu_rental_prices/latest.json
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup

BJT = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ai_bubble" / "gpu_rental_prices"
OUT.mkdir(parents=True, exist_ok=True)

RUNPOD_INDEX = "https://www.runpod.io/gpu-models"

GPUS = {
    "H100": {"vast_name": "H100_SXM", "runpod_label": "H100 SXM", "variant": "H100 SXM 80GB"},
    "H200": {"vast_name": "H200", "runpod_label": "H200", "variant": "H200 SXM 141GB"},
    "B200": {"vast_name": "B200", "runpod_label": "B200", "variant": "B200 180/192GB"},
}

# Emergency anchors are used only if Runpod's public page cannot be parsed.
# They are intentionally marked STALE_ANCHOR and never treated as live market data.
EMERGENCY_RUNPOD = {"H100": 2.69, "H200": 3.59, "B200": 5.98}
HEADERS = {
    "User-Agent": "Mozilla/5.0 AI-Bubble-Monitor/1.0",
    "Accept": "text/html,application/xhtml+xml,application/json,*/*",
}


def now_bjt() -> datetime:
    return datetime.now(BJT)


def pct_change(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0) or pd.isna(a) or pd.isna(b):
        return None
    return (float(a) / float(b) - 1.0) * 100.0


def get_runpod_prices() -> tuple[dict[str, float], str]:
    try:
        r = requests.get(RUNPOD_INDEX, headers=HEADERS, timeout=30)
        r.raise_for_status()
        text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
        prices: dict[str, float] = {}
        for gpu, cfg in GPUS.items():
            label = cfg["runpod_label"]
            pos = text.find(label)
            if pos < 0:
                raise RuntimeError(f"Runpod label not found: {label}")
            window = text[pos : pos + 500]
            m = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)\s*/hr", window, re.I)
            if not m:
                raise RuntimeError(f"Runpod price not found after {label}")
            prices[gpu] = float(m.group(1))
        return prices, "LIVE_PUBLIC_PAGE"
    except Exception as exc:
        print(f"Runpod public-page parse failed; using emergency anchors: {exc}")
        return dict(EMERGENCY_RUNPOD), "STALE_ANCHOR"


def get_vast_stats(api_key: str, vast_name: str) -> dict[str, Any]:
    """Query current rentable Vast.ai offers through the official CLI.

    The Vast CLI is preferred over hand-coding a private/legacy endpoint because
    Vast evolves its API and keeps the CLI/SDK aligned with the current search
    contract.  We only observe offers; the script never rents an instance.
    """
    query = (
        f"gpu_name = {vast_name} "
        "verified = true "
        "rentable = true "
        "reliability >= 0.95"
    )
    cmd = [
        "vastai", "search", "offers", query,
        "--type", "on-demand",
        "--order", "dph_total",
        "--limit", "500",
        "--raw",
        "--api-key", api_key,
    ]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"Vast CLI failed ({proc.returncode}): {err[:500]}")

    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError(f"Vast CLI returned empty output for {vast_name}")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Vast CLI returned non-JSON output for {vast_name}: {raw[:300]}") from exc

    if isinstance(body, list):
        offers = body
    elif isinstance(body, dict):
        offers = body.get("offers") or body.get("results") or body.get("data") or []
        if isinstance(offers, dict):
            offers = [offers]
    else:
        offers = []

    per_gpu: list[float] = []
    for offer in offers:
        try:
            total = float(offer.get("dph_total"))
            n = int(float(offer.get("num_gpus") or 1))
            price = total / max(n, 1)
            if math.isfinite(price) and 0.05 < price < 100:
                per_gpu.append(price)
        except Exception:
            continue

    if not per_gpu:
        raise RuntimeError(f"No valid Vast offers for {vast_name}")

    s = pd.Series(per_gpu, dtype=float)
    return {
        "offers_count": int(len(s)),
        "market_min": float(s.min()),
        "market_p25": float(s.quantile(0.25)),
        "market_median": float(s.median()),
        "market_p75": float(s.quantile(0.75)),
        "market_max": float(s.max()),
    }


def merge_snapshots(fresh: pd.DataFrame) -> pd.DataFrame:
    path = OUT / "snapshots.csv"
    if path.exists():
        old = pd.read_csv(path)
        df = pd.concat([old, fresh], ignore_index=True, sort=False)
    else:
        df = fresh.copy()
    df = df.drop_duplicates(subset=["snapshot_bjt", "gpu"], keep="last")
    df = df.sort_values(["snapshot_bjt", "gpu"]).reset_index(drop=True)
    df.to_csv(path, index=False)
    return df


def build_daily(snapshots: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (date_bjt, gpu, source_series), grp in snapshots.groupby(["date_bjt", "gpu", "source_series"], dropna=False):
        vals = pd.to_numeric(grp["price_usd_per_gpu_hr"], errors="coerce").dropna()
        refs = pd.to_numeric(grp["runpod_reference_usd_per_gpu_hr"], errors="coerce").dropna()
        if vals.empty:
            continue
        rows.append({
            "date_bjt": str(date_bjt),
            "gpu": gpu,
            "source_series": source_series,
            "daily_price_usd_per_gpu_hr": float(vals.median()),
            "daily_low": float(vals.min()),
            "daily_high": float(vals.max()),
            "samples": int(len(vals)),
            "runpod_reference_usd_per_gpu_hr": float(refs.median()) if not refs.empty else None,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date_bjt"] = pd.to_datetime(df["date_bjt"], errors="coerce")
    df = df.sort_values(["gpu", "source_series", "date_bjt"]).reset_index(drop=True)
    for col in ["index", "change_7d_pct", "change_30d_pct", "change_90d_pct"]:
        df[col] = None
    for (gpu, src), idxs in df.groupby(["gpu", "source_series"]).groups.items():
        idxs = list(idxs)
        first_price = float(df.loc[idxs[0], "daily_price_usd_per_gpu_hr"])
        for i in idxs:
            current_date = df.loc[i, "date_bjt"]
            current_price = float(df.loc[i, "daily_price_usd_per_gpu_hr"])
            df.at[i, "index"] = current_price / first_price * 100.0 if first_price else None
            for days, col in [(7, "change_7d_pct"), (30, "change_30d_pct"), (90, "change_90d_pct")]:
                target = current_date - timedelta(days=days)
                candidates = [j for j in idxs if df.loc[j, "date_bjt"] <= target]
                if candidates:
                    j = candidates[-1]
                    old = float(df.loc[j, "daily_price_usd_per_gpu_hr"])
                    df.at[i, col] = pct_change(current_price, old)
    for c in ["daily_price_usd_per_gpu_hr", "daily_low", "daily_high", "runpod_reference_usd_per_gpu_hr", "index", "change_7d_pct", "change_30d_pct", "change_90d_pct"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").round(4)
    out = df.copy()
    out["date_bjt"] = out["date_bjt"].dt.strftime("%Y-%m-%d")
    out.to_csv(OUT / "daily.csv", index=False)
    return df


def build_composite(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()
    rows = []
    for (date_bjt, src), grp in daily.groupby(["date_bjt", "source_series"]):
        indices = pd.to_numeric(grp["index"], errors="coerce").dropna()
        if len(indices) < 2:
            continue
        rows.append({
            "date_bjt": date_bjt,
            "source_series": src,
            "gpu_count": int(len(indices)),
            "composite_index": float(indices.mean()),
        })
    comp = pd.DataFrame(rows)
    if comp.empty:
        return comp
    comp = comp.sort_values(["source_series", "date_bjt"]).reset_index(drop=True)
    comp["date_bjt"] = pd.to_datetime(comp["date_bjt"])
    comp["change_7d_pct"] = None
    comp["change_30d_pct"] = None
    comp["change_90d_pct"] = None
    for src, idxs in comp.groupby("source_series").groups.items():
        idxs = list(idxs)
        for i in idxs:
            d = comp.loc[i, "date_bjt"]
            cur = float(comp.loc[i, "composite_index"])
            for days, col in [(7, "change_7d_pct"), (30, "change_30d_pct"), (90, "change_90d_pct")]:
                target = d - timedelta(days=days)
                candidates = [j for j in idxs if comp.loc[j, "date_bjt"] <= target]
                if candidates:
                    old = float(comp.loc[candidates[-1], "composite_index"])
                    comp.at[i, col] = pct_change(cur, old)
    for c in ["composite_index", "change_7d_pct", "change_30d_pct", "change_90d_pct"]:
        comp[c] = pd.to_numeric(comp[c], errors="coerce").round(4)
    out = comp.copy()
    out["date_bjt"] = out["date_bjt"].dt.strftime("%Y-%m-%d")
    out.to_csv(OUT / "composite_daily.csv", index=False)
    return comp


def main() -> None:
    now = now_bjt()
    snapshot = now.isoformat(timespec="seconds")
    runpod, runpod_status = get_runpod_prices()
    api_key = os.getenv("VAST_API_KEY", "").strip()
    vast_error: str | None = None
    rows = []

    vast_results: dict[str, dict[str, Any]] = {}
    if api_key:
        for gpu, cfg in GPUS.items():
            try:
                vast_results[gpu] = get_vast_stats(api_key, cfg["vast_name"])
            except Exception as exc:
                vast_error = f"{gpu}: {exc}" if vast_error is None else vast_error + f"; {gpu}: {exc}"

    for gpu, cfg in GPUS.items():
        stats = vast_results.get(gpu)
        if stats:
            price = stats["market_median"]
            source_series = "vast_verified_ondemand_median"
            source = "Vast.ai verified on-demand marketplace"
            source_url = "https://console.vast.ai/"
            status = "LIVE_MARKET"
        else:
            price = runpod[gpu]
            source_series = "runpod_community_reference"
            source = "Runpod Community Cloud public pricing"
            source_url = RUNPOD_INDEX
            status = "REFERENCE_FALLBACK" if runpod_status == "LIVE_PUBLIC_PAGE" else "STALE_ANCHOR"
            stats = {
                "offers_count": None,
                "market_min": None,
                "market_p25": None,
                "market_median": None,
                "market_p75": None,
                "market_max": None,
            }
        rows.append({
            "snapshot_bjt": snapshot,
            "date_bjt": now.strftime("%Y-%m-%d"),
            "hour_bjt": now.strftime("%H:%M:%S"),
            "gpu": gpu,
            "variant": cfg["variant"],
            "source_series": source_series,
            "price_usd_per_gpu_hr": round(float(price), 4),
            "runpod_reference_usd_per_gpu_hr": round(float(runpod[gpu]), 4),
            **{k: round(v, 4) if isinstance(v, float) else v for k, v in stats.items()},
            "source": source,
            "source_url": source_url,
            "status": status,
        })

    fresh = pd.DataFrame(rows)
    snapshots = merge_snapshots(fresh)
    daily = build_daily(snapshots)
    composite = build_composite(daily)

    latest_gpus: dict[str, Any] = {}
    active_series: set[str] = set()
    for gpu in GPUS:
        snap = snapshots[snapshots["gpu"] == gpu].sort_values("snapshot_bjt").iloc[-1]
        source_series = str(snap["source_series"])
        active_series.add(source_series)
        g = daily[(daily["gpu"] == gpu) & (daily["source_series"] == source_series)].sort_values("date_bjt")
        if g.empty:
            continue
        r = g.iloc[-1]
        latest_gpus[gpu] = {
            "variant": GPUS[gpu]["variant"],
            "date_bjt": r["date_bjt"].strftime("%Y-%m-%d"),
            "daily_price_usd_per_gpu_hr": float(r["daily_price_usd_per_gpu_hr"]),
            "source_series": source_series,
            "index": None if pd.isna(r["index"]) else float(r["index"]),
            "change_7d_pct": None if pd.isna(r["change_7d_pct"]) else float(r["change_7d_pct"]),
            "change_30d_pct": None if pd.isna(r["change_30d_pct"]) else float(r["change_30d_pct"]),
            "change_90d_pct": None if pd.isna(r["change_90d_pct"]) else float(r["change_90d_pct"]),
            "runpod_reference_usd_per_gpu_hr": float(r["runpod_reference_usd_per_gpu_hr"]),
            "latest_snapshot_bjt": snap["snapshot_bjt"],
            "offers_count": None if pd.isna(snap.get("offers_count")) else int(float(snap["offers_count"])),
            "market_min": None if pd.isna(snap.get("market_min")) else float(snap["market_min"]),
            "market_p25": None if pd.isna(snap.get("market_p25")) else float(snap["market_p25"]),
            "market_median": None if pd.isna(snap.get("market_median")) else float(snap["market_median"]),
            "market_p75": None if pd.isna(snap.get("market_p75")) else float(snap["market_p75"]),
            "market_max": None if pd.isna(snap.get("market_max")) else float(snap["market_max"]),
            "status": snap["status"],
            "source": snap["source"],
        }

    statuses = {k: v.get("status") for k, v in latest_gpus.items()}
    all_live = len(statuses) == len(GPUS) and all(v == "LIVE_MARKET" for v in statuses.values())
    any_stale = any(v == "STALE_ANCHOR" for v in statuses.values())
    scoring_eligible = bool(all_live and active_series == {"vast_verified_ondemand_median"})
    if scoring_eligible:
        quality_level = "live_market"
        quality_reason = "All tracked GPUs use verified live Vast.ai marketplace medians."
    elif any_stale:
        quality_level = "stale"
        quality_reason = "At least one GPU is using an emergency static anchor; GPU prices are display-only and excluded from scoring."
    else:
        quality_level = "reference"
        quality_reason = "GPU prices are Runpod public reference prices rather than live marketplace medians; display-only and excluded from scoring."

    latest_comp = None
    if not composite.empty and len(active_series) == 1:
        active = next(iter(active_series))
        c = composite[composite["source_series"] == active].sort_values("date_bjt")
        if not c.empty:
            cr = c.iloc[-1]
            latest_comp = {
                "date_bjt": cr["date_bjt"].strftime("%Y-%m-%d"),
                "source_series": cr["source_series"],
                "composite_index": float(cr["composite_index"]),
                "change_7d_pct": None if pd.isna(cr["change_7d_pct"]) else float(cr["change_7d_pct"]),
                "change_30d_pct": None if pd.isna(cr["change_30d_pct"]) else float(cr["change_30d_pct"]),
                "change_90d_pct": None if pd.isna(cr["change_90d_pct"]) else float(cr["change_90d_pct"]),
                "scoring_eligible": scoring_eligible,
            }

    latest = {
        "module": "AI Bubble Monitor - GPU Rental Price Index",
        "step": 8,
        "timezone": "Asia/Shanghai",
        "generated_at_bjt": snapshot,
        "scoring_eligible": scoring_eligible,
        "data_quality": {
            "level": quality_level,
            "scoring_eligible": scoring_eligible,
            "reason": quality_reason,
            "active_source_series": sorted(active_series),
            "gpu_statuses": statuses,
        },
        "methodology": {
            "primary": "Hourly median $/GPU/hour across verified, rentable, on-demand Vast.ai marketplace offers queried through the official Vast CLI; machine price divided by GPU count.",
            "fallback": "Runpod Community Cloud published price when VAST_API_KEY is unavailable or Vast fetch fails.",
            "daily": "Median of all hourly intraday snapshots for the same GPU and source series.",
            "source_switch_rule": "7/30/90-day changes are calculated only within the same source series, preventing false jumps when switching between Runpod and Vast.",
            "gpu_scope": ["H100 SXM", "H200", "B200"],
        },
        "vast_api_key_configured": bool(api_key),
        "vast_error": vast_error,
        "runpod_status": runpod_status,
        "gpus": latest_gpus,
        "composite": latest_comp,
        "errors": {},
    }
    (OUT / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(latest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
