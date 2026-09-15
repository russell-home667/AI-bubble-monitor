(() => {
  'use strict';

  const TIME_CHART_IDS = new Set([
    'brentChart',
    'marketChart',
    'liquidityChart',
    'capexFcfChart',
    'tsmcChart',
    'gpuChart',
    'scoreHistoryChart',
    'historyChart'
  ]);

  if (!window.echarts) return;

  const patched = new WeakSet();

  function formatBeijingTimestamp(value) {
    if (!value) return null;
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return null;
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23'
    }).formatToParts(d);
    const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
    return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second} BJT`;
  }

  function ensureCommodityQuoteLayout() {
    const row = document.querySelector('#brentMacroSection .brent-quote-row');
    if (!row) return null;

    let block = document.getElementById('goldQuoteMain');
    if (!block) {
      const style = document.createElement('style');
      style.id = 'gold-large-quote-style';
      style.textContent = `
        #brentMacroSection .brent-desc{display:none;}
        #brentMacroSection .brent-quote-row{
          display:grid;
          grid-template-columns:repeat(2,minmax(0,1fr));
          align-items:start;
          gap:72px;
          padding-top:24px;
          padding-bottom:8px;
        }
        #brentMacroSection .brent-quote-main,
        #brentMacroSection .gold-quote-main{min-width:0;max-width:520px;}
        #brentMacroSection .commodity-quote-label,
        #brentMacroSection .brent-quote-row > div:first-child::before{
          color:#6f8fa6;
          font-size:11px;
          font-weight:700;
          letter-spacing:.75px;
          margin-bottom:7px;
          text-transform:uppercase;
        }
        #brentMacroSection .brent-quote-row > div:first-child::before{
          content:'BRENT CRUDE';
          display:block;
        }
        #brentMacroSection .gold-price-line{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;}
        #brentMacroSection .gold-value{
          font-size:46px;
          line-height:1;
          font-weight:700;
          letter-spacing:.4px;
          color:#f0f8ff;
        }
        #brentMacroSection .gold-unit{color:#7895aa;font-size:13px;font-weight:600;}
        #brentMacroSection .gold-change{margin-top:8px;font-size:14px;font-weight:600;color:#8fa7b7;}
        #brentMacroSection .brent-time,
        #brentMacroSection .gold-time{margin-top:9px;color:#66859b;font-size:10px;line-height:1.45;}
        #brentMacroSection .brent-meta{display:none!important;}
        @media(max-width:900px){#brentMacroSection .brent-quote-row{gap:36px;}}
        @media(max-width:620px){
          #brentMacroSection .brent-quote-row{grid-template-columns:1fr;gap:24px;}
          #brentMacroSection .gold-value{font-size:39px;}
        }
      `;
      document.head.appendChild(style);

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
        <div class="gold-price-line">
          <span class="gold-value" id="goldBigValue">—</span>
          <span class="gold-unit">USD/oz · Gold</span>
        </div>
        <div class="gold-change" id="goldBigChange">—</div>
        <div class="gold-time" id="goldBigDate">Latest quote · —</div>
      `;

      const meta = row.querySelector('.brent-meta');
      if (meta) row.insertBefore(block, meta);
      else row.appendChild(block);
    }
    return block;
  }

  function syncCommodityQuotes() {
    const brent = typeof brentPayload !== 'undefined' ? brentPayload : null;
    const gold = typeof goldPayload !== 'undefined' ? goldPayload : null;

    ensureCommodityQuoteLayout();

    const brentFormatted = formatBeijingTimestamp(brent?.latest_quote?.timestamp);
    const brentQuoteTime = document.getElementById('brentQuoteTime');
    if (brentQuoteTime && brentFormatted) {
      const nextText = `Latest quote · ${brentFormatted}`;
      if (brentQuoteTime.textContent !== nextText) brentQuoteTime.textContent = nextText;
    }

    const brentDateEl = document.getElementById('brentDate');
    if (brentDateEl && brentFormatted && brentDateEl.textContent !== brentFormatted) {
      brentDateEl.textContent = brentFormatted;
    }

    const goldQuote = gold?.latest_quote || {};
    const goldRows = Array.isArray(gold?.data) ? gold.data : [];
    const goldLast = goldRows.length ? goldRows[goldRows.length - 1] : null;
    const goldPrice = Number(goldQuote.price ?? goldLast?.value);

    const goldValueEl = document.getElementById('goldBigValue');
    if (goldValueEl && Number.isFinite(goldPrice)) {
      const nextValue = goldPrice.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      });
      if (goldValueEl.textContent !== nextValue) goldValueEl.textContent = nextValue;
    }

    const goldTime = formatBeijingTimestamp(goldQuote.timestamp);
    const goldBigDate = document.getElementById('goldBigDate');
    if (goldBigDate && goldTime) {
      const nextDate = `Latest quote · ${goldTime}`;
      if (goldBigDate.textContent !== nextDate) goldBigDate.textContent = nextDate;
    }

    const goldChangeEl = document.getElementById('goldBigChange');
    const base = Number(goldLast?.value);
    if (goldChangeEl && Number.isFinite(goldPrice) && Number.isFinite(base) && base !== 0) {
      const change = (goldPrice / base - 1) * 100;
      const nextChange = `${change >= 0 ? '+' : ''}${change.toFixed(2)}% vs prior completed daily close`;
      const nextColor = change > 0 ? 'var(--green)' : change < 0 ? 'var(--red)' : 'var(--muted)';
      if (goldChangeEl.textContent !== nextChange) goldChangeEl.textContent = nextChange;
      if (goldChangeEl.style.color !== nextColor) goldChangeEl.style.color = nextColor;
    }
  }

  function latestFiniteRow(rows, valueKey) {
    if (!Array.isArray(rows)) return null;
    for (let i = rows.length - 1; i >= 0; i -= 1) {
      const row = rows[i];
      if (!row) continue;
      const value = Number(row[valueKey]);
      if (Number.isFinite(value)) return { ...row, __value: value };
    }
    return null;
  }

  function ensureLiquidityQuoteLayout() {
    const chart = document.getElementById('liquidityChart');
    const card = chart?.closest('.chart-card');
    if (!card) return null;
    card.classList.add('liquidity-card-enhanced');

    const head = card.querySelector('.chart-head');
    const sub = head?.querySelector('.chart-sub');
    if (sub) {
      const fixed = '10Y & 30Y Treasury / 10Y Real Yield / HY OAS / VIX / NFCI';
      if (sub.textContent !== fixed) sub.textContent = fixed;
    }

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
        #liquidityLatestGrid{
          display:grid;
          grid-template-columns:repeat(3,minmax(0,1fr));
          margin:14px 16px 2px;
          border:1px solid rgba(89,151,190,.15);
          border-radius:12px;
          overflow:hidden;
          background:rgba(3,14,25,.22);
        }
        #liquidityLatestGrid .liq-quote{
          min-width:0;
          padding:13px 14px 12px;
          border-right:1px solid rgba(89,151,190,.12);
          border-bottom:1px solid rgba(89,151,190,.12);
        }
        #liquidityLatestGrid .liq-quote:nth-child(3n){border-right:0;}
        #liquidityLatestGrid .liq-quote:nth-child(n+4){border-bottom:0;}
        #liquidityLatestGrid .liq-label{
          color:#7893aa;
          font-size:10px;
          font-weight:700;
          letter-spacing:.55px;
          text-transform:uppercase;
          white-space:nowrap;
          overflow:hidden;
          text-overflow:ellipsis;
        }
        #liquidityLatestGrid .liq-value-row{display:flex;align-items:baseline;gap:6px;margin-top:7px;min-width:0;}
        #liquidityLatestGrid .liq-value{color:#f0f8ff;font-size:31px;line-height:1;font-weight:720;letter-spacing:.2px;}
        #liquidityLatestGrid .liq-unit{color:#718aa1;font-size:10px;font-weight:600;}
        #liquidityLatestGrid .liq-date{margin-top:7px;color:#5f7b92;font-size:9px;line-height:1.35;}
        @media(max-width:980px){
          .liquidity-card-enhanced .range{flex-wrap:wrap;}
          #liquidityLatestGrid{grid-template-columns:repeat(2,minmax(0,1fr));}
          #liquidityLatestGrid .liq-quote{border-right:1px solid rgba(89,151,190,.12);border-bottom:1px solid rgba(89,151,190,.12);}
          #liquidityLatestGrid .liq-quote:nth-child(2n){border-right:0;}
          #liquidityLatestGrid .liq-quote:nth-child(n+5){border-bottom:0;}
        }
        @media(max-width:620px){
          #liquidityLatestGrid{grid-template-columns:1fr;}
          #liquidityLatestGrid .liq-quote{border-right:0!important;border-bottom:1px solid rgba(89,151,190,.12)!important;}
          #liquidityLatestGrid .liq-quote:last-child{border-bottom:0!important;}
          #liquidityLatestGrid .liq-value{font-size:28px;}
        }
      `;
      document.head.appendChild(style);
    }

    grid = document.createElement('div');
    grid.id = 'liquidityLatestGrid';
    grid.innerHTML = [
      ['liq10y','US 10Y Treasury','%'],
      ['liq30y','US 30Y Treasury','%'],
      ['liqReal10','10Y Real Yield','%'],
      ['liqHy','HY OAS','%'],
      ['liqVix','VIX','index'],
      ['liqNfci','NFCI','index']
    ].map(([id,label,unit]) => `
      <div class="liq-quote">
        <div class="liq-label">${label}</div>
        <div class="liq-value-row"><span class="liq-value" id="${id}Value">—</span><span class="liq-unit">${unit}</span></div>
        <div class="liq-date" id="${id}Date">Latest · —</div>
      </div>
    `).join('');

    if (head?.nextSibling) card.insertBefore(grid, head.nextSibling);
    else if (head) head.after(grid);
    else card.insertBefore(grid, chart);
    return grid;
  }

  function setLiquidityQuote(id, row, decimals) {
    if (!row) return;
    const valueEl = document.getElementById(`${id}Value`);
    const dateEl = document.getElementById(`${id}Date`);
    if (valueEl) {
      const nextValue = Number(row.__value).toFixed(decimals);
      if (valueEl.textContent !== nextValue) valueEl.textContent = nextValue;
    }
    if (dateEl) {
      const date = row.date || row.observation_date || '—';
      const nextDate = `Latest · ${date}`;
      if (dateEl.textContent !== nextDate) dateEl.textContent = nextDate;
    }
  }

  function syncLiquidityQuotes() {
    ensureLiquidityQuoteLayout();
    if (typeof state === 'undefined' || !state?.raw) return;
    setLiquidityQuote('liq10y', latestFiniteRow(state.raw.dgs10, 'value'), 2);
    setLiquidityQuote('liq30y', latestFiniteRow(state.raw.dgs30, 'value'), 2);
    setLiquidityQuote('liqReal10', latestFiniteRow(state.raw.dfii10, 'value'), 2);
    setLiquidityQuote('liqHy', latestFiniteRow(state.raw.hy, 'value'), 2);
    setLiquidityQuote('liqVix', latestFiniteRow(state.raw.vix, 'close'), 2);
    setLiquidityQuote('liqNfci', latestFiniteRow(state.raw.nfci, 'value'), 3);
  }

  function syncLiquiditySources() {
    const card = document.getElementById('liquidityChart')?.closest('.chart-card');
    const row = card?.querySelector('.chart-title .source-row');
    if (!row || row.querySelector('[data-nfci-source="1"]')) return;

    row.appendChild(document.createTextNode(' · '));
    const a = document.createElement('a');
    a.className = 'source-link';
    a.href = 'https://fred.stlouisfed.org/series/NFCI';
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.dataset.nfciSource = '1';
    a.setAttribute('aria-label', 'Chicago Fed / FRED · NFCI source');
    a.appendChild(document.createTextNode('Chicago Fed / FRED · NFCI '));
    const arrow = document.createElement('span');
    arrow.className = 'source-arrow';
    arrow.textContent = '↗';
    a.appendChild(arrow);
    row.appendChild(a);
  }

  function aviationDataZoom(chartId) {
    return [
      {
        type: 'inside',
        xAxisIndex: 0,
        filterMode: 'filter',
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: false
      },
      {
        type: 'slider',
        xAxisIndex: 0,
        height: 18,
        bottom: 9,
        left: 50,
        right: 24,
        realtime: true,
        borderColor: 'rgba(70, 193, 255, 0.10)',
        backgroundColor: 'rgba(4, 12, 20, 0.30)',
        fillerColor: 'rgba(70, 193, 255, 0.13)',
        handleStyle: {
          color: '#0d1828',
          borderColor: '#46c1ff',
          borderWidth: 1.4
        },
        moveHandleStyle: { color: 'rgba(142, 172, 201, 0.78)' },
        textStyle: { color: '#647f92' },
        showDetail: false,
        showDataShadow: chartId !== 'liquidityChart',
        brushSelect: true,
        zoomLock: false
      }
    ];
  }

  function tuneLiquidityOption(option) {
    if (!option || typeof option !== 'object') return option;
    const out = { ...option };

    out.grid = {
      ...(Array.isArray(out.grid) ? (out.grid[0] || {}) : (out.grid || {})),
      left: 72,
      right: 118,
      top: Math.max(Number((Array.isArray(out.grid) ? out.grid[0]?.top : out.grid?.top)) || 0, 54),
      bottom: 57,
      containLabel: false
    };

    out.legend = {
      ...(out.legend || {}),
      top: 8,
      left: 'center',
      itemGap: 12,
      itemWidth: 18,
      itemHeight: 8,
      textStyle: { ...((out.legend || {}).textStyle || {}), color: '#8ea2bc', fontSize: 10 }
    };

    const axes = Array.isArray(out.yAxis) ? out.yAxis.map(x => ({ ...x })) : [{ ...(out.yAxis || {}) }];
    const baseAxis = axes[0] || { type: 'value', scale: true };
    axes[0] = {
      ...baseAxis,
      name: 'Yield / OAS (%)',
      position: 'left',
      offset: 0,
      nameGap: 14,
      scale: true
    };
    axes[1] = {
      ...(axes[1] || baseAxis),
      name: 'VIX',
      position: 'right',
      offset: 0,
      nameGap: 14,
      scale: true,
      splitLine: { show: false }
    };
    axes[2] = {
      ...baseAxis,
      name: 'NFCI',
      position: 'right',
      offset: 54,
      nameGap: 14,
      scale: true,
      splitLine: { show: false },
      axisLine: { show: true, lineStyle: { color: '#58c6e8' } },
      axisLabel: { ...(baseAxis.axisLabel || {}), color: '#74a9c2' }
    };
    out.yAxis = axes;

    const seriesStyle = {
      'US 10Y Treasury': { color: '#6f83ff', width: 2.0 },
      'US 30Y Treasury': { color: '#9bd66f', width: 2.0 },
      '10Y Real Yield': { color: '#f5c75b', width: 2.0 },
      'HY OAS': { color: '#ff746d', width: 2.0 },
      'VIX': { color: '#b78cff', width: 2.0 },
      'NFCI': { color: '#58c6e8', width: 1.9, type: 'dashed' }
    };

    if (Array.isArray(out.series)) {
      out.series = out.series.map(series => {
        const style = seriesStyle[series?.name];
        const next = style ? {
          ...series,
          lineStyle: { ...(series.lineStyle || {}), color: style.color, width: style.width, ...(style.type ? { type: style.type } : {}) },
          itemStyle: { ...(series.itemStyle || {}), color: style.color }
        } : { ...series };

        if (series?.name === 'NFCI') {
          next.yAxisIndex = 2;
          next.connectNulls = true;
          next.showSymbol = false;
        }
        return next;
      });
    }

    return out;
  }

  function withAviationZoom(option, chartId) {
    if (!option || typeof option !== 'object') return option;
    let out = { ...option };
    if (chartId === 'liquidityChart') out = tuneLiquidityOption(out);

    if (Array.isArray(out.grid)) {
      out.grid = out.grid.map((g, i) => i === 0 ? { ...g, bottom: Math.max(Number(g?.bottom) || 0, 57) } : g);
    } else {
      out.grid = { ...(out.grid || {}), bottom: Math.max(Number(out.grid?.bottom) || 0, 57) };
    }

    out.dataZoom = aviationDataZoom(chartId);
    return out;
  }

  function patchChart(chart, chartId) {
    if (!chart || patched.has(chart)) return;
    const originalSetOption = chart.setOption.bind(chart);

    chart.setOption = function(option, ...args) {
      return originalSetOption(withAviationZoom(option, chartId), ...args);
    };

    patched.add(chart);
    const initial = chartId === 'liquidityChart'
      ? tuneLiquidityOption({ grid: { bottom: 57 } })
      : { grid: { bottom: 57 } };
    originalSetOption({ ...initial, dataZoom: aviationDataZoom(chartId) }, false);
  }

  function scan() {
    TIME_CHART_IDS.forEach(id => {
      const dom = document.getElementById(id);
      if (!dom) return;
      const chart = echarts.getInstanceByDom(dom);
      if (chart) patchChart(chart, id);
    });
    syncCommodityQuotes();
    syncLiquidityQuotes();
    syncLiquiditySources();
  }

  scan();

  let attempts = 0;
  const timer = setInterval(() => {
    scan();
    attempts += 1;
    if (attempts >= 40) clearInterval(timer);
  }, 500);
})();
