from pathlib import Path

INDEX = Path('index.html')
SOURCES = Path('assets/source-links.js')

s = INDEX.read_text(encoding='utf-8')

# Replace the standalone Brent renderer with a dual-axis Brent + XAU/USD renderer.
start = s.index('// BRENT_STANDALONE_JS')
end = s.index('</script>', start)
new_js = r'''// MACRO_COMMODITY_STANDALONE_JS
let brentPayload=null,goldPayload=null,brentRange='1Y',brentChart=null;
function commodityCutoff(rows,range){
  if(!rows?.length)return[];
  if(range==='ALL')return rows;
  const months={"1M":1,"3M":3,"6M":6,"1Y":12}[range]||12;
  const end=new Date(rows[rows.length-1].date+'T00:00:00');
  const start=new Date(end);start.setMonth(start.getMonth()-months);
  return rows.filter(x=>new Date(x.date+'T00:00:00')>=start);
}
function renderBrentStandalone(){
  if(!brentPayload||!brentPayload.data?.length)return;
  const rows=brentPayload.data,last=rows[rows.length-1],prev=rows[rows.length-2];
  const quote=brentPayload.latest_quote||{},display=Number(quote.price??last.value);
  document.getElementById('brentValue').textContent=display.toFixed(2);
  document.getElementById('brentDate').textContent=quote.timestamp?quote.timestamp.replace('T',' ').slice(0,19)+' BJT':last.date;
  document.getElementById('brentStatus').textContent=quote.quote_status||brentPayload.status||'LIVE';
  const base=Number(prev?.value??last.value),chg=base?((display/base)-1)*100:0;
  const el=document.getElementById('brentChange');el.textContent=(chg>=0?'+':'')+chg.toFixed(2)+'% vs prior completed daily close';el.style.color=chg>0?'var(--green)':chg<0?'var(--red)':'var(--muted)';

  const br=commodityCutoff(rows,brentRange);
  const gr=goldPayload?.data?.length?commodityCutoff(goldPayload.data,brentRange):[];
  const dates=[...new Set([...br.map(x=>x.date),...gr.map(x=>x.date)])].sort();
  const bm=new Map(br.map(x=>[x.date,Number(x.value)]));
  const gm=new Map(gr.map(x=>[x.date,Number(x.value)]));

  const goldQuote=goldPayload?.latest_quote||{};
  const goldLast=goldPayload?.data?.length?goldPayload.data[goldPayload.data.length-1]:null;
  const goldDisplay=Number(goldQuote.price??goldLast?.value);
  const gv=document.getElementById('goldLatest');
  if(gv)gv.textContent=Number.isFinite(goldDisplay)?'$'+goldDisplay.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})+' / oz':'—';
  const gd=document.getElementById('goldDate');
  if(gd)gd.textContent=goldQuote.timestamp?goldQuote.timestamp.replace('T',' ').slice(0,19)+' BJT':(goldLast?.date||'—');

  if(!brentChart)brentChart=echarts.init(document.getElementById('brentChart'));
  brentChart.setOption({
    ...chartBase,
    legend:{...chartBase.legend,data:['Brent BZ=F','Gold XAU/USD']},
    grid:{...chartBase.grid,right:66},
    xAxis:{...chartBase.xAxis,data:dates},
    yAxis:[
      {...chartBase.yAxis,name:'Brent USD/bbl',scale:true,position:'left'},
      {...chartBase.yAxis,name:'Gold USD/oz',scale:true,position:'right',splitLine:{show:false},axisLabel:{color:'#a99063'}}
    ],
    series:[
      {name:'Brent BZ=F',type:'line',yAxisIndex:0,showSymbol:false,smooth:false,connectNulls:true,data:dates.map(d=>bm.get(d)??null),lineStyle:{width:1.9},areaStyle:{opacity:.045}},
      {name:'Gold XAU/USD',type:'line',yAxisIndex:1,showSymbol:false,smooth:false,connectNulls:true,data:dates.map(d=>gm.get(d)??null),lineStyle:{width:1.9,color:'#d2b36c'},itemStyle:{color:'#d2b36c'}}
    ]
  },true);
}
async function loadBrentStandalone(){
  try{
    const br=await fetch('data/ai_bubble/macro/brent.json?v='+Date.now(),{cache:'no-store'});
    if(!br.ok)throw new Error('Brent HTTP '+br.status);
    brentPayload=await br.json();
    try{
      const gr=await fetch('data/ai_bubble/macro/gold_xauusd.json?v='+Date.now(),{cache:'no-store'});
      if(gr.ok)goldPayload=await gr.json();else console.warn('Gold HTTP',gr.status);
    }catch(goldErr){console.warn('Gold load failed',goldErr)}
    renderBrentStandalone();
    document.querySelectorAll('#brentRange button').forEach(b=>b.addEventListener('click',()=>{
      document.querySelectorAll('#brentRange button').forEach(x=>x.classList.remove('active'));
      b.classList.add('active');brentRange=b.dataset.range;renderBrentStandalone();
    }));
    window.addEventListener('resize',()=>brentChart?.resize());
  }catch(e){console.error('Macro commodity load failed',e);const x=document.getElementById('brentStatus');if(x)x.textContent='LOAD ERROR'}
}
window.addEventListener('load',loadBrentStandalone);

'''
s = s[:start] + new_js + s[end:]

old_section = '''  <!-- BRENT_MACRO_SECTION -->
  <section class="section" id="brentMacroSection"><div class="section-head"><div><div class="section-title">Macro Commodity</div><div class="section-note">能源价格与通胀 / 金融条件背景</div></div></div>
    <div class="card brent-card">
      <div class="brent-head"><div><div class="brent-identity-top"><span class="brent-ticker">BZ=F</span><span class="brent-tag">ENERGY · CRUDE OIL</span><span class="brent-status" id="brentStatus">DELAYED</span></div><h2 class="brent-title">Brent Crude</h2><div class="brent-desc">Brent Crude Oil Last Day Financial Futures · Yahoo Finance BZ=F</div></div>
        <div class="brent-range" id="brentRange"><button data-range="1M">1M</button><button data-range="3M">3M</button><button data-range="6M">6M</button><button class="active" data-range="1Y">1Y</button><button data-range="ALL">ALL</button></div>
      </div>
      <div class="brent-quote-row"><div><div class="brent-price-line"><span class="brent-value" id="brentValue">—</span><span class="brent-unit">USD/bbl</span></div><div class="brent-change" id="brentChange">—</div></div><div class="brent-meta"><span class="brent-meta-label">LATEST</span><span class="brent-meta-value" id="brentDate">—</span><span class="brent-meta-label">FREQUENCY</span><span class="brent-meta-value">Daily history · 1m source bars / 5m polling</span><span class="brent-meta-label">SOURCE</span><span class="brent-meta-value">Yahoo Finance BZ=F</span></div></div>
      <div class="brent-divider"></div><div id="brentChart"></div>
    </div>
  </section>'''
new_section = '''  <!-- BRENT_MACRO_SECTION -->
  <section class="section" id="brentMacroSection"><div class="section-head"><div><div class="section-title">Macro Commodity</div><div class="section-note">能源与避险资产 / 通胀与金融条件背景</div></div></div>
    <div class="card brent-card">
      <div class="brent-head"><div><div class="brent-identity-top"><span class="brent-ticker">BZ=F</span><span class="brent-ticker">XAU/USD</span><span class="brent-tag">ENERGY · GOLD</span><span class="brent-status" id="brentStatus">DELAYED</span></div><h2 class="brent-title">Brent Crude & Gold Spot</h2><div class="brent-desc">Brent Crude · Yahoo Finance BZ=F · Gold Spot XAU/USD · Investing.com</div></div>
        <div class="brent-range" id="brentRange"><button data-range="1M">1M</button><button data-range="3M">3M</button><button data-range="6M">6M</button><button class="active" data-range="1Y">1Y</button><button data-range="ALL">ALL</button></div>
      </div>
      <div class="brent-quote-row"><div><div class="brent-price-line"><span class="brent-value" id="brentValue">—</span><span class="brent-unit">USD/bbl · Brent</span></div><div class="brent-change" id="brentChange">—</div></div><div class="brent-meta"><span class="brent-meta-label">BRENT LATEST</span><span class="brent-meta-value" id="brentDate">—</span><span class="brent-meta-label">GOLD XAU/USD</span><span class="brent-meta-value" id="goldLatest">—</span><span class="brent-meta-label">GOLD DATE</span><span class="brent-meta-value" id="goldDate">—</span><span class="brent-meta-label">SOURCES</span><span class="brent-meta-value">Yahoo Finance · Investing.com</span></div></div>
      <div class="brent-divider"></div><div id="brentChart"></div>
    </div>
  </section>'''
if old_section not in s:
    raise SystemExit('Macro Commodity section did not match expected source')
s = s.replace(old_section, new_section, 1)
INDEX.write_text(s, encoding='utf-8')

# Source-link mapping: canonical human-readable Investing.com page, matching the actual data source.
j = SOURCES.read_text(encoding='utf-8')
if 'investingGold:' not in j:
    needle = "    yahooBrent: {label:'Yahoo Finance · BZ=F', url:'https://finance.yahoo.com/quote/BZ=F/'},\n"
    repl = needle + "    investingGold: {label:'Investing.com · XAU/USD', url:'https://www.investing.com/currencies/xau-usd'},\n"
    if needle not in j:
        raise SystemExit('Yahoo Brent source definition not found')
    j = j.replace(needle, repl, 1)

old_rule = "    // Commodity.\n    if (t.includes('brent crude') || t === 'bz=f' || t.includes('brent bz=f')) return one(S.yahooBrent);"
new_rule = "    // Commodity.\n    if (contains(t,['macro commodity','brent crude & gold spot','brent crude + gold spot'])) return many([S.yahooBrent,S.investingGold]);\n    if (t.includes('xau/usd') || t.includes('gold spot')) return one(S.investingGold);\n    if (t.includes('brent crude') || t === 'bz=f' || t.includes('brent bz=f')) return one(S.yahooBrent);"
if old_rule not in j:
    raise SystemExit('Commodity source rule not found')
j = j.replace(old_rule, new_rule, 1)
SOURCES.write_text(j, encoding='utf-8')

print('Installed dual-axis Brent + Investing.com XAU/USD Macro Commodity chart')
