#!/usr/bin/env python3
from pathlib import Path
import re


def patch_gpu() -> None:
    p = Path('scripts/update_ai_gpu_prices.py')
    s = p.read_text(encoding='utf-8')
    pattern = re.compile(
        r'    latest_gpus: dict\[str, Any\] = \{\}\n    for gpu in GPUS:.*?\n    latest_comp = None\n    if not composite\.empty:.*?\n\n    latest = \{',
        re.S,
    )
    replacement = '''    latest_gpus: dict[str, Any] = {}
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

    latest = {'''
    s2, n = pattern.subn(replacement, s, count=1)
    if n != 1:
        raise SystemExit(f'GPU active-series replacement count={n}')
    marker = '        "generated_at_bjt": snapshot,\n        "methodology": {'
    insert = '''        "generated_at_bjt": snapshot,
        "scoring_eligible": scoring_eligible,
        "data_quality": {
            "level": quality_level,
            "scoring_eligible": scoring_eligible,
            "reason": quality_reason,
            "active_source_series": sorted(active_series),
            "gpu_statuses": statuses,
        },
        "methodology": {'''
    if marker not in s2:
        raise SystemExit('GPU latest metadata insertion marker missing')
    s2 = s2.replace(marker, insert, 1)
    p.write_text(s2, encoding='utf-8')


def patch_derived() -> None:
    p = Path('scripts/calculate_ai_derived_indicators.py')
    s = p.read_text(encoding='utf-8')
    old = '''    # 6) Compute Demand Score. GPU component is included only when a same-source 30D history exists.
    gpu30 = gpu.get("composite", {}).get("change_30d_pct")
    compute_demand, coverage_weight = weighted([
        (scale(nv["data_center_yoy_pct"], 0, 150), 0.40),
        (scale(ts["rolling_3m_yoy_pct"], -20, 60), 0.30),
        (scale(gpu30, -40, 20), 0.30),
    ])
    coverage_pct = coverage_weight * 100
'''
    new = '''    # 6) Compute Demand Score. GPU contributes only when the current GPU
    # module explicitly certifies live-market scoring eligibility and has a
    # same-source 30D history. Reference/stale fallback values remain visible
    # on the dashboard but never enter the score.
    gpu_comp = gpu.get("composite") or {}
    gpu_scoring_eligible = bool(gpu.get("scoring_eligible")) and bool(gpu_comp.get("scoring_eligible"))
    gpu30 = gpu_comp.get("change_30d_pct") if gpu_scoring_eligible else None
    compute_demand, coverage_weight = weighted([
        (scale(nv["data_center_yoy_pct"], 0, 150), 0.40),
        (scale(ts["rolling_3m_yoy_pct"], -20, 60), 0.30),
        (scale(gpu30, -40, 20), 0.30),
    ])
    coverage_pct = coverage_weight * 100
'''
    if old not in s:
        raise SystemExit('Derived GPU scoring block not found')
    s = s.replace(old, new, 1)
    old_note = '''                "gpu_30d_component_available": gpu30 is not None,
                "note": "GPU weight is automatically excluded and remaining weights renormalized until 30 days of same-source GPU history exist.",'''
    new_note = '''                "gpu_30d_component_available": gpu30 is not None,
                "gpu_scoring_eligible": gpu_scoring_eligible,
                "gpu_data_quality": (gpu.get("data_quality") or {}).get("level"),
                "note": "GPU weight is included only for live-market, scoring-eligible data with 30 days of same-source history; reference/stale fallback values are excluded and remaining weights renormalized.",'''
    if old_note not in s:
        raise SystemExit('Derived GPU note block not found')
    s = s.replace(old_note, new_note, 1)
    p.write_text(s, encoding='utf-8')


def patch_frontend() -> None:
    p = Path('index.html')
    s = p.read_text(encoding='utf-8')
    old_keys = "['vix','dgs10','dgs30'].forEach(key=>{"
    new_keys = "['ndx','sox','nvda','vix','dgs10','dgs30'].forEach(key=>{"
    if old_keys not in s:
        raise SystemExit('Market overlay key list not found')
    s = s.replace(old_keys, new_keys, 1)

    old = "displayMarket.indicators[key]={...current,value:Number(quote.price),live_quote_timestamp:quote.timestamp||null,live_quote_source:quote.source||null,live_quote_status:quote.quote_status||null,display_layer:'live_quote'};"
    new = "displayMarket.indicators[key]={...current,official_value:current.value,official_observation_date:current.observation_date||null,live_value:Number(quote.price),value:Number(quote.price),live_quote_timestamp:quote.timestamp||null,live_quote_source:quote.source||null,live_quote_status:quote.quote_status||null,display_layer:'live_quote'};"
    if old not in s:
        raise SystemExit('Market overlay assignment not found')
    s = s.replace(old, new, 1)

    pattern = re.compile(r'function renderMarketCards\(m\)\{.*?\}\nfunction renderHyper', re.S)
    replacement = '''function renderMarketCards(m){
  const i=m.indicators;
  const liveMeta=(x)=>x?.display_layer==='live_quote'?`${x.live_quote_status||'QUOTE'} · ${String(x.live_quote_timestamp||'—').replace('T',' ').slice(0,19)} BJT · `:'';
  const rateDetail=(x)=>`${liveMeta(x)}official close ${num(x?.official_value,2)}% (${x?.official_observation_date||x?.observation_date||'—'}) · 20 obs Δ ${(x?.change_20obs??0)>=0?'+':''}${num(x?.change_20obs,2)} ppt`;
  const arr=[
    ['NASDAQ-100',num(i.ndx.value,0),`${liveMeta(i.ndx)}200DMA ${pct(i.ndx.distance_from_200dma_pct)} · ATH ${pct(i.ndx.ath_drawdown_pct)}`],
    ['SOX',num(i.sox.value,0),`${liveMeta(i.sox)}200DMA ${pct(i.sox.distance_from_200dma_pct)} · ATH ${pct(i.sox.ath_drawdown_pct)}`],
    ['NVIDIA','$'+num(i.nvda.value,2),`${liveMeta(i.nvda)}200DMA ${pct(i.nvda.distance_from_200dma_pct)} · ATH ${pct(i.nvda.ath_drawdown_pct)}`],
    ['VIX',num(i.vix.value,2),`${liveMeta(i.vix)}20D ${pct(i.vix.change_20d_pct)}`],
    ['US 10Y Treasury',num(i.dgs10?.value,2)+'%',rateDetail(i.dgs10)],
    ['US 30Y Treasury',num(i.dgs30?.value,2)+'%',rateDetail(i.dgs30)],
    ['10Y Real Yield',num(i.dfii10.value,2)+'%',`OFFICIAL · ${i.dfii10.observation_date||'—'} · 20 obs Δ ${i.dfii10.change_20obs>=0?'+':''}${num(i.dfii10.change_20obs,2)} ppt`],
    ['HY OAS',num(i.hy_oas.value,2)+'%',`OFFICIAL · ${i.hy_oas.observation_date||'—'} · 20 obs Δ ${i.hy_oas.change_20obs>=0?'+':''}${num(i.hy_oas.change_20obs,2)} ppt`]
  ];
  document.getElementById('marketCards').innerHTML=arr.map(x=>metricCard(...x)).join('');
}
function renderHyper'''
    s2, n = pattern.subn(replacement, s, count=1)
    if n != 1:
        raise SystemExit(f'renderMarketCards replacement count={n}')
    s = s2

    pattern = re.compile(r'function renderGpu\(g\)\{.*?\}\nfunction normalized', re.S)
    replacement = '''function renderGpu(g){
  document.getElementById('gpuCards').innerHTML=['H100','H200','B200'].map(k=>{
    const x=g.gpus[k];
    const quality=g.data_quality?.level||'unknown';
    const role=g.scoring_eligible?'SCORING':'DISPLAY ONLY';
    return metricCard(`${k} · ${x.variant}`,'$'+num(x.daily_price_usd_per_gpu_hr,2)+'/h',`${x.status} · ${role} · quality ${quality} · 30D ${x.change_30d_pct==null?'collecting':pct(x.change_30d_pct)}`)
  }).join('')
}
function normalized'''
    s2, n = pattern.subn(replacement, s, count=1)
    if n != 1:
        raise SystemExit(f'renderGpu replacement count={n}')
    p.write_text(s2, encoding='utf-8')


def main() -> None:
    patch_gpu()
    patch_derived()
    patch_frontend()
    print('P1/P2 source hardening applied')


if __name__ == '__main__':
    main()
