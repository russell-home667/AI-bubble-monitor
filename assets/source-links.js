(() => {
  'use strict';

  // Audited against the acquisition scripts. yfinance price history uses
  // query2 / v8 chart; yfinance statements use fundamentals-timeseries.
  const yfPeriod1 = 1483142400; // 2016-12-31 UTC, same start used by yfinance fundamentals.
  const yfPeriod2 = Math.ceil(Date.now() / 86400000) * 86400;
  const yahooChart = symbol => `https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=max&interval=1d&includePrePost=false&events=div%2Csplits%2CcapitalGains`;
  const yahooFundamentals = symbol => `https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/${encodeURIComponent(symbol)}?symbol=${encodeURIComponent(symbol)}&type=quarterlyTotalRevenue,quarterlyOperatingRevenue,quarterlyOperatingCashFlow,quarterlyCapitalExpenditure,quarterlyDepreciationAndAmortization,quarterlyDepreciationAmortizationDepletion,quarterlyReconciledDepreciation,quarterlyDepreciation&period1=${yfPeriod1}&period2=${yfPeriod2}`;
  const fredCsv = id => `https://fred.stlouisfed.org/graph/fredgraph.csv?id=${encodeURIComponent(id)}`;


  const S = {
    methodology: {label:'Methodology / lineage', url:'backtest.html', internal:true},
    yahooNDX: {label:'Yahoo chart API · NDX', url:yahooChart('^NDX')},
    yahooSOX: {label:'Yahoo chart API · SOX', url:yahooChart('^SOX')},
    yahooNVDA: {label:'Yahoo chart API · NVDA', url:yahooChart('NVDA')},
    yahooQQQ: {label:'Yahoo chart API · QQQ', url:yahooChart('QQQ')},
    yahooRSP: {label:'Yahoo chart API · RSP', url:yahooChart('RSP')},
    yahooBrentDaily: {label:'Yahoo daily API · BZ=F', url:yahooChart('BZ=F')},
    yahooBrent1m: {label:'Yahoo 1m API · BZ=F', url:'https://query1.finance.yahoo.com/v8/finance/chart/BZ%3DF?range=1d&interval=1m&includePrePost=true'},
    cboeVIX: {label:'Cboe CSV · VIX', url:'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'},
    fredReal10: {label:'FRED CSV · DFII10', url:fredCsv('DFII10')},
    fred10: {label:'FRED CSV · DGS10', url:fredCsv('DGS10')},
    fred30: {label:'FRED CSV · DGS30', url:fredCsv('DGS30')},
    fredHY: {label:'FRED CSV · HY OAS', url:fredCsv('BAMLH0A0HYM2')},
    fredIG: {label:'FRED CSV · IG OAS', url:fredCsv('BAMLC0A0CM')},
    fredBAA: {label:'FRED CSV · BAA10Y', url:fredCsv('BAA10Y')},
    yfMSFT: {label:'Yahoo fundamentals API · MSFT', url:yahooFundamentals('MSFT')},
    yfGOOGL: {label:'Yahoo fundamentals API · GOOGL', url:yahooFundamentals('GOOGL')},
    yfAMZN: {label:'Yahoo fundamentals API · AMZN', url:yahooFundamentals('AMZN')},
    yfMETA: {label:'Yahoo fundamentals API · META', url:yahooFundamentals('META')},
    yfORCL: {label:'Yahoo fundamentals API · ORCL', url:yahooFundamentals('ORCL')},
    amznQ226SEC: {label:'SEC 10-Q · AMZN 2026Q2', url:'https://www.sec.gov/Archives/edgar/data/1018724/000101872426000026/amzn-20260630.htm'},
    cloudMSFT: {label:'Microsoft FY26 Q4 metrics', url:'https://www.microsoft.com/en-us/investor/earnings/fy-2026-q4/metrics'},
    cloudAMZN: {label:'Amazon Q2 2026 results', url:'https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-Second-Quarter-Results/default.aspx'},
    cloudGOOGL: {label:'Alphabet Q2 2026 exhibit', url:'https://www.sec.gov/Archives/edgar/data/1652044/000165204426000066/googexhibit991q22026.htm'},
    cloudORCL: {label:'Oracle FY26 Q4 results', url:'https://investor.oracle.com/investor-news/news-details/2026/Oracle-Announces-Record-Q4-and-FY-2026-Results-Driven-by-Cloud-Infrastructure--Cloud-Applications/default.aspx'},
    nvidiaCurrent: {label:'NVIDIA Q2 FY27 10-Q', url:'https://investor.nvidia.com/files/doc_financials/2027/NVDA-2027-Q2-10Q-Final-including-exhibits.pdf'},
    tsmcCurrent: {label:'TSMC IR · 2026 monthly revenue', url:'https://investor.tsmc.com/english/monthly-revenue/2026'},
    runpod: {label:'Runpod · GPU Models', url:'https://www.runpod.io/gpu-models'},
    vastApi: {label:'Vast.ai bundles API', url:'https://console.vast.ai/api/v0/bundles/'}
  };

  const H5_LATEST = [S.yfMSFT,S.yfGOOGL,S.amznQ226SEC,S.yfMETA,S.yfORCL];
  const H5_HISTORY = [S.yfMSFT,S.yfGOOGL,S.yfAMZN,S.amznQ226SEC,S.yfMETA,S.yfORCL];
  const H4_HISTORY = [S.yfMSFT,S.yfGOOGL,S.yfAMZN,S.amznQ226SEC,S.yfORCL];
  const CLOUD = [S.cloudMSFT,S.cloudAMZN,S.cloudGOOGL,S.cloudORCL];
  const MARKET = [S.yahooNDX,S.yahooSOX,S.yahooNVDA];
  const MARKET_HEAT = [S.yahooNDX,S.yahooSOX,S.yahooNVDA,S.yahooQQQ,S.yahooRSP];
  const LIQUIDITY = [S.fredReal10,S.fredHY,S.cboeVIX];
  const RATES = [S.fred10,S.fred30,S.fredReal10,S.fredHY,S.cboeVIX];
  const BACKTEST = [S.yahooNDX,S.yahooSOX,S.yahooNVDA,S.yahooQQQ,S.yahooRSP,S.cboeVIX,S.fredBAA,S.fredReal10,S.tsmcCurrent];

  const norm = s => String(s || '').replace(/\s+/g,' ').trim().toLowerCase();
  const contains = (t, parts) => parts.some(x => t.includes(x));
  const external = src => !src.internal && /^https?:\/\//i.test(src.url);

  function one(src){ return {kind:'single', source:src}; }
  function many(sources){ return {kind:'multi', sources}; }

  function ruleFor(raw){
    const t = norm(raw);
    if (!t) return null;

    // Derived outputs with compact, auditable upstream lineages.
    if (contains(t,['investment–monetization gap','investment-monetization gap'])) return many([...H4_HISTORY,...CLOUD]);
    if (contains(t,['investment–cash flow gap','investment-cash flow gap'])) return many(H5_HISTORY);
    if (contains(t,['price–fundamental gap','price-fundamental gap'])) return many([...MARKET_HEAT,S.nvidiaCurrent,S.tsmcCurrent]);
    if (t.includes('liquidity stress')) return many(LIQUIDITY);
    if (t.includes('compute demand score')) return many([S.nvidiaCurrent,S.tsmcCurrent]);
    if (t.includes('nvidia demand quality')) return one(S.nvidiaCurrent);
    if (t.includes('market heat')) return many(MARKET_HEAT);
    if (t.includes('fundamental heat')) return many([S.nvidiaCurrent,S.tsmcCurrent]);
    if (t.includes('capital burden')) return many(H5_LATEST);
    if (t.includes('market trend breakdown')) return many(MARKET);
    if (contains(t,['cashflow deterioration','cash flow deterioration'])) return many(H5_HISTORY);
    if (t.includes('monetization deterioration')) return many(CLOUD);

    // Derived / model outputs: link to the monitor's methodology and calibration page.
    if (contains(t,[
      'ai bubble score','ai breakdown score','bubble score','breakdown score','current regime',
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
    if (t.includes('brent crude')) return many([S.yahooBrent1m,S.yahooBrentDaily]);
    if (t === 'bz=f' || t.includes('brent bz=f')) return one(S.yahooBrent1m);

    // Market-price sources.
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

    // Cloud monetization: company-specific rules before generic company / revenue rules.
    if (t.includes('azure')) return one(S.cloudMSFT);
    if (t.includes('aws')) return one(S.cloudAMZN);
    if (t.includes('google cloud')) return one(S.cloudGOOGL);
    if (t.includes('oci') || t.includes('oracle cloud infrastructure')) return one(S.cloudORCL);
    if (t.includes('cloud monetization')) return many(CLOUD);

    // NVIDIA / semiconductor fundamentals.
    if (contains(t,['nvidia dc revenue','nvidia data center','nvidia gross margin','nvidia inventory','nvidia dso'])) return one(S.nvidiaCurrent);
    if (t.includes('tsmc')) return one(S.tsmcCurrent);

    // GPU rental pricing. Current dashboard source is Runpod fallback; Vast.ai is the configured primary methodology.
    if (contains(t,['h100','h200','b200'])) return one(S.runpod);
    if (t.includes('gpu rental') || t.includes('gpu price')) return one(S.runpod);

    // Hyperscaler company-specific items.
    if (t.includes('microsoft')) return one(S.yfMSFT);
    if (t.includes('alphabet')) return one(S.yfGOOGL);
    if (t.includes('amazon')) return one(S.amznQ226SEC);
    if (t.includes('meta')) return one(S.yfMETA);
    if (t.includes('oracle')) return one(S.yfORCL);

    // H5 aggregate financials are sourced across all five company filings / IR pages.
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
