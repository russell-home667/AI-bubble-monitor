(() => {
  'use strict';

  const NFCI_URL = 'data/ai_bubble/market_liquidity/nfci.csv';
  let cachedRows = null;
  let loadError = null;

  function stateReady() {
    try { return typeof state !== 'undefined' && !!state?.raw; }
    catch (_) { return false; }
  }

  function latestFinite(rows) {
    if (!Array.isArray(rows)) return null;
    for (let i = rows.length - 1; i >= 0; i -= 1) {
      const value = Number(rows[i]?.value);
      if (rows[i]?.date && Number.isFinite(value)) return {...rows[i], value};
    }
    return null;
  }

  function parseCsv(text) {
    if (window.Papa) {
      return Papa.parse(text, {header:true, dynamicTyping:true, skipEmptyLines:true}).data
        .filter(r => r?.date && Number.isFinite(Number(r.value)));
    }
    const lines = String(text || '').trim().split(/\r?\n/);
    if (lines.length < 2) return [];
    const header = lines[0].split(',');
    const dateIdx = header.indexOf('date');
    const valueIdx = header.indexOf('value');
    if (dateIdx < 0 || valueIdx < 0) return [];
    return lines.slice(1).map(line => {
      const cols = line.split(',');
      return {date: cols[dateIdx], value: Number(cols[valueIdx])};
    }).filter(r => r.date && Number.isFinite(r.value));
  }

  async function fetchRows() {
    const response = await fetch(`${NFCI_URL}?v=${Date.now()}`, {cache:'no-store'});
    if (!response.ok) throw new Error(`NFCI HTTP ${response.status}`);
    const rows = parseCsv(await response.text());
    if (!rows.length) throw new Error('NFCI dataset empty');
    return rows;
  }

  function applyRows(rows) {
    const latest = latestFinite(rows);
    if (!latest) return false;

    if (stateReady()) state.raw.nfci = rows;

    const valueEl = document.getElementById('liqNfciValue');
    const dateEl = document.getElementById('liqNfciDate');
    if (valueEl) valueEl.textContent = Number(latest.value).toFixed(3);
    if (dateEl) dateEl.textContent = `Latest official | ${latest.date}`;

    try {
      if (stateReady() && typeof renderLiquidityChart === 'function') renderLiquidityChart();
    } catch (err) {
      console.warn('NFCI chart refresh failed', err);
    }

    return Boolean(stateReady() && valueEl && dateEl);
  }

  async function start() {
    try {
      cachedRows = await fetchRows();
    } catch (err) {
      loadError = err;
      console.warn('NFCI deterministic load failed', err);
    }

    let attempts = 0;
    const maxAttempts = 160; // 40 seconds at 250ms; avoids the old ~2s race window.
    const tick = () => {
      attempts += 1;
      if (cachedRows && applyRows(cachedRows)) return;

      if (attempts >= maxAttempts) {
        const valueEl = document.getElementById('liqNfciValue');
        const dateEl = document.getElementById('liqNfciDate');
        if (valueEl && !cachedRows) valueEl.textContent = '—';
        if (dateEl && !cachedRows) dateEl.textContent = loadError ? 'Load unavailable' : 'Latest · —';
        return;
      }
      setTimeout(tick, 250);
    };
    tick();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, {once:true});
  } else {
    start();
  }
})();
