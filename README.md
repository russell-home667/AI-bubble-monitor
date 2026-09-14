# AI Bubble Monitor

A data-driven dashboard tracking AI investment, monetization, compute demand, cash flow, market valuation, liquidity, and breakdown risk.

All dashboard data, scripts, automated update workflows, and historical backtests are maintained in this repository.

## Macro Commodity

The Macro Commodity panel keeps the existing AI Bubble Monitor format and overlays Brent crude with Gold Spot XAU/USD using separate y-axes.

- Brent: Yahoo Finance `BZ=F`.
- Gold: XAU/USD spot, sourced primarily from the XAUS Gold Data API; `gold-api.com` is used only as a live-quote fallback.
- Gold history: `data/ai_bubble/macro/gold_xauusd.json`.
- Gold update cadence: every 30 minutes, Monday-Saturday; daily history is retained in the dashboard data file.
- Instrument policy: spot gold only. Do not substitute COMEX Gold Futures (`GC=F`) for XAU/USD.
