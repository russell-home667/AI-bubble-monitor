(() => {
  'use strict';

  if (window.__nfciCardFixLoaded) return;
  window.__nfciCardFixLoaded = true;

  const CSV_URL = 'data/ai_bubble/market_liquidity/nfci.csv';
  const SUMMARY_URL = 'data/ai_bubble/market_liquidity/latest.json';
  const DOM_POLL_MS = 250;
  const MAX_DOM_WAIT_MS = 60000;
  const REFRESH_MS = 5 * 60 * 1000;

  let rowsCache = [];
  let pointCache = null;
  const startedAt = Date.now();

  function parseCsv(text) {
    const lines = String(text || '').trim().split(/\r?\n/).filter(Boolean);
    if (lines.length < 2) return [];
    const header = lines[0].split(',').map(x => x.trim());
    const dateIndex = header.indexOf('date');
    const valueIndex = header.indexOf('value');
    if (dateIndex < 0 || valueIndex < 0) return [];

    const rows = [];
    for (let i = 1; i < lines.length; i += 1) {
      const cols = lines[i].split(',');
      const date = String(cols[dateIndex] || '').trim();
      const value = Number(cols[valueIndex]);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(value)) continue;
      rows.push({ date, value });
    }
    rows.sort((a, b) => a.date.localeCompare(b.date));
    return rows;
  }

  async function fetchData() {
    const stamp = Date.now();
    const results = await Promise.allSettled([
      fetch(`${CSV_URL}?v=${stamp}`, { cache: 'no-store' }),
      fetch(`${SUMMARY_URL}?v=${stamp}`, { cache: 'no-store' })
    ]);

    let rows = [];
    const csvResponse = results[0];
    if (csvResponse.status === 'fulfilled' && csvResponse.value.ok) {
      rows = parseCsv(await csvResponse.value.text());
    }

    let summaryPoint = null;
    const summaryResponse = results[1];
    if (summaryResponse.status === 'fulfilled' && summaryResponse.value.ok) {
      try {
        const payload = await summaryResponse.value.json();
        const x = payload?.indicators?.nfci;
        const value = Number(x?.value);
        const date = String(x?.observation_date || '');
        if (Number.isFinite(value) && /^\d{4}-\d{2}-\d{2}$/.test(date)) {
          summaryPoint = { date, value };
        }
      } catch (_) {}
    }

    const csvPoint = rows.length ? rows[rows.length - 1] : null;
    const point = (!summaryPoint || (csvPoint && csvPoint.date > summaryPoint.date))
      ? csvPoint
      : summaryPoint;

    if (!point) throw new Error('No valid NFCI observation available');
    rowsCache = rows;
    pointCache = point;
    return { rows, point };
  }

  function paintTile(point) {
    if (!point) return false;
    const valueEl = document.getElementById('liqNfciValue');
    const dateEl = document.getElementById('liqNfciDate');
    if (!valueEl || !dateEl) return false;

    valueEl.textContent = Number(point.value).toFixed(3);
    dateEl.textContent = `Latest official | ${point.date}`;
    valueEl.dataset.nfciReady = '1';
    dateEl.dataset.nfciReady = '1';
    return true;
  }

  function syncChartState(rows) {
    if (!Array.isArray(rows) || !rows.length) return false;
    try {
      if (typeof state === 'undefined' || !state?.raw) return false;
      state.raw.nfci = rows;
      if (typeof renderLiquidityChart === 'function') renderLiquidityChart();
      return true;
    } catch (err) {
      console.warn('NFCI state sync failed', err);
      return false;
    }
  }

  function applyCached() {
    const painted = paintTile(pointCache);
    if (rowsCache.length) syncChartState(rowsCache);
    return painted;
  }

  async function refresh() {
    try {
      const { rows, point } = await fetchData();
      paintTile(point);
      syncChartState(rows);
    } catch (err) {
      console.warn('NFCI independent loader failed', err);
    }
  }

  function waitForTile() {
    if (applyCached()) return;
    if (Date.now() - startedAt < MAX_DOM_WAIT_MS) {
      setTimeout(waitForTile, DOM_POLL_MS);
    }
  }

  function protectTile() {
    if (!pointCache) return;
    const valueEl = document.getElementById('liqNfciValue');
    const dateEl = document.getElementById('liqNfciDate');
    const expectedValue = Number(pointCache.value).toFixed(3);
    const expectedDate = `Latest official | ${pointCache.date}`;
    if (valueEl && valueEl.textContent !== expectedValue) valueEl.textContent = expectedValue;
    if (dateEl && dateEl.textContent !== expectedDate) dateEl.textContent = expectedDate;
  }

  refresh().finally(waitForTile);

  const observer = new MutationObserver(() => protectTile());
  const startObserver = () => {
    if (!document.body) return setTimeout(startObserver, DOM_POLL_MS);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  };
  startObserver();

  setInterval(() => {
    protectTile();
    refresh();
  }, REFRESH_MS);
})();
