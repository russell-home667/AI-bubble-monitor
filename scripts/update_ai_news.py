#!/usr/bin/env python3
import hashlib,json,os,re,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

SGT=timezone(timedelta(hours=8)); NOW=datetime.now(SGT)
OUT=Path('data/ai_bubble/news/latest.json'); OUT.parent.mkdir(parents=True,exist_ok=True)
MODEL='deepseek-flash'; API='https://api.deepseek.com/responses'; GDELT='https://api.gdeltproject.org/api/v2/doc/doc'
CATS=['AI Revenue / Monetization','AI CAPEX','AI Valuation / Funding','Semiconductor / GPU Demand','Data Center / Power','AI Credit / Debt','Layoffs / Project Cancellation','Macro / Regulation']
QUERIES={
'AI Revenue / Monetization':'(OpenAI OR Anthropic OR xAI OR "artificial intelligence") (revenue OR monetization OR ARR OR subscription)',
'AI CAPEX':'(AI OR "artificial intelligence") (capex OR "capital expenditure") (Microsoft OR Alphabet OR Amazon OR Meta OR Oracle)',
'AI Valuation / Funding':'(OpenAI OR Anthropic OR xAI OR "AI startup") (funding OR valuation OR financing OR IPO)',
'Semiconductor / GPU Demand':'(NVIDIA OR AMD OR Broadcom OR TSMC OR HBM OR GPU) (AI OR "data center")',
'Data Center / Power':'("data center" OR datacenter) (AI OR "artificial intelligence") (power OR electricity OR grid OR nuclear OR construction)',
'AI Credit / Debt':'(AI OR "artificial intelligence" OR "data center") (debt OR credit OR loan OR bond OR financing)',
'Layoffs / Project Cancellation':'(AI OR "artificial intelligence" OR "data center") (layoffs OR cancellation OR canceled OR cancelled OR delay OR "order cut")',
'Macro / Regulation':'(AI OR "artificial intelligence" OR semiconductor) (regulation OR export OR tariff OR antitrust OR "Federal Reserve" OR rates)'}
TRUST={
'reuters.com':'Reuters','bloomberg.com':'Bloomberg','ft.com':'Financial Times','wsj.com':'Wall Street Journal','cnbc.com':'CNBC','apnews.com':'Associated Press','theinformation.com':'The Information','techcrunch.com':'TechCrunch','semafor.com':'Semafor','fortune.com':'Fortune','barrons.com':"Barron's",'economist.com':'The Economist','nytimes.com':'New York Times',
'openai.com':'OpenAI','anthropic.com':'Anthropic','x.ai':'xAI','microsoft.com':'Microsoft','abc.xyz':'Alphabet','blog.google':'Google','google.com':'Google','aboutamazon.com':'Amazon','amazon.com':'Amazon','meta.com':'Meta','about.fb.com':'Meta','oracle.com':'Oracle','nvidia.com':'NVIDIA','amd.com':'AMD','broadcom.com':'Broadcom','tsmc.com':'TSMC','coreweave.com':'CoreWeave','sec.gov':'U.S. SEC','federalreserve.gov':'Federal Reserve','commerce.gov':'U.S. Commerce Department','energy.gov':'U.S. Department of Energy','whitehouse.gov':'White House','congress.gov':'U.S. Congress','europa.eu':'European Union','ec.europa.eu':'European Commission','gov.uk':'UK Government'}
UA='AI-Bubble-Monitor/1.0 (+https://github.com/russell-home667/AI-bubble-monitor)'

def hostinfo(url):
 try: h=(urlparse(url).hostname or '').lower().removeprefix('www.')
 except: return None
 for d,n in TRUST.items():
  if h==d or h.endswith('.'+d): return d,n
 if h.endswith('.gov'): return h,'Official government source'
 return None

def dtparse(s):
 if not s:return None
 s=str(s)
 for f in ('%Y%m%dT%H%M%SZ','%Y%m%d%H%M%S','%Y-%m-%dT%H:%M:%SZ','%Y-%m-%dT%H:%M:%S%z','%Y-%m-%d'):
  try:
   d=datetime.strptime(s,f)
   if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
   return d.astimezone(SGT)
  except:pass
 try:
  d=datetime.fromisoformat(s.replace('Z','+00:00')); return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(SGT)
 except:return None

def norm(t):return ' '.join(re.sub(r'[^a-z0-9\u4e00-\u9fff]+',' ',str(t).lower()).split())
def sim(a,b):
 x=set(norm(a).split());y=set(norm(b).split());return len(x&y)/len(x|y) if x and y else 0
def sid(t,d):return hashlib.sha1((norm(t)+'|'+str(d)[:10]).encode()).hexdigest()[:14]
def get(url,**kw):
 for i in range(3):
  try:
   r=requests.get(url,timeout=35,**kw);r.raise_for_status();return r.json()
  except Exception as e:
   if i==2:raise
   time.sleep(1.5*(i+1))

def collect(mode):
 deep=mode=='deep'; span='7d' if deep else '8h'; mx=250 if deep else 100; out=[]
 for cat,q in QUERIES.items():
  try:d=get(GDELT,params={'query':q,'mode':'artlist','maxrecords':mx,'timespan':span,'sort':'datedesc','format':'json'},headers={'User-Agent':UA})
  except Exception as e:print('[news] GDELT',cat,e);continue
  for a in d.get('articles',[]) or []:
   u=str(a.get('url') or ''); hi=hostinfo(u); when=dtparse(a.get('seendate') or a.get('date')); title=' '.join(str(a.get('title') or '').split())
   if not hi or not when or len(title)<15 or NOW-when>timedelta(days=8):continue
   out.append({'id':f'c{len(out)+1}','title':title,'url':u,'source':hi[1],'domain':hi[0],'published_at':when.isoformat(timespec='minutes'),'query_category':cat})
  time.sleep(.2)
 out.sort(key=lambda x:x['published_at'],reverse=True); keep=[]; seen=set(); counts={}; cap=28 if deep else 14; total=220 if deep else 100
 for x in out:
  key=x['url'].split('#')[0]
  if key in seen or any(sim(x['title'],z['title'])>.88 for z in keep[-60:]):continue
  if counts.get(x['domain'],0)>=cap:continue
  seen.add(key);counts[x['domain']]=counts.get(x['domain'],0)+1;x['id']=f'c{len(keep)+1:03d}';keep.append(x)
  if len(keep)>=total:break
 print(f'[news] trusted candidates={len(keep)} span={span}')
 return keep

def output_text(r):
 if isinstance(r.get('output_text'),str):return r['output_text']
 parts=[]
 for o in r.get('output',[]) or []:
  for c in o.get('content',[]) or []:
   if c.get('type') in ('output_text','text') and c.get('text'):parts.append(c['text'])
 return '\n'.join(parts)

def ask(key,mode,cands):
 if not cands:return []
 compact=[{k:x[k] for k in ('id','title','source','domain','published_at','url','query_category')} for x in cands]
 instr='''You are the news analyst for an AI-bubble risk dashboard. Use ONLY the supplied candidate records; never invent facts, URLs, sources, dates, companies or amounts. Merge reports of the same underlying event. Return only events with importance >=50. Classify every event into exactly one allowed category. importance_score is 0-100 for significance to AI bubble formation/unwind. bubble_risk_score is -100..100: positive means higher bubble/unwind risk, negative means stronger fundamental support/lower bubble risk. summary_zh and reason_zh must be concise Chinese. Prefer Reuters/Bloomberg/FT/WSJ/AP/CNBC and official company/regulator sources. If the headline evidence is insufficient, omit the event instead of guessing.'''
 prompt='''Allowed categories:\n%s\n\nReturn JSON exactly as {"stories":[{"headline":"...","summary_zh":"...","category":"...","importance_score":0,"bubble_direction":"risk_up|risk_down|neutral","bubble_risk_score":0,"reason_zh":"...","companies":["..."],"primary_candidate_id":"c001","candidate_ids":["c001","c002"]}]}.\n\n%s scan. Candidate records:\n%s'''%(', '.join(CATS),'Deep 08:00 seven-day review; be comprehensive and strict.' if mode=='deep' else 'Intraday incremental review; focus on genuinely new significant events.',json.dumps(compact,ensure_ascii=False))
 body={'model':MODEL,'instructions':instr,'input':prompt,'reasoning':{'effort':'high' if mode=='deep' else 'low'},'max_output_tokens':18000 if mode=='deep' else 10000,'text':{'format':{'type':'json_object'}}}
 h={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
 r=requests.post(API,headers=h,json=body,timeout=180);r.raise_for_status();txt=output_text(r); data=json.loads(txt)
 lookup={x['id']:x for x in cands}; out=[]
 for s in data.get('stories',[]) or []:
  if s.get('category') not in CATS:continue
  try:imp=max(0,min(100,int(s.get('importance_score',0))));risk=max(-100,min(100,int(s.get('bubble_risk_score',0))))
  except:continue
  if imp<50:continue
  ids=[i for i in s.get('candidate_ids',[]) if i in lookup]; p=s.get('primary_candidate_id')
  if p not in lookup:p=ids[0] if ids else None
  if not p:continue
  if p not in ids:ids.insert(0,p)
  sources=[];su=set()
  for i in ids[:6]:
   x=lookup[i]
   if x['url'] in su:continue
   su.add(x['url']);sources.append({'name':x['source'],'domain':x['domain'],'url':x['url'],'published_at':x['published_at']})
   if len(sources)>=4:break
  x=lookup[p]; head=' '.join(str(s.get('headline') or x['title']).split())
  out.append({'id':sid(head,x['published_at']),'headline':head,'summary_zh':' '.join(str(s.get('summary_zh') or '').split()),'category':s['category'],'importance_score':imp,'bubble_direction':s.get('bubble_direction') if s.get('bubble_direction') in ('risk_up','risk_down','neutral') else 'neutral','bubble_risk_score':risk,'reason_zh':' '.join(str(s.get('reason_zh') or '').split()),'companies':[str(z).strip() for z in s.get('companies',[]) if str(z).strip()][:8],'published_at':x['published_at'],'sources':sources})
 print('[news] analyzed stories=',len(out));return out

def old():
 try:return json.loads(OUT.read_text()).get('stories',[]) if OUT.exists() else []
 except:return []
def merge(new,existing):
 cutoff=NOW-timedelta(days=7,hours=2);pool=[]
 for s in new+existing:
  d=dtparse(s.get('published_at'))
  if not d or d<cutoff or s.get('category') not in CATS:continue
  if not any(hostinfo(z.get('url','')) for z in s.get('sources',[])):continue
  pool.append(dict(s))
 pool.sort(key=lambda s:(int(s.get('importance_score',0)),str(s.get('published_at',''))),reverse=True);res=[]
 for s in pool:
  m=next((x for x in res if s.get('id')==x.get('id') or sim(s.get('headline',''),x.get('headline',''))>=.63 or ({z.get('url') for z in s.get('sources',[])}&{z.get('url') for z in x.get('sources',[])})),None)
  if m:
   src={z.get('url'):z for z in m.get('sources',[])+s.get('sources',[]) if z.get('url')};m['sources']=list(src.values())[:4];m['importance_score']=max(int(m.get('importance_score',0)),int(s.get('importance_score',0)));continue
  imp=max(0,min(100,int(s.get('importance_score',0))));risk=max(-100,min(100,int(s.get('bubble_risk_score',0))));s['importance_score']=imp;s['bubble_risk_score']=risk;s['critical']=imp>=85 or (imp>=75 and abs(risk)>=60);res.append(s)
 res.sort(key=lambda s:(int(s.get('importance_score',0)),str(s.get('published_at',''))),reverse=True);return res[:120]
def save(mode,stories):
 p={'generated_at_sgt':NOW.isoformat(timespec='seconds'),'timezone':'Asia/Singapore','model':'deepseek-flash','model_display':'DeepSeek V4.1 Flash','scan_mode':mode,'acquisition':'GDELT trusted article index + DeepSeek V4.1 Flash clustering/analysis','display_window_days':7,'homepage_limits':{'critical':10,'feed':10},'policy':{'important_threshold':60,'critical_rule':'importance>=85 OR (importance>=75 AND abs(bubble_risk_score)>=60)','trusted_sources_only':True,'sort':'importance_score desc, then published_at desc'},'categories':CATS,'stats':{'stored_stories':len(stories),'important_7d':sum(int(s.get('importance_score',0))>=60 for s in stories),'critical_7d':sum(bool(s.get('critical')) for s in stories)},'stories':stories}
 OUT.write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n')
def main():
 key=os.getenv('DEEPSEEK_API_KEY','').strip();mode=os.getenv('NEWS_SCAN_MODE','auto').lower()
 if not key:raise SystemExit('DEEPSEEK_API_KEY missing')
 if mode=='auto':mode='deep' if NOW.hour==8 else 'incremental'
 if mode not in ('deep','incremental'):raise SystemExit('bad NEWS_SCAN_MODE')
 print('[news] mode=',mode,'now=',NOW.isoformat()); c=collect(mode); n=ask(key,mode,c) if c else []; stories=merge(n,old()); save(mode,stories); print('[news] saved',len(stories))
if __name__=='__main__':main()
