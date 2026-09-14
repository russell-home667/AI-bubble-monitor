#!/usr/bin/env python3
import hashlib,json,os,re,time,xml.etree.ElementTree as ET
from datetime import datetime,timedelta,timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse,parse_qs
import requests

SGT=timezone(timedelta(hours=8)); NOW=datetime.now(SGT)
OUT=Path('data/ai_bubble/news/latest.json'); OUT.parent.mkdir(parents=True,exist_ok=True)
MODEL='deepseek-flash'; CHAT_API='https://api.deepseek.com/chat/completions'; BING='https://www.bing.com/news/search'
CATS=['AI Revenue / Monetization','AI CAPEX','AI Valuation / Funding','Semiconductor / GPU Demand','Data Center / Power','AI Credit / Debt','Layoffs / Project Cancellation','Macro / Regulation']
QUERIES={
'AI Revenue / Monetization':'("artificial intelligence" OR AI) (revenue OR monetization OR ARR OR subscription) (OpenAI OR Anthropic OR Microsoft OR Google OR Meta OR Amazon)',
'AI CAPEX':'(AI OR "artificial intelligence") (capex OR "capital expenditure" OR investment) (Microsoft OR Meta OR Alphabet OR Amazon OR Oracle)',
'AI Valuation / Funding':'(OpenAI OR Anthropic OR xAI OR "AI startup") (funding OR valuation OR financing OR IPO OR investment)',
'Semiconductor / GPU Demand':'(Nvidia OR AMD OR Broadcom OR TSMC OR HBM OR GPU) (AI OR "data center") (demand OR sales OR orders OR supply)',
'Data Center / Power':'("data center" OR datacenter) (AI OR "artificial intelligence") (power OR electricity OR grid OR nuclear OR construction OR investment)',
'AI Credit / Debt':'(AI OR "artificial intelligence" OR "data center") (debt OR credit OR loan OR bond OR financing OR leverage)',
'Layoffs / Project Cancellation':'(AI OR "artificial intelligence" OR "data center") (layoffs OR cancellation OR canceled OR cancelled OR delay OR cut OR shutdown)',
'Macro / Regulation':'(AI OR "artificial intelligence" OR semiconductor) (regulation OR export OR tariff OR antitrust OR rates OR policy OR government)'}
TRUST={
'reuters.com':'Reuters','bloomberg.com':'Bloomberg','ft.com':'Financial Times','wsj.com':'Wall Street Journal','cnbc.com':'CNBC','apnews.com':'Associated Press','theinformation.com':'The Information','techcrunch.com':'TechCrunch','semafor.com':'Semafor','fortune.com':'Fortune','barrons.com':"Barron\'s",'economist.com':'The Economist','nytimes.com':'New York Times',
'openai.com':'OpenAI','anthropic.com':'Anthropic','x.ai':'xAI','microsoft.com':'Microsoft','abc.xyz':'Alphabet','blog.google':'Google','google.com':'Google','aboutamazon.com':'Amazon','amazon.com':'Amazon','meta.com':'Meta','about.fb.com':'Meta','oracle.com':'Oracle','nvidia.com':'NVIDIA','amd.com':'AMD','broadcom.com':'Broadcom','tsmc.com':'TSMC','coreweave.com':'CoreWeave','sec.gov':'U.S. SEC','federalreserve.gov':'Federal Reserve','commerce.gov':'U.S. Commerce Department','energy.gov':'U.S. Department of Energy','whitehouse.gov':'White House','congress.gov':'U.S. Congress','europa.eu':'European Union','ec.europa.eu':'European Commission','gov.uk':'UK Government'}
UA='Mozilla/5.0 (compatible; AI-Bubble-Monitor/1.0; +https://github.com/russell-home667/AI-bubble-monitor)'

def hostinfo(url):
 try:h=(urlparse(url).hostname or '').lower().removeprefix('www.')
 except:return None
 for d,n in TRUST.items():
  if h==d or h.endswith('.'+d):return d,n
 if h.endswith('.gov'):return h,'Official government source'
 return None

def unwrap_bing(url):
 try:
  p=urlparse(url)
  if p.hostname and p.hostname.endswith('bing.com') and p.path.endswith('/news/apiclick.aspx'):
   return (parse_qs(p.query).get('url') or [url])[0]
 except:pass
 return url

def dtparse(s):
 if not s:return None
 try:
  d=datetime.fromisoformat(str(s).replace('Z','+00:00'))
  if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
  return d.astimezone(SGT)
 except:pass
 try:
  d=parsedate_to_datetime(str(s));return d.astimezone(SGT)
 except:return None

def norm(t):return ' '.join(re.sub(r'[^a-z0-9\u4e00-\u9fff]+',' ',str(t).lower()).split())
def sim(a,b):
 x=set(norm(a).split());y=set(norm(b).split());return len(x&y)/len(x|y) if x and y else 0
def sid(t,d):return hashlib.sha1((norm(t)+'|'+str(d)[:10]).encode()).hexdigest()[:14]
def clean_html(s):return ' '.join(re.sub(r'<[^>]+>',' ',str(s or '')).replace('&nbsp;',' ').replace('&amp;','&').split())

def bing_page(query,interval,first):
 r=requests.get(BING,params={'q':query,'format':'RSS','setmkt':'en-US','first':first,'qft':f'interval="{interval}"'},headers={'User-Agent':UA,'Accept':'application/rss+xml,application/xml,text/xml,*/*'},timeout=30)
 r.raise_for_status();root=ET.fromstring(r.content);out=[]
 for item in root.findall('.//item'):
  title=clean_html(item.findtext('title'));url=unwrap_bing((item.findtext('link') or '').strip());when=dtparse(item.findtext('pubDate'));desc=clean_html(item.findtext('description'))
  hi=hostinfo(url)
  if not title or not url or not when or not hi:continue
  out.append({'title':title,'url':url,'source':hi[1],'domain':hi[0],'published_at':when.isoformat(timespec='minutes'),'description':desc[:900]})
 return out

def collect(mode):
 deep=mode=='deep';interval='8' if deep else '7';offsets=[1,11] if deep else [1];cut=NOW-(timedelta(days=7,hours=6) if deep else timedelta(hours=30));raw=[]
 for cat,q in QUERIES.items():
  for first in offsets:
   try:batch=bing_page(q,interval,first)
   except Exception as e:print('[news] Bing RSS error',cat,first,e);continue
   for x in batch:
    d=dtparse(x['published_at'])
    if d and d>=cut:x['query_category']=cat;raw.append(x)
   time.sleep(.15)
 raw.sort(key=lambda x:x['published_at'],reverse=True);res=[];seen=set();per_domain={}
 cap=28 if deep else 14;limit=220 if deep else 120
 for x in raw:
  u=x['url'].split('#')[0]
  if u in seen or any(sim(x['title'],z['title'])>.90 for z in res[-80:]):continue
  if per_domain.get(x['domain'],0)>=cap:continue
  seen.add(u);per_domain[x['domain']]=per_domain.get(x['domain'],0)+1;x['id']=f'c{len(res)+1:03d}';res.append(x)
  if len(res)>=limit:break
 print('[news] trusted candidates=',len(res),'domains=',dict(sorted(per_domain.items(),key=lambda x:-x[1])))
 return res

def chat_json(key,mode,cands):
 compact=[{k:x[k] for k in ('id','title','source','domain','published_at','description','query_category')} for x in cands]
 system='''You are the analyst for an AI-bubble risk dashboard. Analyze ONLY the supplied real news candidates. Do not invent events, facts, dates, URLs or candidate IDs. Merge candidates that describe the same underlying event. Classify each retained event into exactly one of the eight allowed categories. importance_score is 0-100 for importance to AI bubble formation/unwind. bubble_risk_score is -100..100: positive means higher bubble/unwind risk, negative means stronger fundamental support/lower bubble risk. summary_zh and reason_zh must be concise Chinese. Return only events with importance_score >= 50. Output valid JSON only.'''
 prompt=f'''Allowed categories: {json.dumps(CATS,ensure_ascii=False)}\nReturn exactly this JSON shape: {{"stories":[{{"headline":"...","summary_zh":"...","category":"one allowed category","importance_score":80,"bubble_direction":"risk_up|risk_down|neutral","bubble_risk_score":40,"reason_zh":"...","companies":["..."],"candidate_ids":["c001","c002"]}}]}}.\nChoose candidate_ids only from the supplied data; the first ID should be the best primary source. Prefer Reuters/Bloomberg/FT/WSJ/AP/CNBC and official primary sources when duplicates exist.\nCandidates:\n{json.dumps(compact,ensure_ascii=False)}'''
 body={'model':MODEL,'messages':[{'role':'system','content':system},{'role':'user','content':prompt}],'thinking':{'type':'enabled'},'reasoning_effort':'max' if mode=='deep' else 'high','response_format':{'type':'json_object'},'max_tokens':10000 if mode=='deep' else 7000}
 h={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
 for i in range(2):
  try:
   r=requests.post(CHAT_API,headers=h,json=body,timeout=180);r.raise_for_status();txt=(r.json().get('choices') or [{}])[0].get('message',{}).get('content','').strip()
   if not txt:raise ValueError('empty chat completion content')
   return json.loads(txt)
  except Exception as e:
   if i==1:raise
   print('[news] retry DeepSeek analysis:',e);time.sleep(2)

def analyze(key,mode,cands):
 if not cands:return []
 lookup={x['id']:x for x in cands};raw=[];size=45 if mode=='deep' else 55
 for i in range(0,len(cands),size):
  data=chat_json(key,mode,cands[i:i+size]);raw.extend(data.get('stories',[]) or []);print('[news] analyzed batch stories=',len(data.get('stories',[]) or []))
 out=[]
 for s in raw:
  if s.get('category') not in CATS:continue
  try:imp=max(0,min(100,int(s.get('importance_score',0))));risk=max(-100,min(100,int(s.get('bubble_risk_score',0))))
  except:continue
  if imp<50:continue
  ids=[]
  for x in s.get('candidate_ids',[]) or []:
   if x in lookup and x not in ids:ids.append(x)
  if not ids:continue
  primary=lookup[ids[0]];sources=[];su=set()
  for cid in ids[:6]:
   x=lookup[cid]
   if x['url'] in su:continue
   su.add(x['url']);sources.append({'name':x['source'],'domain':x['domain'],'url':x['url'],'published_at':x['published_at']})
   if len(sources)>=4:break
  head=' '.join(str(s.get('headline') or primary['title']).split())
  out.append({'id':sid(head,primary['published_at']),'headline':head,'summary_zh':' '.join(str(s.get('summary_zh') or '').split()),'category':s['category'],'importance_score':imp,'bubble_direction':s.get('bubble_direction') if s.get('bubble_direction') in ('risk_up','risk_down','neutral') else ('risk_up' if risk>15 else 'risk_down' if risk<-15 else 'neutral'),'bubble_risk_score':risk,'reason_zh':' '.join(str(s.get('reason_zh') or '').split()),'companies':[str(x).strip() for x in s.get('companies',[]) if str(x).strip()][:8],'published_at':primary['published_at'],'sources':sources})
 return out

def old():
 try:return json.loads(OUT.read_text(encoding='utf-8')).get('stories',[]) if OUT.exists() else []
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
  urls={z.get('url') for z in s.get('sources',[]) if z.get('url')}
  m=next((x for x in res if s.get('id')==x.get('id') or sim(s.get('headline',''),x.get('headline',''))>=.62 or urls&{z.get('url') for z in x.get('sources',[])}),None)
  if m:
   src={z.get('url'):z for z in m.get('sources',[])+s.get('sources',[]) if z.get('url')};m['sources']=list(src.values())[:4];m['importance_score']=max(int(m.get('importance_score',0)),int(s.get('importance_score',0)));continue
  imp=max(0,min(100,int(s.get('importance_score',0))));risk=max(-100,min(100,int(s.get('bubble_risk_score',0))));s['importance_score']=imp;s['bubble_risk_score']=risk;s['critical']=imp>=85 or (imp>=75 and abs(risk)>=60);res.append(s)
 res.sort(key=lambda s:(int(s.get('importance_score',0)),str(s.get('published_at',''))),reverse=True);return res[:120]
def save(mode,stories):
 p={'generated_at_sgt':NOW.isoformat(timespec='seconds'),'timezone':'Asia/Singapore','model':'deepseek-flash','model_display':'DeepSeek V4.1 Flash','scan_mode':mode,'acquisition':'Bing News RSS discovery + trusted-domain whitelist + DeepSeek V4.1 Flash analysis','display_window_days':7,'homepage_limits':{'critical':10,'feed':10},'policy':{'important_threshold':60,'critical_rule':'importance>=85 OR (importance>=75 AND abs(bubble_risk_score)>=60)','trusted_sources_only':True,'sort':'importance_score desc, then published_at desc'},'categories':CATS,'stats':{'stored_stories':len(stories),'important_7d':sum(int(s.get('importance_score',0))>=60 for s in stories),'critical_7d':sum(bool(s.get('critical')) for s in stories)},'stories':stories}
 OUT.write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
 key=os.getenv('DEEPSEEK_API_KEY','').strip();mode=os.getenv('NEWS_SCAN_MODE','auto').lower()
 if not key:raise SystemExit('DEEPSEEK_API_KEY missing')
 if mode=='auto':mode='deep' if NOW.hour==8 else 'incremental'
 if mode not in ('deep','incremental'):raise SystemExit('bad NEWS_SCAN_MODE')
 print('[news] mode=',mode,'now=',NOW.isoformat());cands=collect(mode)
 if mode=='deep' and not cands:raise SystemExit('Deep scan found zero trusted news candidates; refusing to publish an empty refresh')
 fresh=analyze(key,mode,cands);stories=merge(fresh,old())
 if mode=='deep' and not stories:raise SystemExit('Deep scan produced zero validated stories; refusing to publish an empty refresh')
 save(mode,stories);print('[news] saved',len(stories),'important',sum(s.get('importance_score',0)>=60 for s in stories),'critical',sum(bool(s.get('critical')) for s in stories))
if __name__=='__main__':main()
