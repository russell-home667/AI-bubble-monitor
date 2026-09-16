(() => {
  'use strict';

  const TIME_CHART_IDS = new Set([
    'brentChart','marketChart','liquidityChart','capexFcfChart',
    'tsmcChart','gpuChart','scoreHistoryChart','historyChart'
  ]);
  if (!window.echarts) return;

  const patched = new WeakSet();
  let nfciLoadStarted = false;
  let marketQuotePayload = null;
  let marketSummaryPayload = null;
  let marketQuoteLoadStarted = false;
  let marketQuotePoller = null;

  function formatBeijingTimestamp(value) {
    if (!value) return null;
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return null;
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit',
      hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23'
    }).formatToParts(d);
    const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
    return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second} BJT`;
  }

  function ensureCommodityQuoteLayout() {
    const row = document.querySelector('#brentMacroSection .brent-quote-row');
    if (!row) return null;
    let block = document.getElementById('goldQuoteMain');
    if (block) return block;

    if (!document.getElementById('gold-large-quote-style')) {
      const style = document.createElement('style');
      style.id = 'gold-large-quote-style';
      style.textContent = `
        #brentMacroSection .brent-desc{display:none;}
        #brentMacroSection .brent-quote-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:start;gap:72px;padding-top:24px;padding-bottom:8px;}
        #brentMacroSection .brent-quote-main,#brentMacroSection .gold-quote-main{min-width:0;max-width:520px;}
        #brentMacroSection .commodity-quote-label,#brentMacroSection .brent-quote-row>div:first-child::before{color:#6f8fa6;font-size:11px;font-weight:700;letter-spacing:.75px;margin-bottom:7px;text-transform:uppercase;}
        #brentMacroSection .brent-quote-row>div:first-child::before{content:'BRENT CRUDE';display:block;}
        #brentMacroSection .gold-price-line{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;}
        #brentMacroSection .gold-value{font-size:46px;line-height:1;font-weight:700;letter-spacing:.4px;color:#f0f8ff;}
        #brentMacroSection .gold-unit{color:#7895aa;font-size:13px;font-weight:600;}
        #brentMacroSection .gold-change{margin-top:8px;font-size:14px;font-weight:600;color:#8fa7b7;}
        #brentMacroSection .brent-time,#brentMacroSection .gold-time{margin-top:9px;color:#66859b;font-size:10px;line-height:1.45;}
        #brentMacroSection .brent-meta{display:none!important;}
        @media(max-width:900px){#brentMacroSection .brent-quote-row{gap:36px;}}
        @media(max-width:620px){#brentMacroSection .brent-quote-row{grid-template-columns:1fr;gap:24px;}#brentMacroSection .gold-value{font-size:39px;}}
      `;
      document.head.appendChild(style);
    }

    const brentMain = row.firstElementChild;
    if (brentMain) {
      brentMain.classList.add('brent-quote-main');
      if (!document.getElementById('brentQuoteTime')) {
        const time = document.createElement('div');
        time.id = 'brentQuoteTime';
        time.className = 'brent-time';
        time.textContent = 'Latest quote · —';
        brentMain.appendChild(time);
      }
    }

    block = document.createElement('div');
    block.id = 'goldQuoteMain';
    block.className = 'gold-quote-main';
    block.innerHTML = `
      <div class="commodity-quote-label">GOLD SPOT · XAU/USD</div>
      <div class="gold-price-line"><span class="gold-value" id="goldBigValue">—</span><span class="gold-unit">USD/oz · Gold</span></div>
      <div class="gold-change" id="goldBigChange">—</div>
      <div class="gold-time" id="goldBigDate">Latest quote · —</div>`;
    const meta = row.querySelector('.brent-meta');
    if (meta) row.insertBefore(block, meta); else row.appendChild(block);
    return block;
  }

  function syncCommodityQuotes() {
    const brent = typeof brentPayload !== 'undefined' ? brentPayload : null;
    const gold = typeof goldPayload !== 'undefined' ? goldPayload : null;
    ensureCommodityQuoteLayout();

    const brentFormatted = formatBeijingTimestamp(brent?.latest_quote?.timestamp);
    const brentTime = document.getElementById('brentQuoteTime');
    if (brentTime && brentFormatted) brentTime.textContent = `Latest quote · ${brentFormatted}`;
    const legacyDate = document.getElementById('brentDate');
    if (legacyDate && brentFormatted) legacyDate.textContent = brentFormatted;

    const quote = gold?.latest_quote || {};
    const rows = Array.isArray(gold?.data) ? gold.data : [];
    const last = rows.length ? rows[rows.length - 1] : null;
    const price = Number(quote.price ?? last?.value);
    const valueEl = document.getElementById('goldBigValue');
    if (valueEl && Number.isFinite(price)) valueEl.textContent = price.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
    const goldTime = formatBeijingTimestamp(quote.timestamp);
    const dateEl = document.getElementById('goldBigDate');
    if (dateEl && goldTime) dateEl.textContent = `Latest quote · ${goldTime}`;
    const changeEl = document.getElementById('goldBigChange');
    const base = Number(last?.value);
    if (changeEl && Number.isFinite(price) && Number.isFinite(base) && base !== 0) {
      const change = (price / base - 1) * 100;
      changeEl.textContent = `${change >= 0 ? '+' : ''}${change.toFixed(2)}% vs prior completed daily close`;
      changeEl.style.color = change > 0 ? 'var(--green)' : change < 0 ? 'var(--red)' : 'var(--muted)';
    }
  }

  function latestFiniteRow(rows, key) {
    if (!Array.isArray(rows)) return null;
    for (let i = rows.length - 1; i >= 0; i -= 1) {
      const value = Number(rows[i]?.[key]);
      if (Number.isFinite(value)) return { ...rows[i], __value:value };
    }
    return null;
  }

  function nfciReady() {
    try { return !!latestFiniteRow(state?.raw?.nfci, 'value'); }
    catch (_) { return false; }
  }

  function bindMarketRangeSync(card) {
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
        .market-card-enhanced{align-self:stretch!important;}
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
      syncLiquidityQuotes();
    } catch (e) {
      console.warn('Market latest quote load failed',e);
      syncMarketQuotes();
      syncLiquidityQuotes();
    }
  }

  function ensureMarketQuoteData() {
    if (marketQuoteLoadStarted) return;
    marketQuoteLoadStarted = true;
    loadMarketQuoteData();
    marketQuotePoller = setInterval(loadMarketQuoteData, 60000);
  }

  function ensureLiquidityQuoteLayout() {
    const chart = document.getElementById('liquidityChart');
    const card = chart?.closest('.chart-card');
    if (!card) return null;
    card.classList.add('liquidity-card-enhanced');

    const head = card.querySelector('.chart-head');
    const sub = head?.querySelector('.chart-sub');
    if (sub) sub.textContent = '10Y & 30Y Treasury / 10Y Real Yield / HY OAS / VIX / NFCI';

    let grid = document.getElementById('liquidityLatestGrid');
    if (grid) return grid;

    if (!document.getElementById('liquidity-latest-style')) {
      const style = document.createElement('style');
      style.id = 'liquidity-latest-style';
      style.textContent = `
        .liquidity-card-enhanced .chart-head{align-items:flex-start;gap:14px;}
        .liquidity-card-enhanced .chart-title{line-height:1.35;}
        .liquidity-card-enhanced .chart-sub{max-width:520px;line-height:1.4;}
        .liquidity-card-enhanced .range{flex-wrap:nowrap;flex-shrink:0;gap:4px;}
        .liquidity-card-enhanced .range button{min-width:38px;}
        .liquidity-card-enhanced .source-row{font-size:9px;line-height:1.45;margin-top:4px;}
        #liquidityLatestGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin:14px 16px 2px;border:1px solid rgba(89,151,190,.15);border-radius:12px;overflow:hidden;background:rgba(3,14,25,.22);}
        #liquidityLatestGrid .liq-quote{min-width:0;padding:13px 14px 12px;border-right:1px solid rgba(89,151,190,.12);border-bottom:1px solid rgba(89,151,190,.12);}
        #liquidityLatestGrid .liq-quote:nth-child(3n){border-right:0;}#liquidityLatestGrid .liq-quote:nth-child(n+4){border-bottom:0;}
        #liquidityLatestGrid .liq-label{color:#7893aa;font-size:10px;font-weight:700;letter-spacing:.55px;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
        #liquidityLatestGrid .liq-value-row{display:flex;align-items:baseline;gap:6px;margin-top:7px;min-width:0;}
        #liquidityLatestGrid .liq-value{color:#f0f8ff;font-size:31px;line-height:1;font-weight:720;letter-spacing:.2px;}
        #liquidityLatestGrid .liq-unit{color:#718aa1;font-size:10px;font-weight:600;}
        #liquidityLatestGrid .liq-date{margin-top:7px;color:#5f7b92;font-size:9px;line-height:1.35;}
        @media(max-width:980px){.liquidity-card-enhanced .range{flex-wrap:wrap;}#liquidityLatestGrid{grid-template-columns:repeat(2,minmax(0,1fr));}#liquidityLatestGrid .liq-quote{border-right:1px solid rgba(89,151,190,.12);border-bottom:1px solid rgba(89,151,190,.12);}#liquidityLatestGrid .liq-quote:nth-child(2n){border-right:0;}#liquidityLatestGrid .liq-quote:nth-child(n+5){border-bottom:0;}}
        @media(max-width:620px){#liquidityLatestGrid{grid-template-columns:1fr;}#liquidityLatestGrid .liq-quote{border-right:0!important;border-bottom:1px solid rgba(89,151,190,.12)!important;}#liquidityLatestGrid .liq-quote:last-child{border-bottom:0!important;}#liquidityLatestGrid .liq-value{font-size:28px;}}
      `;
      document.head.appendChild(style);
    }

    grid = document.createElement('div');
    grid.id = 'liquidityLatestGrid';
    grid.innerHTML = [
      ['liq10y','US 10Y Treasury','%'],['liq30y','US 30Y Treasury','%'],
      ['liqReal10','10Y Real Yield','%'],['liqHy','HY OAS','%'],
      ['liqVix','VIX','index'],['liqNfci','NFCI','index']
    ].map(([id,label,unit]) => `<div class="liq-quote"><div class="liq-label">${label}</div><div class="liq-value-row"><span class="liq-value" id="${id}Value">—</span><span class="liq-unit">${unit}</span></div><div class="liq-date" id="${id}Date">Latest · —</div></div>`).join('');
    if (head?.nextSibling) card.insertBefore(grid, head.nextSibling); else if (head) head.after(grid); else card.insertBefore(grid, chart);
    return grid;
  }

  // LIVE_LIQUIDITY_TILES_V2
  function summaryIntradayQuote(key) {
    const x = marketSummaryPayload?.indicators?.[key];
    if (!x?.live_quote_timestamp || !Number.isFinite(Number(x?.value))) return null;
    return {
      price:Number(x.value),
      timestamp:x.live_quote_timestamp,
      source:x.live_quote_source || 'Yahoo Finance',
      quote_status:x.live_quote_status || null
    };
  }

  function setLiquidityQuote(id, payload, decimals, mode='daily') {
    const valueEl = document.getElementById(`${id}Value`);
    const dateEl = document.getElementById(`${id}Date`);
    if (!payload) {
      if (valueEl) valueEl.textContent = '—';
      if (dateEl) dateEl.textContent = 'Latest: --';
      return;
    }

    const rawValue = mode === 'intraday'
      ? Number(payload?.price ?? payload?.value)
      : Number(payload?.value ?? payload?.__value);
    if (valueEl) valueEl.textContent = Number.isFinite(rawValue) ? rawValue.toFixed(decimals) : '—';

    if (!dateEl) return;
    if (mode === 'intraday') {
      const stamp = formatBeijingTimestamp(payload?.timestamp || payload?.live_quote_timestamp);
      const source = payload?.source || payload?.live_quote_source || 'Yahoo Finance';
      const status = payload?.quote_status || payload?.live_quote_status || '';
      dateEl.textContent = `Intraday | ${stamp || '--'} | ${source}${status ? ' | '+status : ''}`;
    } else {
      const obs = payload?.observation_date || payload?.date || '—';
      dateEl.textContent = `Latest official | ${obs}`;
    }
  }

  function syncLiquidityQuotes() {
    ensureLiquidityQuoteLayout();
    if (typeof state === 'undefined' || !state?.raw) return;

    const live = marketQuotePayload?.quotes || {};
    const summary = marketSummaryPayload?.indicators || {};

    const q10 = live.dgs10 || summaryIntradayQuote('dgs10');
    const q30 = live.dgs30 || summaryIntradayQuote('dgs30');
    const qVix = live.vix || summaryIntradayQuote('vix');

    setLiquidityQuote('liq10y', q10 || latestFiniteRow(state.raw.dgs10,'value'), q10 ? 3 : 2, q10 ? 'intraday' : 'daily');
    setLiquidityQuote('liq30y', q30 || latestFiniteRow(state.raw.dgs30,'value'), q30 ? 3 : 2, q30 ? 'intraday' : 'daily');
    setLiquidityQuote('liqReal10', summary.dfii10 || latestFiniteRow(state.raw.dfii10,'value'), 2, 'daily');
    setLiquidityQuote('liqHy', summary.hy_oas || latestFiniteRow(state.raw.hy,'value'), 2, 'daily');
    setLiquidityQuote('liqVix', qVix || latestFiniteRow(state.raw.vix,'close'), 2, qVix ? 'intraday' : 'daily');
    setLiquidityQuote('liqNfci', latestFiniteRow(state.raw.nfci,'value'), 3, 'daily');
  }

  function syncLiquiditySources() {
    const card = document.getElementById('liquidityChart')?.closest('.chart-card');
    const row = card?.querySelector('.chart-title .source-row');
    if (!row || row.querySelector('[data-nfci-source="1"]')) return;
    row.appendChild(document.createTextNode(' · '));
    const a = document.createElement('a');
    a.className='source-link'; a.href='https://fred.stlouisfed.org/series/NFCI'; a.target='_blank'; a.rel='noopener noreferrer';
    a.dataset.nfciSource='1'; a.setAttribute('aria-label','Chicago Fed / FRED · NFCI source');
    a.appendChild(document.createTextNode('Chicago Fed / FRED · NFCI '));
    const arrow=document.createElement('span'); arrow.className='source-arrow'; arrow.textContent='↗'; a.appendChild(arrow); row.appendChild(a);
  }

  function aviationDataZoom(chartId) {
    return [
      {type:'inside',xAxisIndex:0,filterMode:'filter',zoomOnMouseWheel:true,moveOnMouseMove:true,moveOnMouseWheel:false},
      {type:'slider',xAxisIndex:0,height:18,bottom:9,left:50,right:24,realtime:true,borderColor:'rgba(70,193,255,.10)',backgroundColor:'rgba(4,12,20,.30)',fillerColor:'rgba(70,193,255,.13)',handleStyle:{color:'#0d1828',borderColor:'#46c1ff',borderWidth:1.4},moveHandleStyle:{color:'rgba(142,172,201,.78)'},textStyle:{color:'#647f92'},showDetail:false,showDataShadow:chartId!=='liquidityChart'&&chartId!=='marketChart',brushSelect:true,zoomLock:false}
    ];
  }

  function tuneMarketOption(option) {
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

  function tuneLiquidityOption(option) {
    if (!option || typeof option !== 'object') return option;
    const out = { ...option };
    const ready = nfciReady();
    const sourceGrid = Array.isArray(out.grid) ? (out.grid[0] || {}) : (out.grid || {});
    out.grid = { ...sourceGrid, left:72, right:ready?118:70, top:Math.max(Number(sourceGrid.top)||0,54), bottom:57, containLabel:false };
    out.legend = { ...(out.legend||{}), top:8,left:'center',itemGap:12,itemWidth:18,itemHeight:8,textStyle:{...((out.legend||{}).textStyle||{}),color:'#8ea2bc',fontSize:10} };

    const axes = Array.isArray(out.yAxis) ? out.yAxis.map(x => ({...x})) : [{...(out.yAxis||{})}];
    const base = axes[0] || {type:'value',scale:true};
    axes[0] = {...base,name:'Yield / OAS (%)',position:'left',offset:0,nameGap:14,scale:true};
    axes[1] = {...(axes[1]||base),name:'VIX',position:'right',offset:0,nameGap:14,scale:true,splitLine:{show:false}};
    axes[2] = {...base,name:'NFCI',show:ready,position:'right',offset:54,nameGap:14,scale:true,splitLine:{show:false},axisLine:{show:ready,lineStyle:{color:'#58c6e8'}},axisLabel:{...(base.axisLabel||{}),show:ready,color:'#74a9c2',formatter:v=>Number(v).toFixed(2)},nameTextStyle:{color:'#74a9c2'}};
    out.yAxis = axes;

    const styles = {
      'US 10Y Treasury':{color:'#6f83ff',width:2},'US 30Y Treasury':{color:'#9bd66f',width:2},
      '10Y Real Yield':{color:'#f5c75b',width:2},'HY OAS':{color:'#ff746d',width:2},
      'VIX':{color:'#b78cff',width:2},'NFCI':{color:'#58c6e8',width:1.9,type:'dashed'}
    };
    if (Array.isArray(out.series)) {
      out.series = out.series.map(series => {
        const s = styles[series?.name];
        const next = s ? {...series,lineStyle:{...(series.lineStyle||{}),color:s.color,width:s.width,...(s.type?{type:s.type}:{})},itemStyle:{...(series.itemStyle||{}),color:s.color}} : {...series};
        if (series?.name === 'NFCI') { next.yAxisIndex=2; next.connectNulls=true; next.showSymbol=false; }
        return next;
      });
    }
    return out;
  }

  function withAviationZoom(option, chartId) {
    if (!option || typeof option !== 'object') return option;
    let out = {...option};
    if (chartId === 'marketChart') out = tuneMarketOption(out);
    if (chartId === 'liquidityChart') out = tuneLiquidityOption(out);
    if (Array.isArray(out.grid)) out.grid = out.grid.map((g,i)=>i===0?{...g,bottom:Math.max(Number(g?.bottom)||0,57)}:g);
    else out.grid = {...(out.grid||{}),bottom:Math.max(Number(out.grid?.bottom)||0,57)};
    out.dataZoom = aviationDataZoom(chartId);
    return out;
  }

  function patchChart(chart, chartId) {
    if (!chart || patched.has(chart)) return;
    const originalSetOption = chart.setOption.bind(chart);
    chart.setOption = function(option,...args){ return originalSetOption(withAviationZoom(option,chartId),...args); };
    patched.add(chart);
    let initial = {grid:{bottom:57}};
    if (chartId === 'marketChart') initial = tuneMarketOption(initial);
    if (chartId === 'liquidityChart') initial = tuneLiquidityOption(initial);
    originalSetOption({...initial,dataZoom:aviationDataZoom(chartId)},false);
  }

  function refreshLiquidityAfterNfci() {
    syncLiquidityQuotes();
    try { if (typeof renderLiquidityChart === 'function') renderLiquidityChart(); } catch (e) { console.warn('Liquidity rerender after NFCI failed',e); }
    const dom = document.getElementById('liquidityChart');
    const chart = dom ? echarts.getInstanceByDom(dom) : null;
    if (chart) chart.resize();
  }

  async function ensureNfciData() {
    if (nfciLoadStarted) return;
    nfciLoadStarted = true;
    await new Promise(resolve => setTimeout(resolve,0));
    try {
      if (nfciReady()) { refreshLiquidityAfterNfci(); return; }
      const response = await fetch('data/ai_bubble/market_liquidity/nfci.csv',{cache:'no-cache'});
      if (!response.ok) throw new Error(`NFCI HTTP ${response.status}`);
      const text = await response.text();
      if (!window.Papa) throw new Error('PapaParse unavailable');
      const rows = Papa.parse(text,{header:true,dynamicTyping:true,skipEmptyLines:true}).data.filter(r=>r?.date && Number.isFinite(Number(r.value)));
      if (!rows.length) throw new Error('NFCI dataset empty');
      let waitCount = 0;
      while ((typeof state === 'undefined' || !state?.raw) && waitCount < 40) {
        await new Promise(resolve => setTimeout(resolve,50));
        waitCount += 1;
      }
      if (typeof state !== 'undefined' && state?.raw) state.raw.nfci = rows;
      refreshLiquidityAfterNfci();
    } catch (e) {
      console.warn('Deterministic NFCI load failed',e);
      const valueEl = document.getElementById('liqNfciValue');
      const dateEl = document.getElementById('liqNfciDate');
      if (valueEl) valueEl.textContent='—';
      if (dateEl) dateEl.textContent='Load unavailable';
    }
  }

  function equalizeMarketLiquidityCards() {
    const left = document.getElementById('marketChart')?.closest('.chart-card');
    const right = document.getElementById('liquidityChart')?.closest('.chart-card');
    if (!left || !right || left.parentElement !== right.parentElement) return;
    const row = left.parentElement;
    row.style.alignItems = 'stretch';
    if (window.innerWidth <= 760) {
      left.style.height = '';
      right.style.height = '';
      return;
    }
    left.style.height = 'auto';
    right.style.height = 'auto';
    const target = Math.ceil(Math.max(
      left.getBoundingClientRect().height,
      right.getBoundingClientRect().height
    ));
    if (target > 0) {
      left.style.height = `${target}px`;
      right.style.height = `${target}px`;
    }
  }

  function scan() {
    TIME_CHART_IDS.forEach(id => {
      const dom=document.getElementById(id); if (!dom) return;
      const chart=echarts.getInstanceByDom(dom); if (chart) patchChart(chart,id);
    });
    syncCommodityQuotes();
    syncMarketQuotes();
    syncLiquidityQuotes();
    syncLiquiditySources();
    requestAnimationFrame(equalizeMarketLiquidityCards);
  }

  window.addEventListener('resize', () => requestAnimationFrame(equalizeMarketLiquidityCards));

  scan();
  ensureNfciData();
  ensureMarketQuoteData();

  let attempts=0;
  const timer=setInterval(()=>{ scan(); attempts+=1; if(attempts>=40) clearInterval(timer); },500);
})();