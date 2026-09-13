#!/usr/bin/env python3
"""Backfill long-history Rates, Credit & Liquidity data to 1990.

Goals
-----
1) Preserve the existing daily production updater.
2) Backfill public/official histories that can cover the dot-com bust and 2008 crisis.
3) Add Chicago Fed NFCI as a long-history financial-conditions proxy because the
   ICE BofA HY OAS series distributed through FRED is now license-limited to a
   short recent window.
4) Keep direct 10Y real-yield history honest: DFII10 only exists from 2003, so
   we do not manufacture a pre-2003 real-yield series.

Sources
-------
- FRED public CSV: DGS10, DGS30, DFII10, NFCI
- Cboe official VIX daily history: 1990-present

The frontend patch is intentionally small and idempotent. It overlays NFCI on
Rates, Credit & Liquidity and keeps missing pre-inception periods as gaps.
"""
from __future__ import annotations

from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

BJT = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ai_bubble" / "market_liquidity"
OUT.mkdir(parents=True, exist_ok=True)
START = pd.Timestamp("1990-01-01")

HEADERS = {
    "User-Agent": "AI-Bubble-Monitor/1.0 (github.com/russell-home667/AI-bubble-monitor)",
    "Accept": "text/csv,text/plain,*/*",
}

FRED_SERIES = {
    "dgs10": ("DGS10", "Federal Reserve Board H.15 / FRED"),
    "dgs30": ("DGS30", "Federal Reserve Board H.15 / FRED"),
    "dfii10": ("DFII10", "Federal Reserve Board H.15 / FRED"),
    "nfci": ("NFCI", "Federal Reserve Bank of Chicago / FRED"),
}

VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


def now_bjt() -> str:
    return datetime.now(BJT).isoformat(timespec="seconds")


def get_text(url: str, *, params: dict | None = None) -> str:
    last: Exception | None = None
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=45)
            r.raise_for_status()
            return r.text
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt == 2:
                break
    raise RuntimeError(f"Failed to fetch {url}: {last}")


def merge_csv(path: Path, fresh: pd.DataFrame) -> pd.DataFrame:
    if path.exists():
        old = pd.read_csv(path)
        combined = pd.concat([old, fresh], ignore_index=True, sort=False)
    else:
        combined = fresh.copy()
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce")
    combined = combined.dropna(subset=["date"]).sort_values("date")
    combined = combined[combined["date"] >= START]
    combined = combined.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    combined["date"] = combined["date"].dt.strftime("%Y-%m-%d")
    combined.to_csv(path, index=False)
    return combined


def backfill_fred(key: str, series: str, source: str) -> None:
    text = get_text(
        "https://fred.stlouisfed.org/graph/fredgraph.csv",
        params={"id": series, "cosd": START.date().isoformat()},
    )
    raw = pd.read_csv(StringIO(text))
    date_col = "DATE" if "DATE" in raw.columns else ("observation_date" if "observation_date" in raw.columns else raw.columns[0])
    value_col = series if series in raw.columns else raw.columns[-1]
    df = raw[[date_col, value_col]].rename(columns={date_col: "date", value_col: "value"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"].replace(".", pd.NA), errors="coerce")
    df = df.dropna(subset=["date", "value"])
    df = df[df["date"] >= START]
    df["source"] = source
    df["source_symbol"] = series
    df["endpoint"] = "FRED public CSV · long-history backfill"
    df["fetched_at_bjt"] = now_bjt()
    df["status"] = "confirmed"
    merged = merge_csv(OUT / f"{key}.csv", df)
    print(f"{key}: {merged['date'].min()} -> {merged['date'].max()} ({len(merged)} rows)")


def backfill_vix() -> None:
    raw = pd.read_csv(StringIO(get_text(VIX_URL)))
    raw.columns = [str(c).strip().upper() for c in raw.columns]
    if "DATE" not in raw.columns or "CLOSE" not in raw.columns:
        raise RuntimeError(f"Unexpected VIX columns: {list(raw.columns)}")
    df = raw.rename(columns={"DATE": "date", "OPEN": "open", "HIGH": "high", "LOW": "low", "CLOSE": "close"})
    keep = [c for c in ["date", "open", "high", "low", "close"] if c in df.columns]
    df = df[keep].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ["open", "high", "low", "close"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date", "close"])
    df = df[df["date"] >= START]
    df["source"] = "Cboe Global Markets"
    df["source_symbol"] = "VIX"
    df["fetched_at_bjt"] = now_bjt()
    df["status"] = "confirmed"
    merged = merge_csv(OUT / "vix.csv", df)
    print(f"vix: {merged['date'].min()} -> {merged['date'].max()} ({len(merged)} rows)")


def patch_frontend() -> None:
    path = ROOT / "index.html"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "10Y & 30Y Treasury / 10Y Real Yield / HY OAS / VIX",
        "10Y & 30Y Treasury / 10Y Real Yield / HY OAS / VIX / NFCI long-history proxy",
    )

    overlay = r'''
<script>
// LONG_HISTORY_LIQUIDITY_OVERLAY
// Adds a 1990+ public-data view without changing the live scoring methodology.
(function(){
  renderLiquidityChart=function(){
    const range=state.ranges.liquidityChart;
    const real=cutoffRows(state.raw.dfii10||[],'date',range);
    const t10=cutoffRows(state.raw.dgs10||[],'date',range);
    const t30=cutoffRows(state.raw.dgs30||[],'date',range);
    const hy=cutoffRows(state.raw.hy||[],'date',range);
    const vix=cutoffRows(state.raw.vix||[],'date',range);
    const nfci=cutoffRows(state.raw.nfci||[],'date',range);
    const dates=[...new Set([...real,...t10,...t30,...hy,...vix,...nfci].map(x=>x.date).filter(Boolean))].sort();
    const rm=new Map(real.map(x=>[x.date,x.value]));
    const t10m=new Map(t10.map(x=>[x.date,x.value]));
    const t30m=new Map(t30.map(x=>[x.date,x.value]));
    const hm=new Map(hy.map(x=>[x.date,x.value]));
    const vm=new Map(vix.map(x=>[x.date,x.close]));
    const nm=new Map(nfci.map(x=>[x.date,x.value]));
    initChart('liquidityChart').setOption({
      ...chartBase,
      grid:{...chartBase.grid,top:92,right:64},
      legend:{
        ...chartBase.legend,
        type:'scroll',
        top:34,
        left:88,
        right:72,
        itemGap:14,
        itemWidth:18,
        itemHeight:10,
        pageButtonGap:8,
        pageIconSize:10,
        pageTextStyle:{color:'#8ea2bc'},
        textStyle:{color:'#8ea2bc',fontSize:12}
      },
      xAxis:{...chartBase.xAxis,data:dates},
      yAxis:[
        {...chartBase.yAxis,name:'Yield / spread / NFCI',nameGap:16},
        {...chartBase.yAxis,name:'VIX',position:'right',nameGap:16}
      ],
      series:[
        {name:'US 10Y Treasury',type:'line',showSymbol:false,data:dates.map(d=>t10m.get(d)??null),connectNulls:false},
        {name:'US 30Y Treasury',type:'line',showSymbol:false,data:dates.map(d=>t30m.get(d)??null),connectNulls:false},
        {name:'10Y Real Yield',type:'line',showSymbol:false,data:dates.map(d=>rm.get(d)??null),connectNulls:false},
        {name:'HY OAS',type:'line',showSymbol:false,data:dates.map(d=>hm.get(d)??null),connectNulls:false},
        {name:'NFCI',type:'line',showSymbol:false,data:dates.map(d=>nm.get(d)??null),connectNulls:false,lineStyle:{type:'dashed',width:1.6}},
        {name:'VIX',type:'line',showSymbol:false,yAxisIndex:1,data:dates.map(d=>vm.get(d)??null),connectNulls:false}
      ]
    },true);
  };

  fetchCSV(BASE+'market_liquidity/nfci.csv').then(rows=>{
    state.raw.nfci=rows;
    renderLiquidityChart();
  }).catch(err=>console.warn('NFCI long-history load failed',err));
})();
</script>
'''

    marker = "// LONG_HISTORY_LIQUIDITY_OVERLAY"
    if marker in text:
        start = text.rfind("<script>", 0, text.index(marker))
        end = text.find("</script>", text.index(marker))
        if start == -1 or end == -1:
            raise RuntimeError("Could not locate existing liquidity overlay script boundaries")
        end += len("</script>")
        text = text[:start] + overlay.strip() + text[end:]
        print("Updated existing NFCI long-history overlay and legend layout")
    else:
        if "</body>" not in text:
            raise RuntimeError("index.html has no </body> tag")
        text = text.replace("</body>", overlay + "\n</body>")
        print("Patched index.html with NFCI long-history overlay")

    path.write_text(text, encoding="utf-8")


def main() -> None:
    for key, (series, source) in FRED_SERIES.items():
        backfill_fred(key, series, source)
    backfill_vix()
    patch_frontend()


if __name__ == "__main__":
    main()
