(() => {
  'use strict';

  const DATA_URL = 'data/ai_bubble/news/latest.json';
  const IMPORTANT_MIN = 60;
  const HOME_LIMIT = 10;

  const CATEGORY_SHORT = {
    'AI Revenue / Monetization': 'Revenue / Monetization',
    'AI CAPEX': 'AI CAPEX',
    'AI Valuation / Funding': 'Valuation / Funding',
    'Semiconductor / GPU Demand': 'Semiconductor / GPU',
    'Data Center / Power': 'Data Center / Power',
    'AI Credit / Debt': 'AI Credit / Debt',
    'Layoffs / Project Cancellation': 'Layoffs / Cancellation',
    'Macro / Regulation': 'Macro / Regulation'
  };

  function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'
    })[c]);
  }

  function safeUrl(url) {
    try {
      const u = new URL(url, location.href);
      return /^https?:$/.test(u.protocol) ? u.href : '#';
    } catch (_) { return '#'; }
  }

  function fmtTime(s) {
    if (!s) return '—';
    const d = new Date(s);
    if (Number.isNaN(d.getTime())) return String(s);
    return new Intl.DateTimeFormat('zh-CN', {
      timeZone: 'Asia/Singapore',
      month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit',
      hour12:false
    }).format(d) + ' SGT';
  }

  function directionMeta(s) {
    const score = Number(s.bubble_risk_score || 0);
    if (s.bubble_direction === 'risk_up' || score > 15) return {cls:'up', text:`Bubble Risk ↑ ${score > 0 ? '+' : ''}${score}`};
    if (s.bubble_direction === 'risk_down' || score < -15) return {cls:'down', text:`Bubble Risk ↓ ${score}`};
    return {cls:'neutral', text:`Neutral ${score > 0 ? '+' : ''}${score}`};
  }

  function injectStyles() {
    if (document.getElementById('aiNewsStyles')) return;
    const st = document.createElement('style');
    st.id = 'aiNewsStyles';
    st.textContent = `
      .news-shell{display:block}
      .news-panel{padding:0;overflow:hidden}
      .news-panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:16px 17px 12px;border-bottom:1px solid rgba(29,49,73,.62)}
      .news-panel-title{font-size:14px;font-weight:760}
      .news-panel-sub{font-size:11px;color:var(--muted);margin-top:4px;line-height:1.45}
      .news-more{font-size:11px;color:#7ab9ff;border:1px solid rgba(90,168,255,.32);border-radius:999px;padding:5px 9px;white-space:nowrap}
      .news-more:hover{color:#dbeeff;border-color:#5aa8ff}
      .news-list{display:flex;flex-direction:column}
      .news-item{padding:14px 16px;border-bottom:1px solid rgba(29,49,73,.5)}
      .news-item:last-child{border-bottom:0}
      .news-topline{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-bottom:7px}
      .news-rank{font-size:10px;color:#5e7591;min-width:20px}
      .news-critical{font-size:10px;font-weight:800;color:#ff9caf;background:rgba(255,93,115,.11);border:1px solid rgba(255,93,115,.30);border-radius:999px;padding:3px 7px}
      .news-cat{font-size:10px;font-weight:700;color:#b8d9ff;background:rgba(90,168,255,.10);border:1px solid rgba(90,168,255,.23);border-radius:999px;padding:3px 7px}
      .news-importance{font-size:10px;color:#9fb1c8}
      .news-risk{font-size:10px;font-weight:700;border-radius:999px;padding:3px 7px}
      .news-risk.up{color:var(--red);background:rgba(255,93,115,.1)}
      .news-risk.down{color:var(--green);background:rgba(48,210,138,.1)}
      .news-risk.neutral{color:var(--yellow);background:rgba(244,201,93,.1)}
      .news-time{margin-left:auto;font-size:10px;color:#657e9b}
      .news-headline{display:block;font-size:13px;font-weight:700;line-height:1.5;color:#e8f0fb}
      .news-headline:hover{color:#8fc7ff}
      .news-summary{font-size:11px;line-height:1.62;color:#96abc3;margin-top:6px}
      .news-implication{font-size:11px;line-height:1.55;color:#c0cfdf;margin-top:6px}
      .news-implication b{color:#788fa9}
      .news-sources{font-size:10px;color:#667f9c;margin-top:8px;line-height:1.5}
      .news-sources a{color:#769fca}
      .news-sources a:hover{color:#b9dcff}
      .news-empty{padding:22px 16px;color:#7288a2;font-size:12px}
      @media(max-width:760px){.news-panel-head{padding-left:14px;padding-right:14px}.news-item{padding-left:14px;padding-right:14px}.news-time{margin-left:0;width:100%}}
    `;
    document.head.appendChild(st);
  }

  function panelMarkup() {
    return `
      <section class="section" id="aiNewsSection">
        <div class="section-head">
          <div>
            <div class="section-title">AI Bubble News Radar</div>
            <div class="section-note" id="aiNewsMeta">DeepSeek V4.1 Flash · trusted news / official sources · 7-day window</div>
          </div>
        </div>
        <div class="news-shell">
          <div class="card news-panel">
            <div class="news-panel-head">
              <div><div class="news-panel-title">AI Bubble News Feed</div><div class="news-panel-sub">过去7天重要新闻 · Critical 事件标记 · 按重要性排序 · 最多10条</div></div>
              <a class="news-more" href="news.html">More →</a>
            </div>
            <div class="news-list" id="importantNewsList"><div class="news-empty">Loading news…</div></div>
          </div>
        </div>
      </section>`;
  }

  function storyMarkup(s, rank) {
    const srcs = Array.isArray(s.sources) ? s.sources : [];
    const primary = srcs[0] || {};
    const url = safeUrl(primary.url || '#');
    const dm = directionMeta(s);
    const sourceHtml = srcs.slice(0, 3).map(x => {
      const u = safeUrl(x.url || '#');
      return `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(x.name || x.domain || 'Source')}↗</a>`;
    }).join(' · ');
    return `
      <article class="news-item">
        <div class="news-topline">
          <span class="news-rank">#${rank}</span>
          ${s.critical ? '<span class="news-critical">CRITICAL</span>' : ''}
          <span class="news-cat">${esc(CATEGORY_SHORT[s.category] || s.category || 'AI News')}</span>
          <span class="news-importance">Importance ${Number(s.importance_score || 0)}</span>
          <span class="news-risk ${dm.cls}">${esc(dm.text)}</span>
          <span class="news-time">${esc(fmtTime(s.published_at))}</span>
        </div>
        <a class="news-headline" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(s.headline)}</a>
        ${s.summary_zh ? `<div class="news-summary">${esc(s.summary_zh)}</div>` : ''}
        ${s.reason_zh ? `<div class="news-implication"><b>Bubble implication · </b>${esc(s.reason_zh)}</div>` : ''}
        ${sourceHtml ? `<div class="news-sources">Sources · ${sourceHtml}</div>` : ''}
      </article>`;
  }

  function renderList(id, stories) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!stories.length) {
      el.innerHTML = '<div class="news-empty">当前7天窗口内没有符合条件的事件。</div>';
      return;
    }
    el.innerHTML = stories.slice(0, HOME_LIMIT).map((s, i) => storyMarkup(s, i + 1)).join('');
  }

  async function loadNews() {
    try {
      const r = await fetch(`${DATA_URL}?v=${Date.now()}`, {cache:'no-store'});
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      const stories = Array.isArray(data.stories) ? data.stories : [];
      const sortFn = (a,b) =>
        (Number(b.importance_score || 0) - Number(a.importance_score || 0)) ||
        String(b.published_at || '').localeCompare(String(a.published_at || ''));

      const feed = stories.filter(x => Number(x.importance_score || 0) >= IMPORTANT_MIN).sort(sortFn);
      renderList('importantNewsList', feed);

      const meta = document.getElementById('aiNewsMeta');
      if (meta) {
        const mode = data.scan_mode === 'deep' ? 'deep scan' : 'intraday incremental';
        meta.textContent = `DeepSeek V4.1 Flash · ${mode} · ${fmtTime(data.generated_at_sgt)} · trusted news / official sources`;
      }
    } catch (err) {
      console.warn('AI news load failed', err);
      const el = document.getElementById('importantNewsList');
      if (el) el.innerHTML = '<div class="news-empty">News data is not available yet. The scheduled pipeline will populate this module.</div>';
    }
  }

  function mount() {
    if (document.getElementById('aiNewsSection')) return;
    injectStyles();
    const hero = document.querySelector('.hero');
    if (!hero) return;
    hero.insertAdjacentHTML('afterend', panelMarkup());
    loadNews();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true});
  else mount();
})();
