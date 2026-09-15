(() => {
  'use strict';

  // Shared ECharts time navigation, intentionally matched to the aviation-leasing dashboard.
  // Only true time-series charts are included; cross-sectional charts are excluded.
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

  // The commodity payload timestamps are ISO instants (normally UTC with a trailing Z).
  // Normalize them to Beijing time before display.
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

  function ensureGoldLargeQuote() {
    const row = document.querySelector('#brentMacroSection .brent-quote-row');
    if (!row) return null;

    let block = document.getElementById('goldQuoteMain');
    if (!block) {
      const style = document.createElement('style');
      style.id = 'gold-large-quote-style';
      style.textContent = `
        #brentMacroSection .brent-quote-row{
          display:grid;
          grid-template-columns:minmax(0,1fr) minmax(0,1fr) auto;
          align-items:end;
          gap:34px;
        }
        #brentMacroSection .gold-quote-main{min-width:230px;}
        #brentMacroSection .commodity-quote-label{
          color:#6f8fa6;
          font-size:11px;
          font-weight:700;
          letter-spacing:.75px;
          margin-bottom:7px;
          text-transform:uppercase;
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
        #brentMacroSection .gold-time{margin-top:7px;color:#66859b;font-size:10px;line-height:1.45;}
        #brentMacroSection .brent-quote-row > div:first-child::before{
          content:'BRENT CRUDE';
          display:block;
          color:#6f8fa6;
          font-size:11px;
          font-weight:700;
          letter-spacing:.75px;
          margin-bottom:7px;
        }
        @media(max-width:900px){
          #brentMacroSection .brent-quote-row{grid-template-columns:1fr 1fr;}
          #brentMacroSection .brent-meta{grid-column:1/-1;text-align:left;grid-template-columns:auto 1fr;}
        }
        @media(max-width:620px){
          #brentMacroSection .brent-quote-row{grid-template-columns:1fr;gap:22px;}
          #brentMacroSection .gold-value{font-size:39px;}
        }
      `;
      document.head.appendChild(style);

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
        <div class="gold-time" id="goldBigDate">—</div>
      `;

      const meta = row.querySelector('.brent-meta');
      if (meta) row.insertBefore(block, meta);
      else row.appendChild(block);

      // The small metadata price/date are now redundant; keep Sources visible.
      ['goldLatest', 'goldDate'].forEach(id => {
        const value = document.getElementById(id);
        if (!value) return;
        const label = value.previousElementSibling;
        value.style.display = 'none';
        if (label) label.style.display = 'none';
      });
    }
    return block;
  }

  function syncCommodityQuotes() {
    const brent = typeof brentPayload !== 'undefined' ? brentPayload : null;
    const gold = typeof goldPayload !== 'undefined' ? goldPayload : null;

    const brentTime = brent?.latest_quote?.timestamp;
    const brentDateEl = document.getElementById('brentDate');
    const brentFormatted = formatBeijingTimestamp(brentTime);
    if (brentDateEl && brentFormatted && brentDateEl.textContent !== brentFormatted) {
      brentDateEl.textContent = brentFormatted;
    }

    ensureGoldLargeQuote();
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

  function aviationDataZoom() {
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
        moveHandleStyle: {
          color: 'rgba(142, 172, 201, 0.78)'
        },
        textStyle: { color: '#647f92' },
        showDetail: false,
        showDataShadow: true,
        brushSelect: true,
        zoomLock: false
      }
    ];
  }

  function withAviationZoom(option) {
    if (!option || typeof option !== 'object') return option;
    const out = { ...option };

    if (Array.isArray(out.grid)) {
      out.grid = out.grid.map((g, i) => i === 0 ? { ...g, bottom: Math.max(Number(g?.bottom) || 0, 57) } : g);
    } else {
      out.grid = { ...(out.grid || {}), bottom: Math.max(Number(out.grid?.bottom) || 0, 57) };
    }

    out.dataZoom = aviationDataZoom();
    return out;
  }

  function patchChart(chart) {
    if (!chart || patched.has(chart)) return;
    const originalSetOption = chart.setOption.bind(chart);

    chart.setOption = function(option, ...args) {
      return originalSetOption(withAviationZoom(option), ...args);
    };

    patched.add(chart);
    originalSetOption({
      grid: { bottom: 57 },
      dataZoom: aviationDataZoom()
    }, false);
  }

  function scan() {
    TIME_CHART_IDS.forEach(id => {
      const dom = document.getElementById(id);
      if (!dom) return;
      const chart = echarts.getInstanceByDom(dom);
      if (chart) patchChart(chart);
    });
    syncCommodityQuotes();
  }

  // Run once immediately, then use a bounded lightweight poll while async chart/data
  // initialization finishes. Do not observe the whole document: commodity DOM writes and
  // ECharts mutations can otherwise recursively retrigger scans and freeze the page.
  scan();

  let attempts = 0;
  const timer = setInterval(() => {
    scan();
    attempts += 1;
    if (attempts >= 40) clearInterval(timer);
  }, 500);
})();
