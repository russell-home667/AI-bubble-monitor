#!/usr/bin/env python3
import hashlib,json,os,re,time,xml.etree.ElementTree as ET
from datetime import datetime,timedelta,timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse,parse_qs,urlunparse
import requests

SGT=timezone(timedelta(hours=8)); NOW=datetime.now(SGT)
OUT=Path('data/ai_bubble/news/latest.json'); OUT.parent.mkdir(parents=True,exist_ok=True)
MODEL='deepseek-flash'; CHAT_API='https://api.deepseek.com/chat/completions'
BING='https://www.bing.com/news/search'; GOOGLE='https://news.google.com/rss/search'; GDELT='https://api.gdeltproject.org/api/v2/doc/doc'
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
'reuters.com':'Reuters','bloomberg.com':'Bloomberg','ft.com':'Financial Times','wsj.com':'Wall Street Journal','cnbc.com':'CNBC','apnews.com':'Associated Press','theinformation.com':'The Information','techcrunch.com':'TechCrunch','semafor.com':'Semafor','fortune.com':'Fortune','barrons.com':"Barron's",'economist.com':'The Economist','nytimes.com':'New York Times',
'openai.com':'OpenAI','anthropic.com':'Anthropic','x.ai':'xAI','microsoft.com':'Microsoft','abc.xyz':'Alphabet','blog.google':'Google','google.com':'Google','aboutamazon.com':'Amazon','amazon.com':'Amazon','meta.com':'Meta','about.fb.com':'Meta','oracle.com':'Oracle','nvidia.com':'NVIDIA','amd.com':'AMD','broadcom.com':'Broadcom','tsmc.com':'TSMC','coreweave.com':'CoreWeave','sec.gov':'U.S. SEC','federalreserve.gov':'Federal Reserve','commerce.gov':'U.S. Commerce Department','energy.gov':'U.S. Department of Energy','whitehouse.gov':'White House','congress.gov':'U.S. Congress','europa.eu':'European Union','ec.europa.eu':'European Commission','gov.uk':'UK Government'}
UA='Mozilla/5.0 (compatible; AI-Bubble-Monitor/1.2; +https://github.com/russell-home667/AI-bubble-monitor)'
CACHE_DAYS=8; CACHE_MAX=1800

def hostinfo(url):
 try:h=(urlparse(url).hostname or '').lower().removeprefix('www.')
 except:return None
 for d,n in TRUST.items():
  if h==d or h.endswith('.'+d):return d,n
 if h.endswith('.gov'):return h,'Official government source'
 return None

def domaininfo(domain):
 h=str(domain or '').lower().strip().removeprefix('www.')
 if not h:return None
 for d,n in TRUST.items():
  if h==d or h.endswith('.'+d):return d,n
 if h.endswith('.gov'):return h,'Official government source'
 return None

def trusted_source_obj(source):return domaininfo(source.get('domain')) or hostinfo(source.get('url',''))

def unwrap_bing(url):
 try:
  p=urlparse(url)
  if p.hostname and p.hostname.endswith('bing.com') and p.path.endswith('/news/apiclick.aspx'):
   return (parse_qs(p.query).get('url') or [url])[0]
 except:pass
 return url

def canon_url(url):
 try:
  p=urlparse(str(url or '').strip());host=(p.hostname or '').lower().removeprefix('www.');path=re.sub(r'/+$','',p.path or '/') or '/'
  return urlunparse((p.scheme.lower() or 'https',host,path,'','',''))
 except:return str(url or '').split('#')[0].split('?')[0].rstrip('/')

def dtparse(s):
 if not s:return None
 text=str(s).strip()
 try:
  d=datetime.fromisoformat(text.replace('Z','+00:00'))
  if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
  return d.astimezone(SGT)
 except:pass
 for fmt in ('%Y%m%dT%H%M%SZ','%Y%m%d%H%M%S'):
  try:return datetime.strptime(text,fmt).replace(tzinfo=timezone.utc).astimezone(SGT)
  except:pass
 try:return parsedate_to_datetime(text).astimezone(SGT)
 except:return None

def norm(t):return ' '.join(re.sub(r'[^a-z0-9\u4e00-\u9fff]+',' ',str(t).lower()).split())
def sim(a,b):
 x=set(norm(a).split());y=set(norm(b).split());return len(x&y)/len(x|y) if x and y else 0
def sid(t,d):return hashlib.sha1((norm(t)+'|'+str(d)[:10]).encode()).hexdigest()[:14]
def clean_html(s):return ' '.join(re.sub(r'<[^>]+>',' ',str(s or '')).replace('&nbsp;',' ').replace('&amp;','&').split())

def salient_numbers(text):
 out=set()
 for m in re.finditer(r'(?<!\w)([$€£]?\s*\d+(?:[.,]\d+)?\s*(?:%|percent|bn|billion|million|trillion|mn|m|b|t)?)(?!\w)',str(text or ''),re.I):
  v=''.join(m.group(1).lower().replace(',','').split());digits=re.sub(r'[^0-9.]','',v)
  try:n=float(digits)
  except:continue
  tagged=any(k in v for k in ('%','$','€','£','bn','billion','million','trillion','mn','m','b','t'))
  if 1900<=n<=2100 and not tagged:continue
  if n<=31 and not tagged:continue
  out.add(v)
 return out

def numbers_compatible(a,b):
 na=salient_numbers(a);nb=salient_numbers(b)
 return True if not na and not nb else na==nb

def within_hours(a,b,hours):
 da,db=dtparse(a),dtparse(b);return bool(da and db and abs((da-db).total_seconds())<=hours*3600)

def source_from_candidate(x):
 return {'name':x.get('source'),'domain':x.get('domain'),'url':x.get('url'),'published_at':x.get('published_at'),'discovered_via':x.get('discovery_source')}

def add_source(story,cand):
 out=dict(story);srcs=[dict(z) for z in (story.get('sources') or [])];cu=canon_url(cand.get('url'))
 if cu and all(canon_url(z.get('url'))!=cu for z in srcs):srcs.append(source_from_candidate(cand))
 out['sources']=srcs[:4];return out

def load_state():
 if not OUT.exists():return {},[],[]
 try:
  p=json.loads(OUT.read_text(encoding='utf-8'));return p,p.get('stories',[]) or [],p.get('candidate_cache',[]) or []
 except:return {},[],[]

def history_filter(cands,existing,cache):
 stories=[dict(s) for s in existing];cut=NOW-timedelta(days=CACHE_DAYS,hours=6)
 live=[x for x in cache if dtparse(x.get('published_at')) and dtparse(x.get('published_at'))>=cut]
 by_url={}
 for row in live:
  u=canon_url(row.get('url'))
  if u:by_url.setdefault(u,[]).append(row)
 ai=[];reused=exact=story_reuse=0
 for cand in cands:
  title=cand.get('title','');ctext=title+' | '+cand.get('description','');cu=canon_url(cand.get('url'));matched=False
  for row in by_url.get(cu,[]):
   oldtext=str(row.get('title') or '')+' | '+str(row.get('description') or '')
   if sim(title,row.get('title',''))>=.72 and numbers_compatible(ctext,oldtext):matched=True;exact+=1;break
  if not matched:
   for row in live:
    if row.get('domain')==cand.get('domain') and sim(title,row.get('title',''))>=.90 and numbers_compatible(ctext,str(row.get('title') or '')+' | '+str(row.get('description') or '')):
     matched=True;break
  if matched:reused+=1;continue
  best_i=None;best_score=0.0
  for i,story in enumerate(stories):
   if not within_hours(cand.get('published_at'),story.get('published_at'),96):continue
   head=story.get('headline','');score=sim(title,head);story_urls={canon_url(z.get('url')) for z in (story.get('sources') or []) if z.get('url')}
   threshold=.62 if cu and cu in story_urls else .84
   if score<threshold or not numbers_compatible(title,head+' | '+str(story.get('summary_zh') or '')):continue
   if score>best_score:best_i=i;best_score=score
  if best_i is not None:
   stories[best_i]=add_source(stories[best_i],cand);reused+=1;story_reuse+=1;continue
  ai.append(cand)
 print('[news] history filter total=',len(cands),'ai_needed=',len(ai),'reused=',reused,'exact_cache=',exact,'story_source_reuse=',story_reuse)
 return ai,stories,{'discovered_candidates':len(cands),'reused_history_candidates':reused,'ai_candidates':len(ai),'exact_cache_hits':exact,'story_source_reuse':story_reuse}

def updated_cache(old_cache,cands):
 cut=NOW-timedelta(days=CACHE_DAYS,hours=6);rows=[];seen=set()
 for x in list(cands)+list(old_cache):
  d=dtparse(x.get('published_at'))
  if not d or d<cut:continue
  u=canon_url(x.get('url'));key=u or (norm(x.get('title'))+'|'+str(x.get('published_at',''))[:10])
  if not key or key in seen:continue
  seen.add(key);rows.append({'url':x.get('url'),'title':x.get('title'),'description':str(x.get('description') or '')[:900],'domain':x.get('domain'),'published_at':x.get('published_at'),'query_category':x.get('query_category'),'discovery_source':x.get('discovery_source'),'last_seen_at':NOW.isoformat(timespec='seconds')})
  if len(rows)>=CACHE_MAX:break
 return rows

def bing_page(query,interval,first):
 r=requests.get(BING,params={'q':query,'format':'RSS','setmkt':'en-US','first':first,'qft':f'interval="{interval}"'},headers={'User-Agent':UA,'Accept':'application/rss+xml,application/xml,text/xml,*/*'},timeout=30)
 r.raise_for_status();root=ET.fromstring(r.content);out=[]
 for item in root.findall('.//item'):
  title=clean_html(item.findtext('title'));url=unwrap_bing((item.findtext('link') or '').strip());when=dtparse(item.findtext('pubDate'));desc=clean_html(item.findtext('description'));hi=hostinfo(url)
  if title and url and when and hi:out.append({'title':title,'url':url,'source':hi[1],'domain':hi[0],'published_at':when.isoformat(timespec='minutes'),'description':desc[:900],'discovery_source':'Bing News RSS'})
 return out

def google_page(query,deep):
 q=f'{query} when:{"7d" if deep else "2d"}';r=requests.get(GOOGLE,params={'q':q,'hl':'en-US','gl':'US','ceid':'US:en'},headers={'User-Agent':UA,'Accept':'application/rss+xml,application/xml,text/xml,*/*'},timeout=30)
 r.raise_for_status();root=ET.fromstring(r.content);out=[]
 for item in root.findall('.//item'):
  title=clean_html(item.findtext('title'));url=(item.findtext('link') or '').strip();when=dtparse(item.findtext('pubDate'));desc=clean_html(item.findtext('description'));src=item.find('source');src_url=(src.attrib.get('url','').strip() if src is not None else '');src_name=clean_html(src.text if src is not None else '');hi=hostinfo(src_url) or domaininfo(urlparse(src_url).hostname or '')
  if title and url and when and hi:out.append({'title':title,'url':url,'source':hi[1] or src_name,'domain':hi[0],'published_at':when.isoformat(timespec='minutes'),'description':desc[:900],'discovery_source':'Google News RSS'})
 return out

def gdelt_page(query,deep):
 r=requests.get(GDELT,params={'query':query,'mode':'ArtList','format':'json','maxrecords':75 if deep else 40,'timespan':'7d' if deep else '30h','sort':'DateDesc'},headers={'User-Agent':UA,'Accept':'application/json,*/*'},timeout=45)
 r.raise_for_status();out=[]
 for a in (r.json().get('articles',[]) or []):
  title=clean_html(a.get('title'));url=str(a.get('url') or '').strip();when=dtparse(a.get('seendate'));hi=domaininfo(a.get('domain')) or hostinfo(url)
  if title and url and when and hi:out.append({'title':title,'url':url,'source':hi[1],'domain':hi[0],'published_at':when.isoformat(timespec='minutes'),'description':'','discovery_source':'GDELT DOC API'})
 return out

def collect(mode):
 deep=mode=='deep';interval='8' if deep else '7';offsets=[1,11] if deep else [1];cut=NOW-(timedelta(days=7,hours=6) if deep else timedelta(hours=30));raw=[];discovery_counts={'Bing News RSS':0,'Google News RSS':0,'GDELT DOC API':0}
 for cat,q in QUERIES.items():
  batches=[]
  for first in offsets:
   try:batches.append(bing_page(q,interval,first))
   except Exception as e:print('[news] Bing RSS error',cat,first,e)
  try:batches.append(google_page(q,deep))
  except Exception as e:print('[news] Google News RSS error',cat,e)
  try:batches.append(gdelt_page(q,deep))
  except Exception as e:print('[news] GDELT error',cat,e)
  for batch in batches:
   for x in batch:
    d=dtparse(x['published_at'])
    if d and d>=cut:x['query_category']=cat;raw.append(x);discovery_counts[x['discovery_source']]=discovery_counts.get(x['discovery_source'],0)+1
  time.sleep(.20)
 raw.sort(key=lambda x:x['published_at'],reverse=True);res=[];seen=set();per_domain={};cap=28 if deep else 14;limit=260 if deep else 150
 for x in raw:
  u=canon_url(x['url'])
  if u in seen or any(sim(x['title'],z['title'])>.90 for z in res[-100:]) or per_domain.get(x['domain'],0)>=cap:continue
  seen.add(u);per_domain[x['domain']]=per_domain.get(x['domain'],0)+1;x['id']=f'c{len(res)+1:03d}';res.append(x)
  if len(res)>=limit:break
 print('[news] discovery raw=',discovery_counts);print('[news] trusted candidates=',len(res),'domains=',dict(sorted(per_domain.items(),key=lambda x:-x[1])));return res

def chat_json(key,mode,cands):
 compact=[{k:x[k] for k in ('id','title','source','domain','published_at','description','query_category','discovery_source')} for x in cands]
 system='''You are the analyst for an AI-bubble risk dashboard. Analyze ONLY the supplied real news candidates. Do not invent events, facts, dates, URLs or candidate IDs. Merge candidates that describe the same underlying event. Classify each retained event into exactly one of the eight allowed categories. importance_score is 0-100 for importance to AI bubble formation/unwind. bubble_risk_score is -100..100: positive means higher bubble/unwind risk, negative means stronger fundamental support/lower bubble risk. summary_zh and reason_zh must be concise Chinese. Return only events with importance_score >= 50. Output valid JSON only.'''
 prompt=f'''Allowed categories: {json.dumps(CATS,ensure_ascii=False)}
Return exactly this JSON shape: {{"stories":[{{"headline":"...","summary_zh":"...","category":"one allowed category","importance_score":80,"bubble_direction":"risk_up|risk_down|neutral","bubble_risk_score":40,"reason_zh":"...","companies":["..."],"candidate_ids":["c001","c002"]}}]}}.
Choose candidate_ids only from the supplied data; the first ID should be the best primary source. Prefer direct publisher/official URLs over aggregator wrapper URLs when duplicates exist, and prefer Reuters/Bloomberg/FT/WSJ/AP/CNBC and official primary sources.
Candidates:
{json.dumps(compact,ensure_ascii=False)}'''
 body={'model':MODEL,'messages':[{'role':'system','content':system},{'role':'user','content':prompt}],'thinking':{'type':'enabled'},'reasoning_effort':'max' if mode=='deep' else 'high','response_format':{'type':'json_object'},'max_tokens':10000 if mode=='deep' else 7000};h={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
 for i in range(2):
  try:
   r=requests.post(CHAT_API,headers=h,json=body,timeout=180);r.raise_for_status();txt=(r.json().get('choices') or [{}])[0].get('message',{}).get('content','').strip()
   if not txt:raise ValueError('empty chat completion content')
   return json.loads(txt)
  except Exception as e:
   if i==1:raise
   print('[news] retry DeepSeek analysis:',e);time.sleep(2)

def analyze(key,mode,cands):
 if not cands:return [],0
 lookup={x['id']:x for x in cands};raw=[];size=45 if mode=='deep' else 55;batches=0
 for i in range(0,len(cands),size):
  data=chat_json(key,mode,cands[i:i+size]);batches+=1;raw.extend(data.get('stories',[]) or []);print('[news] analyzed batch stories=',len(data.get('stories',[]) or []))
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
  for cid in ids[:8]:
   x=lookup[cid];skey=(x.get('domain'),canon_url(x.get('url')))
   if skey in su:continue
   su.add(skey);sources.append(source_from_candidate(x))
   if len(sources)>=4:break
  head=' '.join(str(s.get('headline') or primary['title']).split())
  out.append({'id':sid(head,primary['published_at']),'headline':head,'summary_zh':' '.join(str(s.get('summary_zh') or '').split()),'category':s['category'],'importance_score':imp,'bubble_direction':s.get('bubble_direction') if s.get('bubble_direction') in ('risk_up','risk_down','neutral') else ('risk_up' if risk>15 else 'risk_down' if risk<-15 else 'neutral'),'bubble_risk_score':risk,'reason_zh':' '.join(str(s.get('reason_zh') or '').split()),'companies':[str(x).strip() for x in s.get('companies',[]) if str(x).strip()][:8],'published_at':primary['published_at'],'sources':sources})
 return out,batches

def merge(new,existing):
 cutoff=NOW-timedelta(days=7,hours=2);pool=[]
 for s in new+existing:
  d=dtparse(s.get('published_at'))
  if not d or d<cutoff or s.get('category') not in CATS or not any(trusted_source_obj(z) for z in s.get('sources',[])):continue
  pool.append(dict(s))
 pool.sort(key=lambda s:(int(s.get('importance_score',0)),str(s.get('published_at',''))),reverse=True);res=[]
 for s in pool:
  urls={canon_url(z.get('url')) for z in s.get('sources',[]) if z.get('url')}
  m=next((x for x in res if s.get('id')==x.get('id') or sim(s.get('headline',''),x.get('headline',''))>=.62 or urls&{canon_url(z.get('url')) for z in x.get('sources',[]) if z.get('url')}),None)
  if m:
   src={canon_url(z.get('url')):z for z in m.get('sources',[])+s.get('sources',[]) if z.get('url')};m['sources']=list(src.values())[:4];m['importance_score']=max(int(m.get('importance_score',0)),int(s.get('importance_score',0)));continue
  imp=max(0,min(100,int(s.get('importance_score',0))));risk=max(-100,min(100,int(s.get('bubble_risk_score',0))));s['importance_score']=imp;s['bubble_risk_score']=risk;s['critical']=imp>=85 or (imp>=75 and abs(risk)>=60);res.append(s)
 res.sort(key=lambda s:(int(s.get('importance_score',0)),str(s.get('published_at',''))),reverse=True);return res[:120]

def save(mode,stories,cache,run_stats):
 stats={'stored_stories':len(stories),'important_7d':sum(int(s.get('importance_score',0))>=60 for s in stories),'critical_7d':sum(bool(s.get('critical')) for s in stories),**run_stats}
 p={'generated_at_sgt':NOW.isoformat(timespec='seconds'),'timezone':'Asia/Singapore','model':'deepseek-flash','model_display':'DeepSeek V4.1 Flash','scan_mode':mode,'acquisition':'Bing News RSS + Google News RSS + GDELT DOC API discovery; trusted-domain whitelist; history-first incremental filter; DeepSeek V4.1 Flash analysis only for new/materially changed candidates','discovery_sources':['Bing News RSS','Google News RSS','GDELT DOC API'],'display_window_days':7,'homepage_limits':{'critical':10,'feed':10},'policy':{'important_threshold':60,'critical_rule':'importance>=85 OR (importance>=75 AND abs(bubble_risk_score)>=60)','trusted_sources_only':True,'sort':'importance_score desc, then published_at desc','history_first_ai_filter':True},'categories':CATS,'stats':stats,'candidate_cache':cache,'stories':stories}
 OUT.write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
 key=os.getenv('DEEPSEEK_API_KEY','').strip();mode=os.getenv('NEWS_SCAN_MODE','auto').lower()
 if not key:raise SystemExit('DEEPSEEK_API_KEY missing')
 if mode=='auto':mode='deep' if NOW.hour==8 else 'incremental'
 if mode not in ('deep','incremental'):raise SystemExit('bad NEWS_SCAN_MODE')
 _,existing,cache=load_state();print('[news] mode=',mode,'now=',NOW.isoformat());cands=collect(mode)
 if mode=='deep' and not cands:raise SystemExit('Deep scan found zero trusted news candidates; refusing to publish an empty refresh')
 ai_cands,reused_existing,run_stats=history_filter(cands,existing,cache);fresh,batches=analyze(key,mode,ai_cands);run_stats['deepseek_batches']=batches;stories=merge(fresh,reused_existing)
 if mode=='deep' and not stories:raise SystemExit('Deep scan produced zero validated stories; refusing to publish an empty refresh')
 cache2=updated_cache(cache,cands);save(mode,stories,cache2,run_stats)
 print('[news] saved',len(stories),'important',sum(s.get('importance_score',0)>=60 for s in stories),'critical',sum(bool(s.get('critical')) for s in stories),'deepseek_batches',batches,'reused',run_stats.get('reused_history_candidates',0))

if __name__=='__main__':main()
