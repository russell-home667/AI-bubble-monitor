(() => {
  'use strict';

  const S = {
    methodology: {label:'Methodology', url:'backtest.html', internal:true},
    yahooNDX: {label:'Yahoo Finance · NDX', url:'https://finance.yahoo.com/quote/%5ENDX/history/'},
    yahooSOX: {label:'Yahoo Finance · SOX', url:'https://finance.yahoo.com/quote/%5ESOX/history/'},
    yahooNVDA: {label:'Yahoo Finance · NVDA', url:'https://finance.yahoo.com/quote/NVDA/history/'},
    yahooQQQ: {label:'Yahoo Finance · QQQ', url:'https://finance.yahoo.com/quote/QQQ/history/'},
    yahooRSP: {label:'Yahoo Finance · RSP', url:'https://finance.yahoo.com/quote/RSP/history/'},
    yahooBrent: {label:'Yahoo Finance · BZ=F', url:'https://finance.yahoo.com/quote/BZ=F/'},
    cboeVIX: {label:'Cboe · VIX', url:'https://www.cboe.com/tradable_products/vix/vix_historical_data/'},
    fredReal10: {label:'FRED · DFII10', url:'https://fred.stlouisfed.org/series/DFII10'},
    fred10: {label:'FRED · DGS10', url:'https://fred.stlouisfed.org/series/DGS10'},
    fred30: {label:'FRED · DGS30', url:'https://fred.stlouisfed.org/series/DGS30'},
    fredHY: {label:'FRED · HY OAS', url:'https://fred.stlouisfed.org/series/BAMLH0A0HYM2'},
    fredIG: {label:'FRED · IG OAS', url:'https://fred.stlouisfed.org/series/BAMLC0A0CM'},
    fredBAA: {label:'FRED · BAA10Y', url:'https://fred.stlouisfed.org/series/BAA10Y'},
    microsoft: {label:'Microsoft IR', url:'https://www.microsoft.com/en-us/Investor'},
    alphabet: {label:'Alphabet IR', url:'https://abc.xyz/investor/'},
    amazon: {label:'Amazon IR', url:'https://ir.aboutamazon.com/quarterly-results/default.aspx'},
    meta: {label:'Meta IR', url:'https://investor.atmeta.com/financials/'},
    oracle: {label:'Oracle IR', url:'https://investor.oracle.com/financial-reporting/quarterly-earnings/'},
    nvidiaIR: {label:'NVIDIA IR', url:'https://investor.nvidia.com/financial-info/financial-reports/default.aspx'},
    tsmc: {label:'TSMC IR · Monthly Revenue', url:'https://investor.tsmc.com/english/monthly-revenue'},
    runpod: {label:'Runpod · GPU Models', url:'https://www.runpod.io/gpu-models'},
    vast: {label:'Vast.ai', url:'https://vast.ai/'}
  };

  const H5 = [S.microsoft,S.alphabet,S.amazon,S.meta,S.oracle];
  const CLOUD = [S.microsoft,S.amazon,S.alphabet,S.oracle];
  const MARKET = [S.yahooNDX,S.yahooSOX,S.yahooNVDA];
  const RATES = [S.fred10,S.fred30,S.fredReal10,S.fredHY,S.cboeVIX];
  const BACKTEST = [S.yahooNDX,S.yahooSOX,S.cboeVIX,S.fredBAA,S.tsmc];

  const norm = s => String(s || '').replace(/\s+/g,' ').trim().toLowerCase();
  const contains = (t, parts) => parts.some(x => t.includes(x));
  const external = src => !src.internal && /^https?:\/\//i.test(src.url);

  function one(src){ return {kind:'single', source:src}; }
  function many(sources){ return {kind:'multi', sources}; }

  function ruleFor(raw){
    const t = norm(raw);
    if (!t) return null;

    // Derived / model outputs: link to the monitor's methodology and calibration page.
    if (contains(t,[
      'ai bubble score','ai breakdown score','current regime',
      'investment–monetization gap','investment-monetization gap',
      'investment–cash flow gap','investment-cash flow gap',
      'price–fundamental gap','price-fundamental gap',
      'compute demand score','nvidia demand quality','liquidity stress',
      'market heat','fundamental heat','capital burden','market trend breakdown',
      'cashflow deterioration','cash flow deterioration','monetization deterioration',
      'score composition','top score history','calibration result','breakdown p95',
      'first alert threshold','event validation','what the backtest says'
    ])) return one(S.methodology);

    if (t.includes('historical proxy') || t.includes('1999–present') || t.includes('1999-present')) return many(BACKTEST);

    // Commodity.
    if (t.includes('brent crude') || t === 'bz=f' || t.includes('brent bz=f')) return one(S.yahooBrent);

    // Market-price sources.
    if (t.includes('nasdaq-100') || t === 'ndx' || t.includes('nasdaq 100')) return one(S.yahooNDX);
    if (t === 'sox' || t.includes('phlx semiconductor')) return one(S.yahooSOX);
    if (t.includes('qqq / rsp') || t.includes('qqq/rsp') || t.includes('concentration ratio')) return many([S.yahooQQQ,S.yahooRSP]);
    if ((t === 'nvidia' || t === 'nvda' || t.includes('nvidia price')) && !contains(t,['dc revenue','data center','demand quality','gross margin','inventory','dso'])) return one(S.yahooNVDA);
    if (t === 'vix' || t.includes('cboe vix')) return one(S.cboeVIX);
    if (t.includes('market prices') || t.includes('market price trend')) return many(MARKET);

    // Rates / credit.
    if (t.includes('30y treasury') || t.includes('30-year treasury') || t.includes('dgs30')) return one(S.fred30);
    if ((t.includes('10y treasury') || t.includes('10-year treasury') || t.includes('dgs10')) && !t.includes('real')) return one(S.fred10);
    if (t.includes('10y real yield') || t.includes('10-year real') || t.includes('dfii10')) return one(S.fredReal10);
    if (t.includes('hy oas') || t.includes('high yield oas')) return one(S.fredHY);
    if (t.includes('ig oas') || t.includes('investment grade oas')) return one(S.fredIG);
    if (t.includes('baa10y') || t.includes('baa-10y') || t.includes('baa 10y')) return one(S.fredBAA);
    if (t.includes('rates, credit') || t.includes('rates & credit') || t.includes('credit & liquidity') || t.includes('rates & liquidity')) return many(RATES);

    // Cloud monetization: company-specific rules before generic company / revenue rules.
    if (t.includes('azure')) return one(S.microsoft);
    if (t.includes('aws')) return one(S.amazon);
    if (t.includes('google cloud')) return one(S.alphabet);
    if (t.includes('oci') || t.includes('oracle cloud infrastructure')) return one(S.oracle);
    if (t.includes('cloud monetization')) return many(CLOUD);

    // NVIDIA / semiconductor fundamentals.
    if (contains(t,['nvidia dc revenue','nvidia data center','nvidia gross margin','nvidia inventory','nvidia dso'])) return one(S.nvidiaIR);
    if (t.includes('tsmc')) return one(S.tsmc);

    // GPU rental pricing. Current dashboard source is Runpod fallback; Vast.ai is the configured primary methodology.
    if (contains(t,['h100','h200','b200'])) return one(S.runpod);
    if (t.includes('gpu rental') || t.includes('gpu price')) return many([S.runpod,S.vast]);

    // Hyperscaler company-specific items.
    if (t.includes('microsoft')) return one(S.microsoft);
    if (t.includes('alphabet')) return one(S.alphabet);
    if (t.includes('amazon')) return one(S.amazon);
    if (t.includes('meta')) return one(S.meta);
    if (t.includes('oracle')) return one(S.oracle);

    // H5 aggregate financials are sourced across all five company filings / IR pages.
    if (contains(t,['h5 ','h5 cash','h5 standardized','capex / revenue','capex/revenue','d&a / revenue','d&a/revenue','free cash flow','cash capex vs','hyperscaler investment'])) return many(H5);

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
    document.querySelectorAll('#bubbleTable td:first-child,#breakdownTable td:first-child').forEach(el=>{
      if(el.dataset.sourceLinked==='1') return;
      el.dataset.sourceLinked='1';
      const text=el.textContent.trim();
      el.textContent='';
      el.appendChild(makeAnchor(S.methodology,text));
    });
  }

  function decorateAll(){
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
