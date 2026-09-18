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
    const base = Number(quote.previous_close);
    if (changeEl && Number.isFinite(price) && Number.isFinite(base) && base !== 0) {
      const change = (price / base - 1) * 100;
      changeEl.textContent = `${change >= 0 ? '+' : ''}${change.toFixed(2)}% vs prior completed daily close`;
      changeEl.style.color = change > 0 ? 'var(--green)' : change < 0 ? 'var(--red)' : 'var(--muted)';
    } else if (changeEl) {
      changeEl.textContent = '— vs prior completed daily close';
      changeEl.style.color = 'var(--muted)';
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
    if (sub) sub.textContent = 'NDX / SOX / NVDA / GOOGL / MSFT / AMZN · normalized to 100 at selected-range start';

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
        .market-card-enhanced .chart-head{align-items:flex-start;gap:18px;padding:20px 22px 0;min-height:118px;box-sizing:border-box;}
        .market-card-enhanced .chart-title{line-height:1.35;}
        .market-card-enhanced .chart-sub{max-width:620px;line-height:1.55;margin-top:8px;}
        .market-card-enhanced .range{flex-wrap:nowrap;flex-shrink:0;gap:7px;}
        .market-card-enhanced .range button{min-width:44px;padding:7px 10px;}
        .market-card-enhanced .source-row{font-size:9px;line-height:1.6;margin-top:7px;}
        .market-card-enhanced #marketChart{height:430px!important;margin-top:10px;}
        #marketLatestGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin:20px 22px 16px;border:1px solid rgba(89,151,190,.15);border-radius:14px;overflow:hidden;background:rgba(3,14,25,.22);}
        #marketLatestGrid .market-quote{min-width:0;min-height:150px;box-sizing:border-box;padding:20px 22px 18px;border-right:1px solid rgba(89,151,190,.12);border-bottom:1px solid rgba(89,151,190,.12);display:flex;flex-direction:column;}
        #marketLatestGrid .market-quote:nth-child(3n){border-right:0;}
        #marketLatestGrid .market-quote:nth-last-child(-n+3){border-bottom:0;}
        #marketLatestGrid .market-label{color:#7893aa;font-size:10px;font-weight:700;letter-spacing:.55px;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
        #marketLatestGrid .market-value-row{display:flex;align-items:baseline;gap:10px;margin-top:11px;min-width:0;}
        #marketLatestGrid .market-value{color:#f0f8ff;font-size:34px;line-height:1;font-weight:720;letter-spacing:.2px;}
        #marketLatestGrid .market-unit{color:#718aa1;font-size:10px;font-weight:600;}
        #marketLatestGrid .market-change{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-top:11px;font-size:10px;font-weight:650;}
        #marketLatestGrid .market-range-change{color:#86a0b6;font-weight:600;}
        #marketLatestGrid .market-date{margin-top:auto;padding-top:10px;color:#5f7b92;font-size:9px;line-height:1.5;white-space:normal;overflow:visible;text-overflow:clip;min-height:27px;}
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
      ['marketNvda','NVIDIA','USD'],
      ['marketGoogl','Alphabet','USD'],
      ['marketMsft','Microsoft','USD'],
      ['marketAmzn','Amazon','USD']
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
      if (quoteTime) dateEl.textContent = `Latest available · ${quoteTime} · Yahoo Finance · 10m polling`;
      else if (obsDate) dateEl.textContent = `Last completed session · ${obsDate} · Yahoo Finance`;
      else dateEl.textContent = 'Latest quote · unavailable';
    }
  }

  function syncMarketQuotes() {
    ensureMarketQuoteLayout();
    const live = marketQuotePayload?.quotes || {};
    const fallback = marketSummaryPayload?.indicators || {};
    if (typeof renderMarketCards === 'function' && marketSummaryPayload?.indicators) {
      try { renderMarketCards(marketSummaryPayload, live); }
      catch (e) { console.warn('Market small cards refresh failed', e); }
    }
    setMarketQuote('marketNdx', 'ndx', live.ndx, fallback.ndx, 2);
    setMarketQuote('marketSox', 'sox', live.sox, fallback.sox, 2);
    setMarketQuote('marketNvda', 'nvda', live.nvda, fallback.nvda, 2);
    setMarketQuote('marketGoogl', 'googl', live.googl, fallback.googl, 2);
    setMarketQuote('marketMsft', 'msft', live.msft, fallback.msft, 2);
    setMarketQuote('marketAmzn', 'amzn', live.amzn, fallback.amzn, 2);
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
    if (sub) sub.textContent = '10Y & 30Y Treasury / VIX / 10Y Real Yield / HY OAS / NFCI';

    let grid = document.getElementById('liquidityLatestGrid');
    if (grid) return grid;

    if (!document.getElementById('liquidity-latest-style')) {
      const style = document.createElement('style');
      style.id = 'liquidity-latest-style';
      style.textContent = `
        .liquidity-card-enhanced{align-self:stretch!important;}
        .liquidity-card-enhanced .chart-head{align-items:flex-start;gap:18px;padding:20px 22px 0;min-height:118px;box-sizing:border-box;}
        .liquidity-card-enhanced .chart-title{line-height:1.35;}
        .liquidity-card-enhanced .chart-sub{max-width:620px;line-height:1.55;margin-top:8px;}
        .liquidity-card-enhanced .range{flex-wrap:nowrap;flex-shrink:0;gap:7px;}
        .liquidity-card-enhanced .range button{min-width:44px;padding:7px 10px;}
        .liquidity-card-enhanced .source-row{font-size:9px;line-height:1.6;margin-top:7px;}
        .liquidity-card-enhanced #liquidityChart{height:430px!important;margin-top:10px;}
        #liquidityLatestGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin:20px 22px 16px;border:1px solid rgba(89,151,190,.15);border-radius:14px;overflow:hidden;background:rgba(3,14,25,.22);}
        #liquidityLatestGrid .liq-quote{min-width:0;min-height:150px;box-sizing:border-box;padding:20px 22px 18px;border-right:1px solid rgba(89,151,190,.12);border-bottom:1px solid rgba(89,151,190,.12);display:flex;flex-direction:column;}
        #liquidityLatestGrid .liq-quote:nth-child(3n){border-right:0;}
        #liquidityLatestGrid .liq-quote:nth-last-child(-n+3){border-bottom:0;}
        #liquidityLatestGrid .liq-label{color:#7893aa;font-size:10px;font-weight:700;letter-spacing:.55px;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
        #liquidityLatestGrid .liq-value-row{display:flex;align-items:baseline;gap:10px;margin-top:11px;min-width:0;}
        #liquidityLatestGrid .liq-value{color:#f0f8ff;font-size:34px;line-height:1;font-weight:720;letter-spacing:.2px;}
        #liquidityLatestGrid .liq-unit{color:#718aa1;font-size:10px;font-weight:600;}
        #liquidityLatestGrid .liq-change-stack{display:flex;flex-direction:row;gap:14px;align-items:center;flex-wrap:wrap;margin-top:11px;font-size:10px;line-height:1.2;font-weight:700;white-space:nowrap;}
        #liquidityLatestGrid .liq-change-item{color:#86a0b6;}
        #liquidityLatestGrid .liq-date{margin-top:auto;padding-top:10px;color:#5f7b92;font-size:9px;line-height:1.5;min-height:14px;}
        #liquidityLatestGrid .liq-source{margin-top:3px;color:#4f6b81;font-size:8.5px;line-height:1.35;min-height:12px;}
        @media(max-width:980px){.liquidity-card-enhanced .range{flex-wrap:wrap;}#liquidityLatestGrid{grid-template-columns:repeat(2,minmax(0,1fr));}#liquidityLatestGrid .liq-quote{border-right:1px solid rgba(89,151,190,.12);border-bottom:1px solid rgba(89,151,190,.12);}#liquidityLatestGrid .liq-quote:nth-child(2n){border-right:0;}#liquidityLatestGrid .liq-quote:nth-child(n+5){border-bottom:0;}}
        @media(max-width:620px){.liquidity-card-enhanced #liquidityChart{height:320px!important;}#liquidityLatestGrid{grid-template-columns:1fr;}#liquidityLatestGrid .liq-quote{border-right:0!important;border-bottom:1px solid rgba(89,151,190,.12)!important;}#liquidityLatestGrid .liq-quote:last-child{border-bottom:0!important;}#liquidityLatestGrid .liq-value{font-size:29px;}}
      `;
      document.head.appendChild(style);
    }

    grid = document.createElement('div');
    grid.id = 'liquidityLatestGrid';
    grid.innerHTML = [
      ['liq10y','US 10Y Treasury','%'],['liq30y','US 30Y Treasury','%'],
      ['liqVix','VIX','index'],['liqReal10','10Y Real Yield','%'],
      ['liqHy','HY OAS','%'],['liqNfci','NFCI','index']
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

  function compactLiquiditySource(source, mode='daily') {
    const s = String(source || '').trim();
    if (/investing/i.test(s)) return 'Investing.com';
    if (/yahoo/i.test(s)) return 'Yahoo Finance';
    if (/federal reserve|fred|h\.15/i.test(s)) return 'Federal Reserve / FRED';
    if (s) return s.replace(/\s+(US\s+)?(10Y|30Y).*$/i,'').trim() || s;
    return mode === 'intraday' ? 'Market data feed' : 'Federal Reserve / FRED';
  }

  function ensureLiquiditySourceLine(id) {
    let el = document.getElementById(`${id}Source`);
    if (el) return el;
    const dateEl = document.getElementById(`${id}Date`);
    const quote = dateEl?.closest('.liq-quote');
    if (!quote) return null;
    el = document.createElement('div');
    el.id = `${id}Source`;
    el.className = 'liq-source';
    dateEl.after(el);
    return el;
  }

  function setLiquidityQuote(id, payload, decimals, mode='daily') {
    const valueEl = document.getElementById(`${id}Value`);
    const dateEl = document.getElementById(`${id}Date`);
    const treasury = id === 'liq10y' || id === 'liq30y';
    const sourceEl = treasury ? ensureLiquiditySourceLine(id) : null;
    if (!payload) {
      if (valueEl) valueEl.textContent = '—';
      if (dateEl) dateEl.textContent = treasury ? 'Latest available · —' : 'Latest: --';
      if (sourceEl) sourceEl.textContent = 'Source · —';
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
      if (treasury) {
        dateEl.textContent = `Latest available · ${stamp || '—'}`;
        if (sourceEl) sourceEl.textContent = `Source · ${compactLiquiditySource(source, mode)}`;
      } else {
        const status = payload?.quote_status || payload?.live_quote_status || '';
        dateEl.textContent = `Intraday | ${stamp || '--'} | ${source}${status ? ' | '+status : ''}`;
      }
    } else {
      const obs = payload?.observation_date || payload?.date || '—';
      if (treasury) {
        dateEl.textContent = `Latest available · ${obs}`;
        const source = payload?.source || payload?.live_quote_source || 'Federal Reserve / FRED';
        if (sourceEl) sourceEl.textContent = `Source · ${compactLiquiditySource(source, mode)}`;
      } else {
        dateEl.textContent = `Latest official | ${obs}`;
      }
    }
  }

  function latestOfficialBefore(rows, targetMs) {
    if (!Array.isArray(rows) || !rows.length || !Number.isFinite(targetMs)) return null;
    let chosen = null;
    for (const row of rows) {
      const value = Number(row?.value);
      const ts = Date.parse(String(row?.date || '') + 'T00:00:00Z');
      if (!Number.isFinite(value) || !Number.isFinite(ts)) continue;
      if (ts <= targetMs) chosen = { value, ts, date:row.date };
      else break;
    }
    return chosen;
  }

  function ensureTreasuryChangeStack(id) {
    let el = document.getElementById(`${id}Change`);
    const valueEl = document.getElementById(`${id}Value`);
    const row = valueEl?.closest('.liq-value-row');
    const quote = valueEl?.closest('.liq-quote');
    const dateEl = document.getElementById(`${id}Date`);
    if (!row || !quote) return null;
    if (!el) {
      el = document.createElement('div');
      el.id = `${id}Change`;
      el.className = 'liq-change-stack';
      el.innerHTML = '<span class="liq-change-item">1D —</span><span class="liq-change-item">1M —</span>';
    }
    if (dateEl) quote.insertBefore(el, dateEl);
    else row.after(el);
    return el;
  }

  function treasuryQuoteMarketDateMs(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone:'America/New_York', year:'numeric', month:'2-digit', day:'2-digit'
  }).formatToParts(d);
  const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
  return Date.parse(`${p.year}-${p.month}-${p.day}T00:00:00Z`);
}

function treasuryPriorClose(rows, live, summaryRow) {
  const providerPreviousClose = Number(live?.previous_close);
  if (Number.isFinite(providerPreviousClose) && providerPreviousClose !== 0) {
    return {value:providerPreviousClose, source:'provider_previous_close'};
  }

  const quoteMarketDateMs = treasuryQuoteMarketDateMs(live?.timestamp || summaryRow?.live_quote_timestamp);
  if (Number.isFinite(quoteMarketDateMs)) {
    const priorOfficial = latestOfficialBefore(rows, quoteMarketDateMs - 1);
    if (priorOfficial) return priorOfficial;
  }

  const summaryClose = Number(summaryRow?.close_value);
  if (Number.isFinite(summaryClose) && summaryClose !== 0) {
    return {value:summaryClose, date:summaryRow?.close_observation_date || null, source:'official_summary_close'};
  }
  return latestFiniteRow(rows, 'value');
}

function calendarMonthTargetMs(referenceValue) {
  const d = new Date(referenceValue);
  if (Number.isNaN(d.getTime())) return null;
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone:'America/New_York', year:'numeric', month:'2-digit', day:'2-digit'
  }).formatToParts(d);
  const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
  const year = Number(p.year), month = Number(p.month), day = Number(p.day);
  const previousMonth = new Date(Date.UTC(year, month - 2, 1));
  const py = previousMonth.getUTCFullYear();
  const pm = previousMonth.getUTCMonth();
  const lastDay = new Date(Date.UTC(py, pm + 1, 0)).getUTCDate();
  return Date.UTC(py, pm, Math.min(day, lastDay));
}

function treasuryBasisPointChanges(key, live, summaryRow) {
  const price = Number(live?.price ?? live?.value ?? summaryRow?.value);
  if (!Number.isFinite(price)) return {oneDayBp:null, oneMonthBp:null};
  const rows = Array.isArray(state?.raw?.[key]) ? state.raw[key] : [];

  const prior = treasuryPriorClose(rows, live, summaryRow);
  const oneDayBp = prior && Number.isFinite(Number(prior.value))
    ? (price - Number(prior.value)) * 100
    : null;

  const referenceValue = live?.timestamp || summaryRow?.live_quote_timestamp || new Date().toISOString();
  const targetMs = calendarMonthTargetMs(referenceValue);
  const monthBase = Number.isFinite(targetMs) ? latestOfficialBefore(rows, targetMs) : null;
  const oneMonthBp = monthBase && Number.isFinite(Number(monthBase.value))
    ? (price - Number(monthBase.value)) * 100
    : null;
  return {oneDayBp, oneMonthBp};
}

function setTreasuryChangeBadges(id, key, live, summaryRow) {
  const el = ensureTreasuryChangeStack(id);
  if (!el) return;
  const {oneDayBp, oneMonthBp} = treasuryBasisPointChanges(key, live, summaryRow);
  const render = (label, value) => {
    if (!Number.isFinite(value)) return `<span class="liq-change-item">${label} —</span>`;
    const color = value > 0 ? 'var(--green)' : value < 0 ? 'var(--red)' : 'var(--muted)';
    return `<span class="liq-change-item" style="color:${color}">${label} ${value >= 0 ? '+' : ''}${value.toFixed(1)} bp</span>`;
  };
  el.innerHTML = render('1D', oneDayBp) + render('1M', oneMonthBp);
}

function ensureLiquidityMetricChangeStack(id, labels) {
  let el = document.getElementById(`${id}Change`);
  const valueEl = document.getElementById(`${id}Value`);
  const row = valueEl?.closest('.liq-value-row');
  const quote = valueEl?.closest('.liq-quote');
  const dateEl = document.getElementById(`${id}Date`);
  if (!row || !quote) return null;
  if (!el) {
    el = document.createElement('div');
    el.id = `${id}Change`;
    el.className = 'liq-change-stack';
    el.innerHTML = labels.map(label => `<span class="liq-change-item">${label} —</span>`).join('');
  }
  if (dateEl) quote.insertBefore(el, dateEl);
  else row.after(el);
  return el;
}

function liquidityChangeBadge(label, value, unit='%', decimals=1) {
  if (!Number.isFinite(value)) return `<span class="liq-change-item">${label} —</span>`;
  const color = value > 0 ? 'var(--green)' : value < 0 ? 'var(--red)' : 'var(--muted)';
  return `<span class="liq-change-item" style="color:${color}">${label} ${value >= 0 ? '+' : ''}${value.toFixed(decimals)}${unit}</span>`;
}

function setVixChangeBadges(live, summaryRow) {
  const el = ensureLiquidityMetricChangeStack('liqVix', ['1D','1M']);
  if (!el) return;

  const live1d = live?.change_1d_pct ?? live?.live_change_1d_pct;
  const summary1d = summaryRow?.live_change_1d_pct ?? summaryRow?.change_1d_pct;
  const oneDay = Number(live1d ?? summary1d);
  const oneMonth = Number(summaryRow?.change_20d_pct);

  el.innerHTML =
    liquidityChangeBadge('1D', oneDay, '%', 2) +
    liquidityChangeBadge('1M', oneMonth, '%', 1);
}

function setRealYieldChangeBadge(summaryRow) {
  const el = ensureLiquidityMetricChangeStack('liqReal10', ['1D']);
  if (!el) return;

  let oneDayBp = null;
  const summaryChange = Number(summaryRow?.change_1obs);
  if (Number.isFinite(summaryChange)) {
    oneDayBp = summaryChange * 100;
  } else {
    const rows = Array.isArray(state?.raw?.dfii10) ? state.raw.dfii10 : [];
    const valid = rows.filter(row => Number.isFinite(Number(row?.value)));
    if (valid.length >= 2) {
      oneDayBp = (Number(valid[valid.length - 1].value) - Number(valid[valid.length - 2].value)) * 100;
    }
  }

  el.innerHTML = liquidityChangeBadge('1D', oneDayBp, ' bp', 1);
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
    setTreasuryChangeBadges('liq10y', 'dgs10', q10, summary.dgs10);
    setTreasuryChangeBadges('liq30y', 'dgs30', q30, summary.dgs30);
    setLiquidityQuote('liqReal10', summary.dfii10 || latestFiniteRow(state.raw.dfii10,'value'), 2, 'daily');
    setRealYieldChangeBadge(summary.dfii10);
    setLiquidityQuote('liqHy', summary.hy_oas || latestFiniteRow(state.raw.hy,'value'), 2, 'daily');
    setLiquidityQuote('liqVix', qVix || latestFiniteRow(state.raw.vix,'close'), 2, qVix ? 'intraday' : 'daily');
    setVixChangeBadges(qVix, summary.vix);
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
      const order = {'US 10Y Treasury':0,'US 30Y Treasury':1,'VIX':2,'10Y Real Yield':3,'HY OAS':4,'NFCI':5};
      out.series = out.series.map(series => {
        const s = styles[series?.name];
        const next = s ? {...series,lineStyle:{...(series.lineStyle||{}),color:s.color,width:s.width,...(s.type?{type:s.type}:{})},itemStyle:{...(series.itemStyle||{}),color:s.color}} : {...series};
        if (series?.name === 'NFCI') { next.yAxisIndex=2; next.connectNulls=true; next.showSymbol=false; }
        return next;
      }).sort((a,b)=>(order[a?.name]??99)-(order[b?.name]??99));
    }
    return out;
  }

  function applyLegendSeriesFocus(option) {
    if (!option || typeof option !== 'object') return option;
    const out = {...option};
    if (Array.isArray(out.series)) {
      out.series = out.series.map(series => {
        if (!series || typeof series !== 'object') return series;
        return {...series,emphasis:{...(series.emphasis||{}),focus:'series'}};
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
    chart.setOption = function(option,...args){
      let next = applyLegendSeriesFocus(option);
      if (TIME_CHART_IDS.has(chartId)) next = withAviationZoom(next,chartId);
      return originalSetOption(next,...args);
    };
    patched.add(chart);
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

  if (!window.__aiBubbleLegendFocusInitPatched) {
    const originalEchartsInit = echarts.init.bind(echarts);
    echarts.init = function(dom,...args) {
      const chart = originalEchartsInit(dom,...args);
      patchChart(chart,dom?.id||'');
      return chart;
    };
    window.__aiBubbleLegendFocusInitPatched = true;
  }

  function scan() {
    document.querySelectorAll('[_echarts_instance_]').forEach(dom => {
      const chart=echarts.getInstanceByDom(dom); if (chart) patchChart(chart,dom.id||'');
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