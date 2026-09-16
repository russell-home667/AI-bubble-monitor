#!/usr/bin/env python3
from pathlib import Path

p = Path('assets/chart-time-slider.js')
s = p.read_text(encoding='utf-8')

css_old = """        #liquidityLatestGrid .liq-unit{color:#718aa1;font-size:10px;font-weight:600;}
        #liquidityLatestGrid .liq-date{margin-top:7px;color:#5f7b92;font-size:9px;line-height:1.35;}"""
css_new = """        #liquidityLatestGrid .liq-unit{color:#718aa1;font-size:10px;font-weight:600;}
        #liquidityLatestGrid .liq-change-stack{display:flex;flex-direction:column;gap:3px;margin-left:7px;align-self:center;font-size:9px;line-height:1.15;font-weight:700;white-space:nowrap;}
        #liquidityLatestGrid .liq-change-item{color:#86a0b6;}
        #liquidityLatestGrid .liq-date{margin-top:7px;color:#5f7b92;font-size:9px;line-height:1.35;}"""
if 'liq-change-stack' not in s:
    if css_old not in s:
        raise SystemExit('CSS anchor not found')
    s = s.replace(css_old, css_new, 1)

anchor = """  function syncLiquidityQuotes() {
    ensureLiquidityQuoteLayout();"""
helpers = '''  function latestOfficialBefore(rows, targetMs) {
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
    if (el) return el;
    const valueEl = document.getElementById(`${id}Value`);
    const row = valueEl?.closest('.liq-value-row');
    if (!row) return null;
    el = document.createElement('span');
    el.id = `${id}Change`;
    el.className = 'liq-change-stack';
    el.innerHTML = '<span class="liq-change-item">1D —</span><span class="liq-change-item">1M —</span>';
    row.appendChild(el);
    return el;
  }

  function treasuryPercentChanges(key, live, summaryRow) {
    const price = Number(live?.price ?? live?.value ?? summaryRow?.value);
    if (!Number.isFinite(price) || price === 0) return {oneDay:null, oneMonth:null};
    const rows = Array.isArray(state?.raw?.[key]) ? state.raw[key] : [];

    let prior = Number(summaryRow?.close_value);
    if (!Number.isFinite(prior) || prior === 0) {
      const last = latestFiniteRow(rows, 'value');
      prior = Number(last?.__value);
    }
    const oneDay = Number.isFinite(prior) && prior !== 0 ? (price / prior - 1) * 100 : null;

    const quoteMs = Date.parse(live?.timestamp || summaryRow?.live_quote_timestamp || '');
    const referenceMs = Number.isFinite(quoteMs) ? quoteMs : Date.now();
    const targetMs = referenceMs - 30 * 86400000;
    const monthBase = latestOfficialBefore(rows, targetMs);
    const oneMonth = monthBase && monthBase.value !== 0 ? (price / monthBase.value - 1) * 100 : null;
    return {oneDay, oneMonth};
  }

  function setTreasuryChangeBadges(id, key, live, summaryRow) {
    const el = ensureTreasuryChangeStack(id);
    if (!el) return;
    const {oneDay, oneMonth} = treasuryPercentChanges(key, live, summaryRow);
    const render = (label, value) => {
      if (!Number.isFinite(value)) return `<span class="liq-change-item">${label} —</span>`;
      const color = value > 0 ? 'var(--green)' : value < 0 ? 'var(--red)' : 'var(--muted)';
      return `<span class="liq-change-item" style="color:${color}">${label} ${value >= 0 ? '+' : ''}${value.toFixed(2)}%</span>`;
    };
    el.innerHTML = render('1D', oneDay) + render('1M', oneMonth);
  }

  function syncLiquidityQuotes() {
    ensureLiquidityQuoteLayout();'''
if 'function setTreasuryChangeBadges(' not in s:
    if anchor not in s:
        raise SystemExit('syncLiquidityQuotes anchor not found')
    s = s.replace(anchor, helpers, 1)

calls_old = """    setLiquidityQuote('liq10y', q10 || latestFiniteRow(state.raw.dgs10,'value'), q10 ? 3 : 2, q10 ? 'intraday' : 'daily');
    setLiquidityQuote('liq30y', q30 || latestFiniteRow(state.raw.dgs30,'value'), q30 ? 3 : 2, q30 ? 'intraday' : 'daily');"""
calls_new = """    setLiquidityQuote('liq10y', q10 || latestFiniteRow(state.raw.dgs10,'value'), q10 ? 3 : 2, q10 ? 'intraday' : 'daily');
    setLiquidityQuote('liq30y', q30 || latestFiniteRow(state.raw.dgs30,'value'), q30 ? 3 : 2, q30 ? 'intraday' : 'daily');
    setTreasuryChangeBadges('liq10y', 'dgs10', q10, summary.dgs10);
    setTreasuryChangeBadges('liq30y', 'dgs30', q30, summary.dgs30);"""
if "setTreasuryChangeBadges('liq10y'" not in s:
    if calls_old not in s:
        raise SystemExit('Treasury tile call anchor not found')
    s = s.replace(calls_old, calls_new, 1)

p.write_text(s, encoding='utf-8')
print('Treasury change badges patched')
