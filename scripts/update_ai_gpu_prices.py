#!/usr/bin/env python3
"""GPU rental market monitor for the AI Bubble Monitor.

Sources
-------
1. Vast.ai verified on-demand marketplace offers (primary market source).
2. Runpod API v2 GPU catalog (official platform benchmark + availability).
3. Runpod public GPU models page (last-resort fallback when API is unavailable).
4. Static emergency anchors (last-resort display-only fallback).

The existing Vast-based price series remains backward compatible. A separate
cross-platform series normalizes Vast and Runpod independently and blends them
60%/40%, avoiding an invalid direct average between marketplace medians and
catalog prices.

Outputs
-------
  data/ai_bubble/gpu_rental_prices/snapshots.csv
  data/ai_bubble/gpu_rental_prices/daily.csv
  data/ai_bubble/gpu_rental_prices/composite_daily.csv
  data/ai_bubble/gpu_rental_prices/platform_daily.csv
  data/ai_bubble/gpu_rental_prices/cross_platform_composite_daily.csv
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
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup

BJT = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ai_bubble" / "gpu_rental_prices"
OUT.mkdir(parents=True, exist_ok=True)

RUNPOD_API = "https://api.runpod.io/v2/catalog/gpus"
RUNPOD_INDEX = "https://www.runpod.io/gpu-models"
RUNPOD_API_SERIES = "runpod_api_v2_community_catalog"
RUNPOD_PAGE_SERIES = "runpod_public_page_reference"
VAST_SERIES = "vast_verified_ondemand_median"
BLEND_WEIGHTS = {"vast": 0.60, "runpod": 0.40}

GPUS = {
    "H100": {
        "vast_name": "H100_SXM",
        "runpod_label": "H100 SXM",
        "variant": "H100 SXM 80GB",
        "runpod_required": ["H100"],
        "runpod_preferred": ["SXM", "80"],
        "runpod_excluded": ["H200", "B200", "NVL", "PCIE"],
    },
    "H200": {
        "vast_name": "H200",
        "runpod_label": "H200",
        "variant": "H200 SXM 141GB",
        "runpod_required": ["H200"],
        "runpod_preferred": ["SXM", "141"],
        "runpod_excluded": ["H100", "B200"],
    },
    "B200": {
        "vast_name": "B200",
        "runpod_label": "B200",
        "variant": "B200 180/192GB",
        "runpod_required": ["B200"],
        "runpod_preferred": ["180", "192"],
        "runpod_excluded": ["H100", "H200"],
    },
}

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


def finite_float(value: Any) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def normalize_text(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def match_runpod_gpu(items: list[dict[str, Any]], gpu: str) -> dict[str, Any] | None:
    cfg = GPUS[gpu]
    candidates: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        text = normalize_text(f"{item.get('id', '')} {item.get('name', '')} {item.get('pool', '')}")
        if not all(token in text for token in cfg["runpod_required"]):
            continue
        if any(token in text for token in cfg["runpod_excluded"]):
            continue
        score = 20
        for token in cfg["runpod_preferred"]:
            if token in text:
                score += 4
        if bool(item.get("community")):
            score += 3
        price = item.get("price") or {}
        if finite_float(price.get("community")) is not None:
            score += 3
        candidates.append((score, item))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], str(x[1].get("name") or x[1].get("id") or "")), reverse=True)
    return candidates[0][1]


def get_runpod_api_stats(api_key: str) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Read official Runpod API v2 catalog pricing and POD/Community availability."""
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    params = {
        "include": "AVAILABILITY",
        "product": "POD",
        "count": 1,
        "cloud": "COMMUNITY",
    }
    r = requests.get(RUNPOD_API, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    body = r.json()
    items = body.get("gpus") if isinstance(body, dict) else None
    if not isinstance(items, list) or not items:
        raise RuntimeError("Runpod API returned no GPU catalog entries")

    out: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for gpu in GPUS:
        item = match_runpod_gpu(items, gpu)
        if item is None:
            missing.append(gpu)
            continue
        prices = item.get("price") or {}
        max_count = item.get("maxCount") or {}
        community_price = finite_float(prices.get("community"))
        secure_price = finite_float(prices.get("secure"))
        if community_price is None or community_price <= 0:
            missing.append(gpu)
            continue
        data_centers = item.get("dataCenters") or []
        if not isinstance(data_centers, list):
            data_centers = []
        available_dcs = [
            d for d in data_centers
            if str((d or {}).get("availability") or "").upper() not in {"", "NONE"}
        ]
        out[gpu] = {
            "gpu_id": item.get("id"),
            "gpu_name": item.get("name"),
            "community_price": community_price,
            "secure_price": secure_price,
            "serverless_price": finite_float(prices.get("serverless")),
            "availability": str(item.get("availability") or "UNKNOWN").upper(),
            "max_count_community": max_count.get("community"),
            "max_count_secure": max_count.get("secure"),
            "data_centers_count": len(data_centers),
            "available_data_centers_count": len(available_dcs),
        }
    err = f"Missing tracked Runpod GPU matches: {', '.join(missing)}" if missing else None
    return out, err


def get_runpod_public_prices() -> tuple[dict[str, float], str]:
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
            m = re.search(r"$s*([0-9]+(?:.[0-9]+)?)s*/hr", window, re.I)
            if not m:
                raise RuntimeError(f"Runpod price not found after {label}")
            prices[gpu] = float(m.group(1))
        return prices, "LIVE_PUBLIC_PAGE"
    except Exception as exc:
        print(f"Runpod public-page parse failed; using emergency anchors: {exc}")
        return dict(EMERGENCY_RUNPOD), "STALE_ANCHOR"


def get_vast_stats(api_key: str, vast_name: str) -> dict[str, Any]:
    """Query current rentable Vast.ai offers through the official CLI."""
    query = (
        f"gpu_name={vast_name} "
        "verified=True "
        "rentable=True "
        "rented=False "
        "reliability>=0.95"
    )
    cmd = [
        "vastai", "search", "offers", query,
        "--type", "on-demand",
        "--order", "dph",
        "--limit", "500",
        "--raw",
        "--api-key", api_key,
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)
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
            raw_price = offer.get("dph_total")
            if raw_price is None:
                raw_price = offer.get("dph")
            total = float(raw_price)
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
    """Backward-compatible active price history used by the existing dashboard/scoring."""
    rows: list[dict[str, Any]] = []
    for (date_bjt, gpu, source_series), grp in snapshots.groupby(
        ["date_bjt", "gpu", "source_series"], dropna=False
    ):
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
    for (_, _), idxs in df.groupby(["gpu", "source_series"]).groups.items():
        idxs = list(idxs)
        first_price = float(df.loc[idxs[0], "daily_price_usd_per_gpu_hr"])
        for i in idxs:
            current_date = df.loc[i, "date_bjt"]
            current_price = float(df.loc[i, "daily_price_usd_per_gpu_hr"])
            df.at[i, "index"] = current_price / first_price * 100.0 if first_price else None
            for days, col in [
                (7, "change_7d_pct"),
                (30, "change_30d_pct"),
                (90, "change_90d_pct"),
            ]:
                target = current_date - timedelta(days=days)
                candidates = [j for j in idxs if df.loc[j, "date_bjt"] <= target]
                if candidates:
                    old = float(df.loc[candidates[-1], "daily_price_usd_per_gpu_hr"])
                    df.at[i, col] = pct_change(current_price, old)
    for c in [
        "daily_price_usd_per_gpu_hr", "daily_low", "daily_high",
        "runpod_reference_usd_per_gpu_hr", "index",
        "change_7d_pct", "change_30d_pct", "change_90d_pct",
    ]:
        df[c] = pd.to_numeric(df[c], errors="coerce").round(4)
    out = df.copy()
    out["date_bjt"] = out["date_bjt"].dt.strftime("%Y-%m-%d")
    out.to_csv(OUT / "daily.csv", index=False)
    return df


def build_composite(daily: pd.DataFrame) -> pd.DataFrame:
    """Backward-compatible composite for the existing active price source."""
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
    for col in ["change_7d_pct", "change_30d_pct", "change_90d_pct"]:
        comp[col] = None
    for _, idxs in comp.groupby("source_series").groups.items():
        idxs = list(idxs)
        for i in idxs:
            d = comp.loc[i, "date_bjt"]
            cur = float(comp.loc[i, "composite_index"])
            for days, col in [
                (7, "change_7d_pct"),
                (30, "change_30d_pct"),
                (90, "change_90d_pct"),
            ]:
                target = d - timedelta(days=days)
                candidates = [j for j in idxs if comp.loc[j, "date_bjt"] <= target]
                if candidates:
                    comp.at[i, col] = pct_change(
                        cur, float(comp.loc[candidates[-1], "composite_index"])
                    )
    for c in ["composite_index", "change_7d_pct", "change_30d_pct", "change_90d_pct"]:
        comp[c] = pd.to_numeric(comp[c], errors="coerce").round(4)
    out = comp.copy()
    out["date_bjt"] = out["date_bjt"].dt.strftime("%Y-%m-%d")
    out.to_csv(OUT / "composite_daily.csv", index=False)
    return comp


def build_platform_daily(snapshots: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build Vast + Runpod daily panel and normalized 60/40 cross-platform blend."""
    rows: list[dict[str, Any]] = []
    for (date_bjt, gpu), grp in snapshots.groupby(["date_bjt", "gpu"], dropna=False):
        grp = grp.sort_values("snapshot_bjt")
        vast_mask = grp["source_series"].astype(str).eq(VAST_SERIES)
        vast_vals = (
            pd.to_numeric(grp.loc[vast_mask, "market_median"], errors="coerce").dropna()
            if "market_median" in grp else pd.Series(dtype=float)
        )
        if vast_vals.empty:
            vast_vals = pd.to_numeric(
                grp.loc[vast_mask, "price_usd_per_gpu_hr"], errors="coerce"
            ).dropna()

        rp_col = (
            grp["runpod_source_series"]
            if "runpod_source_series" in grp
            else pd.Series(index=grp.index, dtype=object)
        )
        api_mask = rp_col.astype(str).eq(RUNPOD_API_SERIES)
        rp_comm = (
            pd.to_numeric(
                grp.loc[api_mask, "runpod_community_usd_per_gpu_hr"], errors="coerce"
            ).dropna()
            if "runpod_community_usd_per_gpu_hr" in grp else pd.Series(dtype=float)
        )
        rp_secure = (
            pd.to_numeric(
                grp.loc[api_mask, "runpod_secure_usd_per_gpu_hr"], errors="coerce"
            ).dropna()
            if "runpod_secure_usd_per_gpu_hr" in grp else pd.Series(dtype=float)
        )

        latest_api = grp.loc[api_mask].iloc[-1] if api_mask.any() else None
        latest_vast = grp.loc[vast_mask].iloc[-1] if vast_mask.any() else None
        rows.append({
            "date_bjt": str(date_bjt),
            "gpu": gpu,
            "vast_median_usd_per_gpu_hr": (
                float(vast_vals.median()) if not vast_vals.empty else None
            ),
            "vast_offers_count": (
                finite_float(latest_vast.get("offers_count"))
                if latest_vast is not None else None
            ),
            "vast_p25": (
                finite_float(latest_vast.get("market_p25"))
                if latest_vast is not None else None
            ),
            "vast_p75": (
                finite_float(latest_vast.get("market_p75"))
                if latest_vast is not None else None
            ),
            "runpod_community_usd_per_gpu_hr": (
                float(rp_comm.median()) if not rp_comm.empty else None
            ),
            "runpod_secure_usd_per_gpu_hr": (
                float(rp_secure.median()) if not rp_secure.empty else None
            ),
            "runpod_availability": (
                latest_api.get("runpod_availability")
                if latest_api is not None else None
            ),
            "runpod_max_count_community": (
                finite_float(latest_api.get("runpod_max_count_community"))
                if latest_api is not None else None
            ),
            "runpod_max_count_secure": (
                finite_float(latest_api.get("runpod_max_count_secure"))
                if latest_api is not None else None
            ),
            "runpod_data_centers_count": (
                finite_float(latest_api.get("runpod_data_centers_count"))
                if latest_api is not None else None
            ),
            "runpod_available_data_centers_count": (
                finite_float(latest_api.get("runpod_available_data_centers_count"))
                if latest_api is not None else None
            ),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df, pd.DataFrame()
    df["date_bjt"] = pd.to_datetime(df["date_bjt"], errors="coerce")
    df = df.sort_values(["gpu", "date_bjt"]).reset_index(drop=True)
    for col in [
        "vast_index", "runpod_index", "blended_index_60_40",
        "blended_change_7d_pct", "blended_change_30d_pct",
        "blended_change_90d_pct",
    ]:
        df[col] = None

    for _, idxs in df.groupby("gpu").groups.items():
        idxs = list(idxs)
        paired = [
            i for i in idxs
            if pd.notna(df.loc[i, "vast_median_usd_per_gpu_hr"])
            and pd.notna(df.loc[i, "runpod_community_usd_per_gpu_hr"])
        ]
        if not paired:
            continue
        first = paired[0]
        base_v = float(df.loc[first, "vast_median_usd_per_gpu_hr"])
        base_r = float(df.loc[first, "runpod_community_usd_per_gpu_hr"])
        for i in paired:
            v = float(df.loc[i, "vast_median_usd_per_gpu_hr"])
            r = float(df.loc[i, "runpod_community_usd_per_gpu_hr"])
            vi = v / base_v * 100.0 if base_v else None
            ri = r / base_r * 100.0 if base_r else None
            blend = (
                vi * BLEND_WEIGHTS["vast"] + ri * BLEND_WEIGHTS["runpod"]
                if vi is not None and ri is not None else None
            )
            df.at[i, "vast_index"] = vi
            df.at[i, "runpod_index"] = ri
            df.at[i, "blended_index_60_40"] = blend
            for days, col in [
                (7, "blended_change_7d_pct"),
                (30, "blended_change_30d_pct"),
                (90, "blended_change_90d_pct"),
            ]:
                target = df.loc[i, "date_bjt"] - timedelta(days=days)
                candidates = [
                    j for j in paired
                    if df.loc[j, "date_bjt"] <= target
                    and pd.notna(df.loc[j, "blended_index_60_40"])
                ]
                if candidates:
                    df.at[i, col] = pct_change(
                        blend, float(df.loc[candidates[-1], "blended_index_60_40"])
                    )

    numeric_cols = [
        "vast_median_usd_per_gpu_hr", "vast_offers_count", "vast_p25", "vast_p75",
        "runpod_community_usd_per_gpu_hr", "runpod_secure_usd_per_gpu_hr",
        "runpod_max_count_community", "runpod_max_count_secure",
        "runpod_data_centers_count", "runpod_available_data_centers_count",
        "vast_index", "runpod_index", "blended_index_60_40",
        "blended_change_7d_pct", "blended_change_30d_pct",
        "blended_change_90d_pct",
    ]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").round(4)
    out = df.copy()
    out["date_bjt"] = out["date_bjt"].dt.strftime("%Y-%m-%d")
    out.to_csv(OUT / "platform_daily.csv", index=False)

    comp_rows: list[dict[str, Any]] = []
    for date_bjt, grp in df.groupby("date_bjt"):
        vals = pd.to_numeric(grp["blended_index_60_40"], errors="coerce").dropna()
        if len(vals) < 2:
            continue
        comp_rows.append({
            "date_bjt": date_bjt,
            "gpu_count": int(len(vals)),
            "composite_index": float(vals.mean()),
        })
    comp = pd.DataFrame(comp_rows)
    if comp.empty:
        return df, comp

    comp = comp.sort_values("date_bjt").reset_index(drop=True)
    for col in ["change_7d_pct", "change_30d_pct", "change_90d_pct"]:
        comp[col] = None
    for i in comp.index:
        d = comp.loc[i, "date_bjt"]
        cur = float(comp.loc[i, "composite_index"])
        for days, col in [
            (7, "change_7d_pct"),
            (30, "change_30d_pct"),
            (90, "change_90d_pct"),
        ]:
            target = d - timedelta(days=days)
            candidates = [j for j in comp.index if comp.loc[j, "date_bjt"] <= target]
            if candidates:
                comp.at[i, col] = pct_change(
                    cur, float(comp.loc[candidates[-1], "composite_index"])
                )
    for c in ["composite_index", "change_7d_pct", "change_30d_pct", "change_90d_pct"]:
        comp[c] = pd.to_numeric(comp[c], errors="coerce").round(4)
    comp_out = comp.copy()
    comp_out["date_bjt"] = comp_out["date_bjt"].dt.strftime("%Y-%m-%d")
    comp_out.to_csv(OUT / "cross_platform_composite_daily.csv", index=False)
    return df, comp


def main() -> None:
    now = now_bjt()
    snapshot = now.isoformat(timespec="seconds")
    vast_key = os.getenv("VAST_API_KEY", "").strip()
    runpod_key = os.getenv("RUNPOD_API_KEY", "").strip()

    runpod_api: dict[str, dict[str, Any]] = {}
    runpod_error: str | None = None
    if runpod_key:
        try:
            runpod_api, partial_error = get_runpod_api_stats(runpod_key)
            runpod_error = partial_error
        except Exception as exc:
            runpod_error = str(exc)
    else:
        runpod_error = "RUNPOD_API_KEY not configured"

    public_prices: dict[str, float] | None = None
    public_status: str | None = None
    if len(runpod_api) < len(GPUS):
        public_prices, public_status = get_runpod_public_prices()

    vast_error: str | None = None
    vast_results: dict[str, dict[str, Any]] = {}
    if vast_key:
        for gpu, cfg in GPUS.items():
            try:
                vast_results[gpu] = get_vast_stats(vast_key, cfg["vast_name"])
            except Exception as exc:
                msg = f"{gpu}: {exc}"
                vast_error = msg if vast_error is None else vast_error + f"; {msg}"

    rows: list[dict[str, Any]] = []
    for gpu, cfg in GPUS.items():
        rp = runpod_api.get(gpu)
        if rp:
            rp_reference = float(rp["community_price"])
            rp_source_series = RUNPOD_API_SERIES
            rp_source = "Runpod API v2 Community catalog"
            rp_status = "LIVE_API_V2"
        else:
            rp_reference = float((public_prices or EMERGENCY_RUNPOD)[gpu])
            rp_source_series = (
                RUNPOD_PAGE_SERIES
                if public_status == "LIVE_PUBLIC_PAGE"
                else "runpod_emergency_anchor"
            )
            rp_source = (
                "Runpod public GPU models page"
                if public_status == "LIVE_PUBLIC_PAGE"
                else "Emergency static anchor"
            )
            rp_status = public_status or "STALE_ANCHOR"
            rp = {}

        stats = vast_results.get(gpu)
        if stats:
            price = stats["market_median"]
            source_series = VAST_SERIES
            source = "Vast.ai verified on-demand marketplace"
            source_url = "https://console.vast.ai/"
            status = "LIVE_MARKET"
        else:
            price = rp_reference
            source_series = (
                RUNPOD_API_SERIES if rp_status == "LIVE_API_V2" else rp_source_series
            )
            source = rp_source
            source_url = RUNPOD_API if rp_status == "LIVE_API_V2" else RUNPOD_INDEX
            status = (
                "REFERENCE_FALLBACK"
                if rp_status in {"LIVE_API_V2", "LIVE_PUBLIC_PAGE"}
                else "STALE_ANCHOR"
            )
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
            "runpod_reference_usd_per_gpu_hr": round(rp_reference, 4),
            "runpod_source_series": rp_source_series,
            "runpod_status": rp_status,
            "runpod_community_usd_per_gpu_hr": (
                round(float(rp.get("community_price")), 4)
                if rp.get("community_price") is not None else round(rp_reference, 4)
            ),
            "runpod_secure_usd_per_gpu_hr": (
                round(float(rp.get("secure_price")), 4)
                if rp.get("secure_price") is not None else None
            ),
            "runpod_serverless_usd_per_gpu_hr": (
                round(float(rp.get("serverless_price")), 4)
                if rp.get("serverless_price") is not None else None
            ),
            "runpod_availability": rp.get("availability"),
            "runpod_max_count_community": rp.get("max_count_community"),
            "runpod_max_count_secure": rp.get("max_count_secure"),
            "runpod_data_centers_count": rp.get("data_centers_count"),
            "runpod_available_data_centers_count": rp.get(
                "available_data_centers_count"
            ),
            "runpod_gpu_id": rp.get("gpu_id"),
            "runpod_gpu_name": rp.get("gpu_name"),
            **{
                k: round(v, 4) if isinstance(v, float) else v
                for k, v in stats.items()
            },
            "source": source,
            "source_url": source_url,
            "status": status,
        })

    fresh = pd.DataFrame(rows)
    snapshots = merge_snapshots(fresh)
    daily = build_daily(snapshots)
    composite = build_composite(daily)
    platform_daily, cross_comp = build_platform_daily(snapshots)

    latest_gpus: dict[str, Any] = {}
    active_series: set[str] = set()
    for gpu in GPUS:
        snap = snapshots[snapshots["gpu"] == gpu].sort_values("snapshot_bjt").iloc[-1]
        source_series = str(snap["source_series"])
        active_series.add(source_series)
        g = daily[
            (daily["gpu"] == gpu) & (daily["source_series"] == source_series)
        ].sort_values("date_bjt")
        if g.empty:
            continue
        r = g.iloc[-1]
        p = platform_daily[
            platform_daily["gpu"] == gpu
        ].sort_values("date_bjt")
        pr = p.iloc[-1] if not p.empty else None
        runpod_live = str(snap.get("runpod_status") or "") == "LIVE_API_V2"

        latest_gpus[gpu] = {
            "variant": GPUS[gpu]["variant"],
            "date_bjt": r["date_bjt"].strftime("%Y-%m-%d"),
            "daily_price_usd_per_gpu_hr": float(
                r["daily_price_usd_per_gpu_hr"]
            ),
            "source_series": source_series,
            "index": None if pd.isna(r["index"]) else float(r["index"]),
            "change_7d_pct": (
                None if pd.isna(r["change_7d_pct"])
                else float(r["change_7d_pct"])
            ),
            "change_30d_pct": (
                None if pd.isna(r["change_30d_pct"])
                else float(r["change_30d_pct"])
            ),
            "change_90d_pct": (
                None if pd.isna(r["change_90d_pct"])
                else float(r["change_90d_pct"])
            ),
            "runpod_reference_usd_per_gpu_hr": float(
                r["runpod_reference_usd_per_gpu_hr"]
            ),
            "latest_snapshot_bjt": snap["snapshot_bjt"],
            "offers_count": (
                None if pd.isna(snap.get("offers_count"))
                else int(float(snap["offers_count"]))
            ),
            "market_min": (
                None if pd.isna(snap.get("market_min"))
                else float(snap["market_min"])
            ),
            "market_p25": (
                None if pd.isna(snap.get("market_p25"))
                else float(snap["market_p25"])
            ),
            "market_median": (
                None if pd.isna(snap.get("market_median"))
                else float(snap["market_median"])
            ),
            "market_p75": (
                None if pd.isna(snap.get("market_p75"))
                else float(snap["market_p75"])
            ),
            "market_max": (
                None if pd.isna(snap.get("market_max"))
                else float(snap["market_max"])
            ),
            "status": snap["status"],
            "source": snap["source"],
            "runpod": {
                "status": snap.get("runpod_status"),
                "source_series": snap.get("runpod_source_series"),
                "gpu_id": (
                    snap.get("runpod_gpu_id")
                    if pd.notna(snap.get("runpod_gpu_id")) else None
                ),
                "gpu_name": (
                    snap.get("runpod_gpu_name")
                    if pd.notna(snap.get("runpod_gpu_name")) else None
                ),
                "community_price_usd_per_gpu_hr": (
                    None if pd.isna(snap.get("runpod_community_usd_per_gpu_hr"))
                    else float(snap.get("runpod_community_usd_per_gpu_hr"))
                ),
                "secure_price_usd_per_gpu_hr": (
                    None if pd.isna(snap.get("runpod_secure_usd_per_gpu_hr"))
                    else float(snap.get("runpod_secure_usd_per_gpu_hr"))
                ),
                "availability": (
                    snap.get("runpod_availability")
                    if pd.notna(snap.get("runpod_availability")) else None
                ),
                "max_count_community": (
                    None if pd.isna(snap.get("runpod_max_count_community"))
                    else int(float(snap.get("runpod_max_count_community")))
                ),
                "max_count_secure": (
                    None if pd.isna(snap.get("runpod_max_count_secure"))
                    else int(float(snap.get("runpod_max_count_secure")))
                ),
                "data_centers_count": (
                    None if pd.isna(snap.get("runpod_data_centers_count"))
                    else int(float(snap.get("runpod_data_centers_count")))
                ),
                "available_data_centers_count": (
                    None if pd.isna(
                        snap.get("runpod_available_data_centers_count")
                    )
                    else int(float(
                        snap.get("runpod_available_data_centers_count")
                    ))
                ),
            },
            "cross_platform": {
                "eligible": bool(
                    runpod_live
                    and snap["status"] == "LIVE_MARKET"
                    and pr is not None
                    and pd.notna(pr.get("blended_index_60_40"))
                ),
                "blend_weights": BLEND_WEIGHTS,
                "vast_index": (
                    None if pr is None or pd.isna(pr.get("vast_index"))
                    else float(pr.get("vast_index"))
                ),
                "runpod_index": (
                    None if pr is None or pd.isna(pr.get("runpod_index"))
                    else float(pr.get("runpod_index"))
                ),
                "blended_index": (
                    None if pr is None or pd.isna(
                        pr.get("blended_index_60_40")
                    )
                    else float(pr.get("blended_index_60_40"))
                ),
                "change_7d_pct": (
                    None if pr is None or pd.isna(
                        pr.get("blended_change_7d_pct")
                    )
                    else float(pr.get("blended_change_7d_pct"))
                ),
                "change_30d_pct": (
                    None if pr is None or pd.isna(
                        pr.get("blended_change_30d_pct")
                    )
                    else float(pr.get("blended_change_30d_pct"))
                ),
                "change_90d_pct": (
                    None if pr is None or pd.isna(
                        pr.get("blended_change_90d_pct")
                    )
                    else float(pr.get("blended_change_90d_pct"))
                ),
            },
        }

    statuses = {k: v.get("status") for k, v in latest_gpus.items()}
    all_vast_live = (
        len(statuses) == len(GPUS)
        and all(v == "LIVE_MARKET" for v in statuses.values())
    )
    runpod_api_live = (
        len(latest_gpus) == len(GPUS)
        and all(
            (v.get("runpod") or {}).get("status") == "LIVE_API_V2"
            for v in latest_gpus.values()
        )
    )
    any_stale = any(v == "STALE_ANCHOR" for v in statuses.values())
    scoring_eligible = bool(
        all_vast_live and active_series == {VAST_SERIES}
    )
    cross_platform_eligible = bool(all_vast_live and runpod_api_live)

    if scoring_eligible and runpod_api_live:
        quality_level = "live_market"
        quality_reason = (
            "Vast.ai live marketplace medians and Runpod API v2 "
            "catalog/availability are both active."
        )
    elif scoring_eligible:
        quality_level = "live_market"
        quality_reason = (
            "Vast.ai live marketplace medians are active; Runpod API is "
            "degraded, so cross-platform metrics are partial."
        )
    elif any_stale:
        quality_level = "stale"
        quality_reason = (
            "At least one active GPU price uses a static emergency anchor; "
            "display-only and excluded from scoring."
        )
    else:
        quality_level = "reference"
        quality_reason = (
            "At least one active GPU price uses a platform reference rather "
            "than a live Vast marketplace median; display-only and excluded "
            "from scoring."
        )

    latest_comp = None
    if not composite.empty and len(active_series) == 1:
        active = next(iter(active_series))
        c = composite[
            composite["source_series"] == active
        ].sort_values("date_bjt")
        if not c.empty:
            cr = c.iloc[-1]
            latest_comp = {
                "date_bjt": cr["date_bjt"].strftime("%Y-%m-%d"),
                "source_series": cr["source_series"],
                "composite_index": float(cr["composite_index"]),
                "change_7d_pct": (
                    None if pd.isna(cr["change_7d_pct"])
                    else float(cr["change_7d_pct"])
                ),
                "change_30d_pct": (
                    None if pd.isna(cr["change_30d_pct"])
                    else float(cr["change_30d_pct"])
                ),
                "change_90d_pct": (
                    None if pd.isna(cr["change_90d_pct"])
                    else float(cr["change_90d_pct"])
                ),
                "scoring_eligible": scoring_eligible,
            }

    latest_cross = None
    if not cross_comp.empty:
        cr = cross_comp.sort_values("date_bjt").iloc[-1]
        latest_cross = {
            "date_bjt": cr["date_bjt"].strftime("%Y-%m-%d"),
            "gpu_count": int(cr["gpu_count"]),
            "composite_index": float(cr["composite_index"]),
            "change_7d_pct": (
                None if pd.isna(cr["change_7d_pct"])
                else float(cr["change_7d_pct"])
            ),
            "change_30d_pct": (
                None if pd.isna(cr["change_30d_pct"])
                else float(cr["change_30d_pct"])
            ),
            "change_90d_pct": (
                None if pd.isna(cr["change_90d_pct"])
                else float(cr["change_90d_pct"])
            ),
            "eligible": bool(
                cross_platform_eligible
                and int(cr["gpu_count"]) == len(GPUS)
            ),
            "weights": BLEND_WEIGHTS,
            "note": (
                "Vast and Runpod are normalized independently to 100 before "
                "blending; raw prices are never directly averaged."
            ),
        }

    latest = {
        "module": "AI Bubble Monitor - GPU Rental Price Index",
        "step": 8,
        "timezone": "Asia/Shanghai",
        "generated_at_bjt": snapshot,
        "scoring_eligible": scoring_eligible,
        "cross_platform_eligible": cross_platform_eligible,
        "data_quality": {
            "level": quality_level,
            "scoring_eligible": scoring_eligible,
            "cross_platform_eligible": cross_platform_eligible,
            "reason": quality_reason,
            "active_source_series": sorted(active_series),
            "gpu_statuses": statuses,
        },
        "methodology": {
            "vast_primary": (
                "Hourly median $/GPU/hour across verified, rentable, "
                "on-demand Vast.ai marketplace offers queried through the "
                "official Vast CLI; machine price divided by GPU count."
            ),
            "runpod_secondary": (
                "Official Runpod API v2 GPU catalog Community price plus "
                "POD/Community availability; Secure price retained as an "
                "additional benchmark."
            ),
            "cross_platform": (
                "Normalize each platform price series independently to 100, "
                "then blend 60% Vast + 40% Runpod Community. This avoids "
                "directly averaging prices with different market/catalog "
                "semantics."
            ),
            "fallback": (
                "If Runpod API is unavailable, use the Runpod public "
                "GPU-models page; emergency anchors are only a final "
                "display-only fallback."
            ),
            "daily": (
                "Median of hourly intraday prices for each platform/source. "
                "Availability metadata uses the latest intraday API "
                "observation."
            ),
            "source_switch_rule": (
                "7/30/90-day changes are calculated within consistent "
                "source/index series to prevent false jumps when sources "
                "change."
            ),
            "gpu_scope": ["H100 SXM", "H200", "B200"],
        },
        "vast_api_key_configured": bool(vast_key),
        "vast_error": vast_error,
        "runpod_api_key_configured": bool(runpod_key),
        "runpod_status": (
            "LIVE_API_V2"
            if runpod_api_live else (public_status or "DEGRADED")
        ),
        "runpod_error": runpod_error,
        "gpus": latest_gpus,
        "composite": latest_comp,
        "cross_platform_composite": latest_cross,
        "errors": {},
    }
    (OUT / "latest.json").write_text(
        json.dumps(latest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(latest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
