#!/usr/bin/env python3
from pathlib import Path
import re

p = Path('assets/source-links.js')
s = p.read_text(encoding='utf-8')

helpers = """
  // Audited against the acquisition scripts. yfinance price history uses
  // query2 / v8 chart; yfinance statements use fundamentals-timeseries.
  const yfPeriod1 = 1483142400; // 2016-12-31 UTC, same start used by yfinance fundamentals.
  const yfPeriod2 = Math.ceil(Date.now() / 86400000) * 86400;
  const yahooChart = symbol => `https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=max&interval=1d&includePrePost=false&events=div%2Csplits%2CcapitalGains`;
  const yahooFundamentals = symbol => `https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/${encodeURIComponent(symbol)}?symbol=${encodeURIComponent(symbol)}&type=quarterlyTotalRevenue,quarterlyOperatingRevenue,quarterlyOperatingCashFlow,quarterlyCapitalExpenditure,quarterlyDepreciationAndAmortization,quarterlyDepreciationAmortizationDepletion,quarterlyReconciledDepreciation,quarterlyDepreciation&period1=${yfPeriod1}&period2=${yfPeriod2}`;
  const fredCsv = id => `https://fred.stlouisfed.org/graph/fredgraph.csv?id=${encodeURIComponent(id)}`;
"""
if 'const yahooChart = symbol =>' not in s:
    s = s.replace("  'use strict';\n", "  'use strict';\n" + helpers + "\n", 1)

new_s = """  const S = {
    methodology: {label:'Methodology / lineage', url:'backtest.html', internal:true},
    yahooNDX: {label:'Yahoo chart API · NDX', url:yahooChart('^NDX')},
    yahooSOX: {label:'Yahoo chart API · SOX', url:yahooChart('^SOX')},
    yahooNVDA: {label:'Yahoo chart API · NVDA', url:yahooChart('NVDA')},
    yahooQQQ: {label:'Yahoo chart API · QQQ', url:yahooChart('QQQ')},
    yahooRSP: {label:'Yahoo chart API · RSP', url:yahooChart('RSP')},
    yahooBrentDaily: {label:'Yahoo daily API · BZ=F', url:yahooChart('BZ=F')},
    yahooBrent1m: {label:'Yahoo 1m API · BZ=F', url:'https://query1.finance.yahoo.com/v8/finance/chart/BZ%3DF?range=1d&interval=1m&includePrePost=true'},
    cboeVIX: {label:'Cboe CSV · VIX', url:'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'},
    fredReal10: {label:'FRED CSV · DFII10', url:fredCsv('DFII10')},
    fred10: {label:'FRED CSV · DGS10', url:fredCsv('DGS10')},
    fred30: {label:'FRED CSV · DGS30', url:fredCsv('DGS30')},
    fredHY: {label:'FRED CSV · HY OAS', url:fredCsv('BAMLH0A0HYM2')},
    fredIG: {label:'FRED CSV · IG OAS', url:fredCsv('BAMLC0A0CM')},
    fredBAA: {label:'FRED CSV · BAA10Y', url:fredCsv('BAA10Y')},
    yfMSFT: {label:'Yahoo fundamentals API · MSFT', url:yahooFundamentals('MSFT')},
    yfGOOGL: {label:'Yahoo fundamentals API · GOOGL', url:yahooFundamentals('GOOGL')},
    yfAMZN: {label:'Yahoo fundamentals API · AMZN', url:yahooFundamentals('AMZN')},
    yfMETA: {label:'Yahoo fundamentals API · META', url:yahooFundamentals('META')},
    yfORCL: {label:'Yahoo fundamentals API · ORCL', url:yahooFundamentals('ORCL')},
    amznQ226SEC: {label:'SEC 10-Q · AMZN 2026Q2', url:'https://www.sec.gov/Archives/edgar/data/1018724/000101872426000026/amzn-20260630.htm'},
    cloudMSFT: {label:'Microsoft FY26 Q4 metrics', url:'https://www.microsoft.com/en-us/investor/earnings/fy-2026-q4/metrics'},
    cloudAMZN: {label:'Amazon Q2 2026 results', url:'https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-Second-Quarter-Results/default.aspx'},
    cloudGOOGL: {label:'Alphabet Q2 2026 exhibit', url:'https://www.sec.gov/Archives/edgar/data/1652044/000165204426000066/googexhibit991q22026.htm'},
    cloudORCL: {label:'Oracle FY26 Q4 results', url:'https://investor.oracle.com/investor-news/news-details/2026/Oracle-Announces-Record-Q4-and-FY-2026-Results-Driven-by-Cloud-Infrastructure--Cloud-Applications/default.aspx'},
    nvidiaCurrent: {label:'NVIDIA Q2 FY27 10-Q', url:'https://investor.nvidia.com/files/doc_financials/2027/NVDA-2027-Q2-10Q-Final-including-exhibits.pdf'},
    tsmcCurrent: {label:'TSMC IR · 2026 monthly revenue', url:'https://investor.tsmc.com/english/monthly-revenue/2026'},
    runpod: {label:'Runpod · GPU Models', url:'https://www.runpod.io/gpu-models'},
    vastApi: {label:'Vast.ai bundles API', url:'https://console.vast.ai/api/v0/bundles/'}
  };"""
s, n = re.subn(r"  const S = \{.*?\n  \};", new_s, s, count=1, flags=re.S)
if n != 1:
    raise SystemExit('Could not replace source registry')

old_arrays = """  const H5 = [S.microsoft,S.alphabet,S.amazon,S.meta,S.oracle];
  const CLOUD = [S.microsoft,S.amazon,S.alphabet,S.oracle];
  const MARKET = [S.yahooNDX,S.yahooSOX,S.yahooNVDA];
  const RATES = [S.fred10,S.fred30,S.fredReal10,S.fredHY,S.cboeVIX];
  const BACKTEST = [S.yahooNDX,S.yahooSOX,S.cboeVIX,S.fredBAA,S.tsmc];"""
new_arrays = """  const H5_LATEST = [S.yfMSFT,S.yfGOOGL,S.amznQ226SEC,S.yfMETA,S.yfORCL];
  const H5_HISTORY = [S.yfMSFT,S.yfGOOGL,S.yfAMZN,S.amznQ226SEC,S.yfMETA,S.yfORCL];
  const H4_HISTORY = [S.yfMSFT,S.yfGOOGL,S.yfAMZN,S.amznQ226SEC,S.yfORCL];
  const CLOUD = [S.cloudMSFT,S.cloudAMZN,S.cloudGOOGL,S.cloudORCL];
  const MARKET = [S.yahooNDX,S.yahooSOX,S.yahooNVDA];
  const MARKET_HEAT = [S.yahooNDX,S.yahooSOX,S.yahooNVDA,S.yahooQQQ,S.yahooRSP];
  const LIQUIDITY = [S.fredReal10,S.fredHY,S.cboeVIX];
  const RATES = [S.fred10,S.fred30,S.fredReal10,S.fredHY,S.cboeVIX];
  const BACKTEST = [S.yahooNDX,S.yahooSOX,S.yahooNVDA,S.yahooQQQ,S.yahooRSP,S.cboeVIX,S.fredBAA,S.fredReal10,S.tsmcCurrent];"""
if old_arrays not in s:
    raise SystemExit('Old source arrays not found')
s = s.replace(old_arrays, new_arrays, 1)

# Put precise upstream-input rules before the generic methodology rule.
anchor = "    // Derived / model outputs: link to the monitor's methodology and calibration page.\n"
precise = """    // Derived outputs with compact, auditable upstream lineages.
    if (contains(t,['investment–monetization gap','investment-monetization gap'])) return many([...H4_HISTORY,...CLOUD]);
    if (contains(t,['investment–cash flow gap','investment-cash flow gap'])) return many(H5_HISTORY);
    if (contains(t,['price–fundamental gap','price-fundamental gap'])) return many([...MARKET_HEAT,S.nvidiaCurrent,S.tsmcCurrent]);
    if (t.includes('liquidity stress')) return many(LIQUIDITY);
    if (t.includes('compute demand score')) return many([S.nvidiaCurrent,S.tsmcCurrent]);
    if (t.includes('nvidia demand quality')) return one(S.nvidiaCurrent);
    if (t.includes('market heat')) return many(MARKET_HEAT);
    if (t.includes('fundamental heat')) return many([S.nvidiaCurrent,S.tsmcCurrent]);
    if (t.includes('capital burden')) return many(H5_LATEST);
    if (t.includes('market trend breakdown')) return many(MARKET);
    if (contains(t,['cashflow deterioration','cash flow deterioration'])) return many(H5_HISTORY);
    if (t.includes('monetization deterioration')) return many(CLOUD);

"""
if precise not in s:
    s = s.replace(anchor, precise + anchor, 1)

# Brent: displayed price is 1m query1 API, chart history is daily yfinance/query2 API.
s = s.replace("if (t.includes('brent crude') || t === 'bz=f' || t.includes('brent bz=f')) return one(S.yahooBrent);",
              "if (t.includes('brent crude')) return many([S.yahooBrent1m,S.yahooBrentDaily]);\n    if (t === 'bz=f' || t.includes('brent bz=f')) return one(S.yahooBrent1m);", 1)

# Exact cloud source URLs from official_quarterly.csv.
s = s.replace("if (t.includes('azure')) return one(S.microsoft);", "if (t.includes('azure')) return one(S.cloudMSFT);", 1)
s = s.replace("if (t.includes('aws')) return one(S.amazon);", "if (t.includes('aws')) return one(S.cloudAMZN);", 1)
s = s.replace("if (t.includes('google cloud')) return one(S.alphabet);", "if (t.includes('google cloud')) return one(S.cloudGOOGL);", 1)
s = s.replace("if (t.includes('oci') || t.includes('oracle cloud infrastructure')) return one(S.oracle);", "if (t.includes('oci') || t.includes('oracle cloud infrastructure')) return one(S.cloudORCL);", 1)

# Exact current NVIDIA / TSMC source_url values.
s = s.replace("return one(S.nvidiaIR);", "return one(S.nvidiaCurrent);", 1)
s = s.replace("if (t.includes('tsmc')) return one(S.tsmc);", "if (t.includes('tsmc')) return one(S.tsmcCurrent);", 1)

# GPU is currently Runpod fallback; do not show Vast as if it were currently used.
s = s.replace("if (t.includes('gpu rental') || t.includes('gpu price')) return many([S.runpod,S.vast]);", "if (t.includes('gpu rental') || t.includes('gpu price')) return one(S.runpod);", 1)

# Company-specific H5 inputs currently come from Yahoo fundamentals except AMZN Q2 override.
s = s.replace("if (t.includes('microsoft')) return one(S.microsoft);", "if (t.includes('microsoft')) return one(S.yfMSFT);", 1)
s = s.replace("if (t.includes('alphabet')) return one(S.alphabet);", "if (t.includes('alphabet')) return one(S.yfGOOGL);", 1)
s = s.replace("if (t.includes('amazon')) return one(S.amazon);", "if (t.includes('amazon')) return one(S.amznQ226SEC);", 1)
s = s.replace("if (t.includes('meta')) return one(S.meta);", "if (t.includes('meta')) return one(S.yfMETA);", 1)
s = s.replace("if (t.includes('oracle')) return one(S.oracle);", "if (t.includes('oracle')) return one(S.yfORCL);", 1)

# H5 latest vs historical chart lineage.
s = s.replace("if (contains(t,['h5 ','h5 cash','h5 standardized','capex / revenue','capex/revenue','d&a / revenue','d&a/revenue','free cash flow','cash capex vs','hyperscaler investment'])) return many(H5);",
              "if (contains(t,['h5 cash capex vs','free cash flow'])) return many(H5_HISTORY);\n    if (contains(t,['h5 ','h5 cash','h5 standardized','capex / revenue','capex/revenue','d&a / revenue','d&a/revenue','hyperscaler investment'])) return many(H5_LATEST);", 1)

# Component rows should use the same source-lineage rules instead of blindly linking methodology.
old_component = """  function decorateComponentRows(){
    document.querySelectorAll('#bubbleTable td:first-child,#breakdownTable td:first-child').forEach(el=>{
      if(el.dataset.sourceLinked==='1') return;
      el.dataset.sourceLinked='1';
      const text=el.textContent.trim();
      el.textContent='';
      el.appendChild(makeAnchor(S.methodology,text));
    });
  }"""
new_component = """  function decorateComponentRows(){
    document.querySelectorAll('#bubbleTable td:first-child,#breakdownTable td:first-child').forEach(decorate);
  }"""
if old_component not in s:
    raise SystemExit('Component decorator anchor not found')
s = s.replace(old_component, new_component, 1)

# Validate that no old generic source keys remain in executable rules/arrays.
for bad in ['S.microsoft','S.alphabet','S.amazon','S.meta','S.oracle','S.nvidiaIR','S.tsmc','S.vast','S.yahooBrent)']:
    if bad in s:
        raise SystemExit(f'Old generic source mapping remains: {bad}')

p.write_text(s, encoding='utf-8')
print('Audited source links patched successfully.')
