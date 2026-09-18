#!/usr/bin/env python3
"""Build lightweight frontend history files without changing canonical datasets."""
from pathlib import Path
import csv

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"data"/"ai_bubble"/"market_liquidity"
OUT=ROOT/"data"/"ai_bubble"/"frontend"/"market_liquidity"
OUT.mkdir(parents=True,exist_ok=True)

SERIES={
    "ndx.csv":["date","close"],
    "sox.csv":["date","close"],
    "nvda.csv":["date","close"],
    "googl.csv":["date","close"],
    "msft.csv":["date","close"],
    "amzn.csv":["date","close"],
    "vix.csv":["date","close"],
    "dfii10.csv":["date","value"],
    "dgs10.csv":["date","value"],
    "dgs30.csv":["date","value"],
    "hy_oas.csv":["date","value"],
}

for name,cols in SERIES.items():
    src=SRC/name
    if not src.exists():
        raise SystemExit(f"Missing canonical history: {src}")
    dst=OUT/name
    with src.open("r",encoding="utf-8-sig",newline="") as fi, dst.open("w",encoding="utf-8",newline="") as fo:
        reader=csv.DictReader(fi)
        fields=reader.fieldnames or []
        missing=[c for c in cols if c not in fields]
        if missing:
            raise SystemExit(f"{name}: missing required columns {missing}")
        writer=csv.DictWriter(fo,fieldnames=cols)
        writer.writeheader()
        for row in reader:
            if not row.get("date"):
                continue
            writer.writerow({c:row.get(c,"") for c in cols})
    print(f"{name}: {src.stat().st_size:,} -> {dst.stat().st_size:,} bytes")
