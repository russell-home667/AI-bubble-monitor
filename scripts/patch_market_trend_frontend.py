#!/usr/bin/env python3
from pathlib import Path

path = Path('assets/chart-time-slider.js')
text = path.read_text(encoding='utf-8')

old_vars = "  const patched = new WeakSet();\n  let nfciLoadStarted = false;"
new_vars = """  const patched = new WeakSet();
  let nfciLoadStarted = false;
  let marketQuotePayload = null;
  let marketSummaryPayload = null;
  let marketQuoteLoadStarted = false;
  let marketQuotePoller = null;"""
if old_vars not in text:
    raise SystemExit('market patch: variable anchor not found')
text = text.replace(old_vars, new_vars, 1)

start = text.find("  function ensureMarketQuoteLayout() {")
end = text.find("  function ensureLiquidityQuoteLayout() {", start)
if start < 0 or end < 0:
    raise SystemExit('market patch: market quote block anchors not found')

market_block = r'''  function bindMarketRangeSync(card) {
    const range = card?.querySelector('.range[data-chart="marketChart"]');
    if (!range || range.dataset.marketQuoteBound === '1') return;
    range.dataset.marketQuoteBound = '1';
    range.addEventListener('click', () => setTimeout(syncMarketQuotes, 0));
  }

  function ensureMarketQuoteLayout() {
    const chart = document.getElementById('marketChart');
    const card = chart?.closest('.chart-card');
    if (!card) return null;
    card.classList.add('market-card-enhanced');

    const head = card.querySelector('.chart-head');
    const sub = head?.querySelector('.chart-sub');
    if (sub) sub.textContent = 'NDX / SOX / NVDA · normalized to 100 at selected-range start';

    let grid = document.getElementById('marketLatestGrid');
    if (grid) {
      bindMarketRangeSync(card);
      return grid;
    }

    if (!document.getElementById('market-latest-style')) {
      const style = document.createElement('style');
      style.id = 'market-latest-style';
      style.textContent = `
        .market-card-enhanced{align-self:start!important;}
        .market-card-enhanced .chart-head{align-items:flex-start;gap:14px;}
        .market-card-enhanced .chart-title{line-height:1.35;}
        .market-card-enhanced .chart-sub{max-width:560px;line-height:1.4;}
        .market-card-enhanced .range{flex-wrap:nowrap;flex-shrink:0;gap:4px;}
        .market-card-enhanced .range button{min-width:38px;}
        .market-card-enhanced .source-row{font-size:9px;line-height:1.45;margin-top:4px;}
        .market-card-enhanced #marketChart{height:360px!important;}
        #marketLatestGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin:12px 16px 4px;border:1px solid rgba(89,151,190,.15);border-radius:12px;overflow:hidden;background:rgba(3,14,25,.22);}
        #marketLatestGrid .market-quote{min-width:0;padding:13px 16px 11px;border-right:1px solid rgba(89,151,190,.12);}
        #marketLatestGrid .market-quote:last-child{border-right:0;}
        #marketLatestGrid .market-label{color:#7893aa;font-size:10px;font-weight:700;letter-spacing:.55px;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
        #marketLatestGrid .market-value-row{display:flex;align-items:baseline;gap:7px;margin-top:7px;min-width:0;}
        #marketLatestGrid .market-value{color:#f0f8ff;font-size:34px;line-height:1;font-weight:720;letter-spacing:.2px;}
        #marketLatestGrid .market-unit{color:#718aa1;font-size:10px;font-weight:600;}
        #marketLatestGrid .market-change{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-top:8px;font-size:10px;font-weight:650;}
        #marketLatestGrid .market-range-change{color:#86a0b6;font-weight:600;}
        #marketLatestGrid .market-date{margin-top:6px;color:#5f7b92;font-size:9px;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
        @media(max-width:980px){.market-card-enhanced .range{flex-wrap:wrap;}#marketLatestGrid{grid-template-columns:1fr;}#marketLatestGrid .market-quote{border-right:0;border-bottom:1px solid rgba(89,151,190,.12);}#marketLatestGrid .market-quote:last-child{border-bottom:0;}}
        @media(max-width:620px){.market-card-enhanced #marketChart{height:320px!important;}#marketLatestGrid .market-value{font-size:29px;}}
      `;
      document.head.appendChild(style);
    }

    grid = document.createElement('div');
    grid.id = 'marketLatestGrid';
    grid.innerHTML = [
      ['marketNdx','NASDAQ-100','index'],
      ['marketSox','PHLX Semiconductor','index'],
      ['marketNvda','NVIDIA','USD']
    ].map(([id,label,unit]) => `<div class="market-quote"><div class="market-label">${label}</div><div class="market-value-row"><span class="market-value" id="${id}Value">—</span><span class="market-unit">${unit}</span></div><div class="market-change" id="${id}Change"><span>—</span></div><div class="market-date" id="${id}Date">Latest quote · loading…</div></div>`).join('');
    if (head?.nextSibling) card.insertBefore(grid, head.nextSibling); else if (head) head.after(grid); else card.insertBefore(grid, chart);
    bindMarketRangeSync(card);
    return grid;
  }

  function selectedMarketReturn(key, price) {
    try {
      if (!Number.isFinite(Number(price)) || typeof state === 'undefined' || !state?.raw) return null;
      const rows = Array.isArray(state.raw[key]) ? state.raw[key] : [];
      if (!rows.length) return null;
      const range = state.ranges?.marketChart || '1Y';
      let sliced = rows;
      if (typeof cutoffRows === 'function') sliced = cutoffRows(rows, 'date', range);
      const first = sliced.find(row => Number.isFinite(Number(row?.close)));
      const base = Number(first?.close);
      if (!Number.isFinite(base) || base === 0) return null;
      return {range, value:(Number(price) / base - 1) * 100};
    } catch (_) {
      return null;
    }
  }

  function setMarketQuote(id, key, live, fallback, decimals=2) {
    const price = Number(live?.price ?? fallback?.value);
    const change = Number(live?.change_1d_pct ?? fallback?.change_1d_pct);
    const valueEl = document.getElementById(`${id}Value`);
    const changeEl = document.getElementById(`${id}Change`);
    const dateEl = document.getElementById(`${id}Date`);

    if (valueEl && Number.isFinite(price)) {
      valueEl.textContent = price.toLocaleString(undefined,{minimumFractionDigits:decimals,maximumFractionDigits:decimals});
    }

    if (changeEl) {
      const oneDay = Number.isFinite(change)
        ? `<span style="color:${change > 0 ? 'var(--green)' : change < 0 ? 'var(--red)' : 'var(--muted)'}">1D ${change >= 0 ? '+' : ''}${change.toFixed(2)}%</span>`
        : '<span>1D —</span>';
      const selected = selectedMarketReturn(key, price);
      const rangeText = selected && Number.isFinite(selected.value)
        ? `<span class="market-range-change">${selected.range} ${selected.value >= 0 ? '+' : ''}${selected.value.toFixed(1)}%</span>`
        : '<span class="market-range-change">Range —</span>';
      changeEl.innerHTML = oneDay + rangeText;
    }

    if (dateEl) {
      const quoteTime = formatBeijingTimestamp(live?.timestamp);
      const obsDate = live?.observation_date || fallback?.observation_date;
      if (quoteTime) dateEl.textContent = `Latest available · ${quoteTime} · Yahoo Finance · 5m polling`;
      else if (obsDate) dateEl.textContent = `Last completed session · ${obsDate} · Yahoo Finance`;
      else dateEl.textContent = 'Latest quote · unavailable';
    }
  }

  function syncMarketQuotes() {
    ensureMarketQuoteLayout();
    const live = marketQuotePayload?.quotes || {};
    const fallback = marketSummaryPayload?.indicators || {};
    setMarketQuote('marketNdx', 'ndx', live.ndx, fallback.ndx, 2);
    setMarketQuote('marketSox', 'sox', live.sox, fallback.sox, 2);
    setMarketQuote('marketNvda', 'nvda', live.nvda, fallback.nvda, 2);
  }

  async function loadMarketQuoteData() {
    try {
      const stamp = Date.now();
      const [quoteResponse, summaryResponse] = await Promise.all([
        fetch(`data/ai_bubble/market_liquidity/market_quotes.json?v=${stamp}`,{cache:'no-store'}),
        fetch(`data/ai_bubble/market_liquidity/latest.json?v=${stamp}`,{cache:'no-store'})
      ]);
      if (quoteResponse.ok) marketQuotePayload = await quoteResponse.json();
      if (summaryResponse.ok) marketSummaryPayload = await summaryResponse.json();
      syncMarketQuotes();
    } catch (e) {
      console.warn('Market latest quote load failed',e);
      syncMarketQuotes();
    }
  }

  function ensureMarketQuoteData() {
    if (marketQuoteLoadStarted) return;
    marketQuoteLoadStarted = true;
    loadMarketQuoteData();
    marketQuotePoller = setInterval(loadMarketQuoteData, 60000);
  }

'''
text = text[:start] + market_block + text[end:]

old_shadow = "showDetail:false,showDataShadow:chartId!=='liquidityChart',brushSelect:true,zoomLock:false"
new_shadow = "showDetail:false,showDataShadow:chartId!=='liquidityChart'&&chartId!=='marketChart',brushSelect:true,zoomLock:false"
if old_shadow not in text:
    raise SystemExit('market patch: dataZoom anchor not found')
text = text.replace(old_shadow, new_shadow, 1)

start = text.find("  function tuneMarketOption(option) {")
end = text.find("  function tuneLiquidityOption(option) {", start)
if start < 0 or end < 0:
    raise SystemExit('market patch: tuneMarketOption anchors not found')

tune_block = r'''  function tuneMarketOption(option) {
    if (!option || typeof option !== 'object') return option;
    const out = {...option};
    const sourceGrid = Array.isArray(out.grid) ? (out.grid[0] || {}) : (out.grid || {});
    out.grid = {...sourceGrid,left:64,right:24,top:60,bottom:57,containLabel:true};
    out.legend = {...(out.legend||{}),top:10,left:'center',itemGap:18,itemWidth:20,itemHeight:9,textStyle:{...((out.legend||{}).textStyle||{}),color:'#8ea2bc',fontSize:11}};
    const axis = Array.isArray(out.yAxis) ? {...(out.yAxis[0]||{})} : {...(out.yAxis||{})};
    const dynamicMin = v => {
      const span = Math.max(Number(v.max)-Number(v.min),1);
      const pad = Math.max(span*.045,3);
      return Math.floor((Number(v.min)-pad)/10)*10;
    };
    const dynamicMax = v => {
      const span = Math.max(Number(v.max)-Number(v.min),1);
      const pad = Math.max(span*.045,3);
      return Math.ceil((Number(v.max)+pad)/10)*10;
    };
    out.yAxis = {...axis,name:'Normalized',nameGap:10,scale:true,min:dynamicMin,max:dynamicMax,splitNumber:5,axisLabel:{...(axis.axisLabel||{}),color:'#8296b0'},nameTextStyle:{...((axis.nameTextStyle)||{}),color:'#8296b0',fontSize:10}};
    const styles = {
      'NDX':{color:'#7187ff',width:2.2},
      'SOX':{color:'#96d56c',width:2.2},
      'NVDA':{color:'#f4c75a',width:2.3}
    };
    if (Array.isArray(out.series)) {
      out.series = out.series.map(series => {
        const s=styles[series?.name];
        return s ? {...series,lineStyle:{...(series.lineStyle||{}),color:s.color,width:s.width},itemStyle:{...(series.itemStyle||{}),color:s.color},showSymbol:false,smooth:false} : series;
      });
    }
    return out;
  }

'''
text = text[:start] + tune_block + text[end:]

old_init = "  scan();\n  ensureNfciData();"
new_init = "  scan();\n  ensureNfciData();\n  ensureMarketQuoteData();"
if old_init not in text:
    raise SystemExit('market patch: init anchor not found')
text = text.replace(old_init, new_init, 1)

path.write_text(text, encoding='utf-8')
print('Patched Market Trend frontend successfully')
