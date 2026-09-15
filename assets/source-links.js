(() => {
  'use strict';

  // Source links intentionally point to the authoritative human-readable page
  // corresponding to the data acquisition source. They do not need to expose
  // the raw API / CSV endpoint used by the updater.
  const S = {
    methodology: {label:'Methodology / lineage', url:'backtest.html', internal:true},

    // Market prices are acquired from Yahoo Finance / yfinance.
    yahooNDX: {label:'Yahoo Finance · NDX', url:'https://finance.yahoo.com/quote/%5ENDX/'},
    yahooSOX: {label:'Yahoo Finance · SOX', url:'https://finance.yahoo.com/quote/%5ESOX/'},
    yahooNVDA: {label:'Yahoo Finance · NVDA', url:'https://finance.yahoo.com/quote/NVDA/'},
    yahooQQQ: {label:'Yahoo Finance · QQQ', url:'https://finance.yahoo.com/quote/QQQ/'},
    yahooRSP: {label:'Yahoo Finance · RSP', url:'https://finance.yahoo.com/quote/RSP/'},
    yahooBrent: {label:'Yahoo Finance · BZ=F', url:'https://finance.yahoo.com/quote/BZ=F/'},
    xausGold: {label:'XAUS Gold Data API · XAU/USD Spot', url:'https://xaus.com/'},
    goldApiGold: {label:'gold-api.com · XAU/USD Spot', url:'https://api.gold-api.com/price/XAU'},

    // VIX is acquired directly from Cboe's official historical dataset.
    cboeVIX: {label:'Cboe · VIX Historical Data', url:'https://www.cboe.com/tradable_products/vix/vix_historical_data/'},

    // Rates / credit are acquired from FRED; link to the matching FRED series page.
    fredReal10: {label:'FRED · DFII10', url:'https://fred.stlouisfed.org/series/DFII10'},
    fred10: {label:'FRED · DGS10', url:'https://fred.stlouisfed.org/series/DGS10'},
    fred30: {label:'FRED · DGS30', url:'https://fred.stlouisfed.org/series/DGS30'},
    fredHY: {label:'FRED · HY OAS', url:'https://fred.stlouisfed.org/series/BAMLH0A0HYM2'},
    fredIG: {label:'FRED · IG OAS', url:'https://fred.stlouisfed.org/series/BAMLC0A0CM'},
    fredBAA: {label:'FRED · BAA10Y', url:'https://fred.stlouisfed.org/series/BAA10Y'},

    // H5 quarterly financial statements are automatically acquired through Yahoo Finance.
    // Amazon 2026Q2 is overridden by the confirmed SEC 10-Q row in the stored database.
    yfMSFT: {label:'Yahoo Finance · MSFT Financials', url:'https://finance.yahoo.com/quote/MSFT/financials/'},
    yfGOOGL: {label:'Yahoo Finance · GOOGL Financials', url:'https://finance.yahoo.com/quote/GOOGL/financials/'},
    yfAMZN: {label:'Yahoo Finance · AMZN Financials', url:'https://finance.yahoo.com/quote/AMZN/financials/'},
    yfMETA: {label:'Yahoo Finance · META Financials', url:'https://finance.yahoo.com/quote/META/financials/'},
    yfORCL: {label:'Yahoo Finance · ORCL Financials', url:'https://finance.yahoo.com/quote/ORCL/financials/'},
    amznQ226SEC: {label:'SEC · Amazon 2026Q2 10-Q', url:'https://www.sec.gov/Archives/edgar/data/1018724/000101872426000026/amzn-20260630.htm'},

    // Cloud monetization values come from these exact official releases / filings.
    cloudMSFT: {label:'Microsoft IR · FY26 Q4 metrics', url:'https://www.microsoft.com/en-us/investor/earnings/fy-2026-q4/metrics'},
    cloudAMZN: {label:'Amazon IR · Q2 2026 results', url:'https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-Second-Quarter-Results/default.aspx'},
    cloudGOOGL: {label:'SEC · Alphabet Q2 2026 exhibit', url:'https://www.sec.gov/Archives/edgar/data/1652044/000165204426000066/googexhibit991q22026.htm'},
    cloudORCL: {label:'Oracle IR · FY26 Q4 results', url:'https://investor.oracle.com/investor-news/news-details/2026/Oracle-Announces-Record-Q4-and-FY-2026-Results-Driven-by-Cloud-Infrastructure--Cloud-Applications/default.aspx'},

    // Latest NVIDIA row is an official-source override; TSMC is fetched from its IR monthly-revenue pages.
    nvidiaCurrent: {label:'NVIDIA IR · Financial Reports', url:'https://investor.nvidia.com/financial-info/financial-reports/default.aspx'},
    tsmcCurrent: {label:'TSMC IR · 2026 Monthly Revenue', url:'https://investor.tsmc.com/english/monthly-revenue/2026'},
    tsmcLanding: {label:'TSMC IR · Monthly Revenue', url:'https://investor.tsmc.com/english/monthly-revenue'},

    // Current GPU cards are using the Runpod fallback because VAST_API_KEY is not configured.
    runpod: {label:'Runpod · GPU Models', url:'https://www.runpod.io/gpu-models'}
  };

  const H5_LATEST = [S.yfMSFT,S.yfGOOGL,S.amznQ226SEC,S.yfMETA,S.yfORCL];
  const H5_HISTORY = [S.yfMSFT,S.yfGOOGL,S.yfAMZN,S.amznQ226SEC,S.yfMETA,S.yfORCL];
  const H4_HISTORY = [S.yfMSFT,S.yfGOOGL,S.yfAMZN,S.amznQ226SEC,S.yfORCL];
  const CLOUD = [S.cloudMSFT,S.cloudAMZN,S.cloudGOOGL,S.cloudORCL];
  const MARKET = [S.yahooNDX,S.yahooSOX,S.yahooNVDA];
  const MARKET_HEAT = [S.yahooNDX,S.yahooSOX,S.yahooNVDA,S.yahooQQQ,S.yahooRSP];
  const LIQUIDITY = [S.fredReal10,S.fredHY,S.cboeVIX];
  const RATES = [S.fred10,S.fred30,S.fredReal10,S.fredHY,S.cboeVIX];
  const BACKTEST = [S.yahooNDX,S.yahooSOX,S.yahooNVDA,S.yahooQQQ,S.yahooRSP,S.cboeVIX,S.fredBAA,S.fredReal10,S.tsmcLanding];

  const norm = s => String(s || '').replace(/\s+/g,' ').trim().toLowerCase();
  const contains = (t, parts) => parts.some(x => t.includes(x));
  const external = src => !src.internal && /^https?:\/\//i.test(src.url);

  function one(src){ return {kind:'single', source:src}; }
  function many(sources){ return {kind:'multi', sources}; }

  function currentGoldSource(){
    let source='';
    try {
      if (typeof goldPayload !== 'undefined') source=String(goldPayload?.latest_quote?.source || '');
    } catch (_) {}
    const s=source.toLowerCase();
    if (s.includes('gold-api.com')) return S.goldApiGold;
    if (s.includes('xaus')) return S.xausGold;
    return null;
  }

  function syncCommoditySourceText(){
    const desc=document.querySelector('#brentMacroSection .brent-desc');
    if(!desc) return;
    let brent=null, gold=null;
    try { if(typeof brentPayload !== 'undefined') brent=brentPayload; } catch (_) {}
    try { if(typeof goldPayload !== 'undefined') gold=goldPayload; } catch (_) {}
    if(!brent || !gold) return;
    const brentSource=brent?.latest_quote?.source || brent?.source || '—';
    const goldSource=gold?.latest_quote?.source || gold?.source || '—';
    const next=`Current quote sources · Brent: ${brentSource} · Gold: ${goldSource}`;
    if(desc.textContent !== next) desc.textContent=next;
  }

  function ruleFor(raw){
    const t = norm(raw);
    if (!t) return null;

    // Derived outputs: show the actual upstream source lineage where compact enough.
    if (contains(t,['investment–monetization gap','investment-monetization gap'])) return many([...H4_HISTORY,...CLOUD]);
    if (contains(t,['investment–cash flow gap','investment-cash flow gap'])) return many(H5_HISTORY);
    if (contains(t,['price–fundamental gap','price-fundamental gap'])) return many([...MARKET_HEAT,S.nvidiaCurrent,S.tsmcCurrent]);
    if (t.includes('liquidity stress')) return many(LIQUIDITY);
    // Current score excludes GPU until 30D same-source history exists (coverage is 70%).
    if (t.includes('compute demand score')) return many([S.nvidiaCurrent,S.tsmcCurrent]);
    if (t.includes('nvidia demand quality')) return one(S.nvidiaCurrent);
    if (t.includes('market heat')) return many(MARKET_HEAT);
    if (t.includes('fundamental heat')) return many([S.nvidiaCurrent,S.tsmcCurrent]);
    if (t.includes('capital burden')) return many(H5_LATEST);
    if (t.includes('market trend breakdown')) return many(MARKET);
    if (contains(t,['cashflow deterioration','cash flow deterioration'])) return many(H5_HISTORY);
    if (t.includes('monetization deterioration')) return many(CLOUD);

    // Top-level model outputs are methodology-defined rather than sourced from one website.
    if (contains(t,[
      'ai bubble score','ai breakdown score','bubble score','breakdown score','current regime',
      'score composition','top score history','calibration result','breakdown p95',
      'first alert threshold','event validation','what the backtest says'
    ])) return one(S.methodology);

    if (t.includes('historical proxy') || t.includes('1999–present') || t.includes('1999-present')) return many(BACKTEST);

    // Commodity. The Gold live quote provider can switch between XAUS and gold-api.com,
    // so never hard-code the provider in the visible source label.
    if (contains(t,['macro commodity','brent crude & gold spot','brent crude + gold spot'])) {
      const goldSource=currentGoldSource();
      return goldSource ? many([S.yahooBrent,goldSource]) : null;
    }
    if (t.includes('xau/usd') || t.includes('gold spot')) {
      const goldSource=currentGoldSource();
      return goldSource ? one(goldSource) : null;
    }
    if (t.includes('brent crude') || t === 'bz=f' || t.includes('brent bz=f')) return one(S.yahooBrent);

    // Market prices.
    if (t.includes('nasdaq-100') || t === 'ndx' || t.includes('nasdaq 100')) return one(S.yahooNDX);
    if (t === 'sox' || t.includes('phlx semiconductor')) return one(S.yahooSOX);
    if (t.includes('qqq / rsp') || t.includes('qqq/rsp') || t.includes('concentration ratio')) return many([S.yahooQQQ,S.yahooRSP]);
    if ((t === 'nvidia' || t === 'nvda' || t.includes('nvidia price')) && !contains(t,['dc revenue','data center','demand quality','gross margin','inventory','dso'])) return one(S.yahooNVDA);
    if (t === 'vix' || t.includes('cboe vix')) return one(S.cboeVIX);
    if (t.includes('market prices') || t.includes('market price trend') || t.includes('market trend')) return many(MARKET);

    // Rates / credit.
    if (t.includes('30y treasury') || t.includes('30-year treasury') || t.includes('dgs30')) return one(S.fred30);
    if ((t.includes('10y treasury') || t.includes('10-year treasury') || t.includes('dgs10')) && !t.includes('real')) return one(S.fred10);
    if (t.includes('10y real yield') || t.includes('10-year real') || t.includes('dfii10')) return one(S.fredReal10);
    if (t.includes('hy oas') || t.includes('high yield oas')) return one(S.fredHY);
    if (t.includes('ig oas') || t.includes('investment grade oas')) return one(S.fredIG);
    if (t.includes('baa10y') || t.includes('baa-10y') || t.includes('baa 10y')) return one(S.fredBAA);
    if (t.includes('rates, credit') || t.includes('rates & credit') || t.includes('credit & liquidity') || t.includes('rates & liquidity')) return many(RATES);

    // Cloud monetization.
    if (t.includes('azure')) return one(S.cloudMSFT);
    if (t.includes('aws')) return one(S.cloudAMZN);
    if (t.includes('google cloud')) return one(S.cloudGOOGL);
    if (t.includes('oci') || t.includes('oracle cloud infrastructure')) return one(S.cloudORCL);
    if (t.includes('cloud monetization')) return many(CLOUD);

    // NVIDIA / semiconductor fundamentals.
    if (contains(t,['nvidia dc revenue','nvidia data center','nvidia gross margin','nvidia inventory','nvidia dso'])) return one(S.nvidiaCurrent);
    if (t.includes('tsmc')) return one(S.tsmcCurrent);

    // GPU rental pricing: current stored series is Runpod fallback.
    if (contains(t,['h100','h200','b200','gpu rental','gpu price'])) return one(S.runpod);

    // Hyperscaler company-specific latest cards.
    if (t.includes('microsoft')) return one(S.yfMSFT);
    if (t.includes('alphabet')) return one(S.yfGOOGL);
    if (t.includes('amazon')) return one(S.amznQ226SEC);
    if (t.includes('meta')) return one(S.yfMETA);
    if (t.includes('oracle')) return one(S.yfORCL);

    // H5 aggregate financials.
    if (contains(t,['h5 cash capex vs','free cash flow'])) return many(H5_HISTORY);
    if (contains(t,['h5 ','h5 cash','h5 standardized','capex / revenue','capex/revenue','d&a / revenue','d&a/revenue','hyperscaler investment'])) return many(H5_LATEST);

    return null;
  }

  function makeAnchor(src, text, compact=false){
    const a=document.createElement('a');
    a.className='source-link';
    a.href=src.url;
    a.textContent=text || src.label;
    a.setAttribute('aria-label',(text || src.label)+' source');
    if (external(src)) {
      a.target='_blank';
      a.rel='noopener noreferrer';
    }
    const arrow=document.createElement('span');
    arrow.className='source-arrow';
    arrow.textContent=external(src)?'↗':'→';
    a.appendChild(arrow);
    if(compact) a.dataset.compact='1';
    return a;
  }

  function attachSingle(el, src){
    const text=el.textContent.trim();
    el.textContent='';
    el.appendChild(makeAnchor(src,text));
  }

  function attachMulti(el, sources){
    const row=document.createElement('span');
    row.className='source-row';
    const prefix=document.createElement('span');
    prefix.className='source-prefix';
    prefix.textContent='Sources:';
    row.appendChild(prefix);
    sources.forEach((src,i)=>{
      if(i) row.appendChild(document.createTextNode(' · '));
      row.appendChild(makeAnchor(src,src.label,true));
    });
    el.appendChild(row);
  }

  function decorate(el){
    if(!el || el.dataset.sourceLinked==='1' || el.closest('.source-row')) return;
    const raw=el.textContent.trim();
    const rule=ruleFor(raw);
    if(!rule) return;
    el.dataset.sourceLinked='1';
    if(rule.kind==='single') attachSingle(el,rule.source);
    else attachMulti(el,rule.sources);
  }

  function decorateComponentRows(){
    document.querySelectorAll('#bubbleTable td:first-child,#breakdownTable td:first-child').forEach(decorate);
  }

  function decorateAll(){
    syncCommoditySourceText();
    document.querySelectorAll('.score-title,.regime-kicker,.metric-name,.chart-title,.brent-title,.brent-ticker,.name,.title').forEach(decorate);
    decorateComponentRows();
  }

  let scheduled=false;
  function schedule(){
    if(scheduled) return;
    scheduled=true;
    requestAnimationFrame(()=>{scheduled=false;decorateAll();});
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',schedule,{once:true});
  else schedule();

  const observer=new MutationObserver(schedule);
  observer.observe(document.documentElement,{childList:true,subtree:true});
})();
