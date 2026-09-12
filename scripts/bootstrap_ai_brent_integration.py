#!/usr/bin/env python3
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / 'index.html'
OUT = ROOT / 'data' / 'ai_bubble' / 'macro' / 'brent.json'
AVIATION_SOURCE = 'https://raw.githubusercontent.com/russell-home667/aviation-leasing-dashboard/main/data/market_data.json'


def seed_data():
    payload = requests.get(AVIATION_SOURCE, timeout=60).json()
    brent = payload.get('brent')
    if not brent or not brent.get('data'):
        raise RuntimeError('Aviation Brent archive missing')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    brent['seed_source'] = 'russell-home667/aviation-leasing-dashboard data/market_data.json'
    OUT.write_text(json.dumps(brent, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Seeded Brent rows:', len(brent['data']), brent['data'][0]['date'], brent['data'][-1]['date'])


def patch_index():
    s = INDEX.read_text(encoding='utf-8')
    if 'BRENT_MACRO_SECTION' not in s:
        css = r'''
    /* Brent macro card adapted from the aviation-leasing dashboard */
    .brent-card{padding:0;overflow:hidden;background:linear-gradient(180deg,rgba(11,28,47,.96),rgba(7,20,35,.94));border:1px solid rgba(70,193,255,.27)}
    .brent-head{padding:20px 22px 0;display:flex;justify-content:space-between;gap:20px;align-items:flex-start}
    .brent-identity-top{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:7px}.brent-ticker{color:#66c8ff;font-size:13px;font-weight:700;letter-spacing:1.1px}.brent-tag{padding:3px 8px;border:1px solid rgba(105,174,215,.25);border-radius:999px;background:rgba(71,142,185,.08);color:#8db1c8;font-size:10px;font-weight:700;letter-spacing:.6px}.brent-status{padding:3px 8px;border-radius:999px;background:rgba(244,201,93,.1);border:1px solid rgba(244,201,93,.28);color:var(--yellow);font-size:10px;font-weight:700}.brent-title{margin:0;font-size:23px;line-height:1.22;font-weight:700}.brent-desc{margin-top:6px;color:#66859b;font-size:12px;line-height:1.5}
    .brent-range{display:flex;justify-content:flex-end;align-items:center;gap:5px;flex-wrap:wrap}.brent-range button{min-width:42px;padding:6px 9px;border:1px solid transparent;border-radius:6px;background:transparent;color:#7799af;cursor:pointer;font-size:12px}.brent-range button:hover{color:#c9eaff;background:rgba(70,193,255,.07)}.brent-range button.active{color:#dff5ff;border-color:rgba(91,194,255,.52);background:rgba(49,130,183,.24)}
    .brent-quote-row{padding:16px 22px 3px;display:flex;justify-content:space-between;align-items:flex-end;gap:20px;flex-wrap:wrap}.brent-price-line{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}.brent-value{font-size:46px;line-height:1;font-weight:700;letter-spacing:.4px;color:#f0f8ff}.brent-unit{color:#7895aa;font-size:13px;font-weight:600}.brent-change{margin-top:8px;font-size:14px;font-weight:600}.brent-meta{display:grid;grid-template-columns:auto auto;column-gap:10px;row-gap:4px;font-size:11px;line-height:1.45;text-align:right}.brent-meta-label{color:#57758b}.brent-meta-value{color:#8ba7b9}.brent-divider{height:1px;margin:12px 22px 0;background:linear-gradient(90deg,transparent,rgba(94,158,197,.18),transparent)}#brentChart{height:350px}
    @media(max-width:760px){.brent-head{flex-direction:column;padding-left:16px;padding-right:16px}.brent-range{justify-content:flex-start}.brent-quote-row{align-items:flex-start;padding-left:16px;padding-right:16px}.brent-value{font-size:39px}.brent-meta{text-align:left;grid-template-columns:auto 1fr;width:100%}.brent-divider{margin-left:16px;margin-right:16px}}
'''
        s = s.replace('  </style>', css + '  </style>', 1)
        marker = '  <section class="section"><div class="section-head"><div><div class="section-title">Hyperscaler Investment & Cash Return</div>'
        html = r'''  <!-- BRENT_MACRO_SECTION -->
  <section class="section" id="brentMacroSection"><div class="section-head"><div><div class="section-title">Macro Commodity</div><div class="section-note">能源价格与通胀 / 金融条件背景</div></div></div>
    <div class="card brent-card">
      <div class="brent-head"><div><div class="brent-identity-top"><span class="brent-ticker">BZ=F</span><span class="brent-tag">ENERGY · CRUDE OIL</span><span class="brent-status" id="brentStatus">DELAYED</span></div><h2 class="brent-title">Brent Crude</h2><div class="brent-desc">Brent Crude Oil Last Day Financial Futures · Yahoo Finance BZ=F</div></div>
        <div class="brent-range" id="brentRange"><button data-range="1M">1M</button><button data-range="3M">3M</button><button data-range="6M">6M</button><button class="active" data-range="1Y">1Y</button><button data-range="ALL">ALL</button></div>
      </div>
      <div class="brent-quote-row"><div><div class="brent-price-line"><span class="brent-value" id="brentValue">—</span><span class="brent-unit">USD/bbl</span></div><div class="brent-change" id="brentChange">—</div></div><div class="brent-meta"><span class="brent-meta-label">LATEST</span><span class="brent-meta-value" id="brentDate">—</span><span class="brent-meta-label">FREQUENCY</span><span class="brent-meta-value">Daily history · 1m source bars / 5m polling</span><span class="brent-meta-label">SOURCE</span><span class="brent-meta-value">Yahoo Finance BZ=F</span></div></div>
      <div class="brent-divider"></div><div id="brentChart"></div>
    </div>
  </section>

'''
        if marker not in s:
            raise RuntimeError('Hyperscaler insertion marker not found')
        s = s.replace(marker, html + marker, 1)

    if 'BRENT_STANDALONE_JS' not in s:
        js = r'''
// BRENT_STANDALONE_JS
let brentPayload=null, brentRange='1Y', brentChart=null;
function brentCutoff(rows,range){if(range==='ALL')return rows;const months={"1M":1,"3M":3,"6M":6,"1Y":12}[range]||12;const end=new Date(rows[rows.length-1].date+'T00:00:00');const start=new Date(end);start.setMonth(start.getMonth()-months);return rows.filter(x=>new Date(x.date+'T00:00:00')>=start)}
function renderBrentStandalone(){if(!brentPayload||!brentPayload.data?.length)return;const rows=brentPayload.data;const last=rows[rows.length-1],prev=rows[rows.length-2];const quote=brentPayload.latest_quote||{};const display=Number(quote.price??last.value);document.getElementById('brentValue').textContent=display.toFixed(2);document.getElementById('brentDate').textContent=quote.timestamp?quote.timestamp.replace('T',' ').slice(0,19)+' BJT':last.date;document.getElementById('brentStatus').textContent=quote.quote_status||brentPayload.status||'LIVE';const base=Number(prev?.value??last.value);const chg=base?((display/base)-1)*100:0;const el=document.getElementById('brentChange');el.textContent=(chg>=0?'+':'')+chg.toFixed(2)+'% vs prior completed daily close';el.style.color=chg>0?'var(--green)':chg<0?'var(--red)':'var(--muted)';const r=brentCutoff(rows,brentRange);if(!brentChart)brentChart=echarts.init(document.getElementById('brentChart'));brentChart.setOption({...chartBase,xAxis:{...chartBase.xAxis,data:r.map(x=>x.date)},yAxis:{...chartBase.yAxis,name:'USD/bbl',scale:true},series:[{name:'Brent BZ=F',type:'line',showSymbol:false,smooth:false,connectNulls:true,data:r.map(x=>x.value),lineStyle:{width:1.8},areaStyle:{opacity:.06}}]},true)}
async function loadBrentStandalone(){try{const r=await fetch('data/ai_bubble/macro/brent.json?v='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);brentPayload=await r.json();renderBrentStandalone();document.querySelectorAll('#brentRange button').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('#brentRange button').forEach(x=>x.classList.remove('active'));b.classList.add('active');brentRange=b.dataset.range;renderBrentStandalone()}));window.addEventListener('resize',()=>brentChart?.resize())}catch(e){console.error('Brent load failed',e);const x=document.getElementById('brentStatus');if(x)x.textContent='LOAD ERROR'}}
window.addEventListener('load',loadBrentStandalone);
'''
        s = s.replace('</script>', js + '\n</script>', 1)
    INDEX.write_text(s, encoding='utf-8')
    print('Patched index.html for Brent')


if __name__ == '__main__':
    seed_data()
    patch_index()
