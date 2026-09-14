#!/usr/bin/env python3
import hashlib,json,os,re,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

SGT=timezone(timedelta(hours=8)); NOW=datetime.now(SGT)
OUT=Path('data/ai_bubble/news/latest.json'); OUT.parent.mkdir(parents=True,exist_ok=True)
MODEL='deepseek-flash'; API='https://api.deepseek.com/responses'
CATS=['AI Revenue / Monetization','AI CAPEX','AI Valuation / Funding','Semiconductor / GPU Demand','Data Center / Power','AI Credit / Debt','Layoffs / Project Cancellation','Macro / Regulation']
TRUST={
'reuters.com':'Reuters','bloomberg.com':'Bloomberg','ft.com':'Financial Times','wsj.com':'Wall Street Journal','cnbc.com':'CNBC','apnews.com':'Associated Press','theinformation.com':'The Information','techcrunch.com':'TechCrunch','semafor.com':'Semafor','fortune.com':'Fortune','barrons.com':"Barron's",'economist.com':'The Economist','nytimes.com':'New York Times',
'openai.com':'OpenAI','anthropic.com':'Anthropic','x.ai':'xAI','microsoft.com':'Microsoft','abc.xyz':'Alphabet','blog.google':'Google','google.com':'Google','aboutamazon.com':'Amazon','amazon.com':'Amazon','meta.com':'Meta','about.fb.com':'Meta','oracle.com':'Oracle','nvidia.com':'NVIDIA','amd.com':'AMD','broadcom.com':'Broadcom','tsmc.com':'TSMC','coreweave.com':'CoreWeave','sec.gov':'U.S. SEC','federalreserve.gov':'Federal Reserve','commerce.gov':'U.S. Commerce Department','energy.gov':'U.S. Department of Energy','whitehouse.gov':'White House','congress.gov':'U.S. Congress','europa.eu':'European Union','ec.europa.eu':'European Commission','gov.uk':'UK Government'}

SCHEMA={'type':'object','additionalProperties':False,'properties':{'stories':{'type':'array','items':{'type':'object','additionalProperties':False,'properties':{'headline':{'type':'string'},'summary_zh':{'type':'string'},'category':{'type':'string','enum':CATS},'importance_score':{'type':'integer','minimum':0,'maximum':100},'bubble_direction':{'type':'string','enum':['risk_up','risk_down','neutral']},'bubble_risk_score':{'type':'integer','minimum':-100,'maximum':100},'reason_zh':{'type':'string'},'companies':{'type':'array','items':{'type':'string'}},'published_at':{'type':'string'},'sources':{'type':'array','items':{'type':'object','additionalProperties':False,'properties':{'name':{'type':'string'},'url':{'type':'string'}},'required':['name','url']}}},'required':['headline','summary_zh','category','importance_score','bubble_direction','bubble_risk_score','reason_zh','companies','published_at','sources']}}},'required':['stories']}

def hostinfo(url):
 try:h=(urlparse(url).hostname or '').lower().removeprefix('www.')
 except:return None
 for d,n in TRUST.items():
  if h==d or h.endswith('.'+d):return d,n
 if h.endswith('.gov'):return h,'Official government source'
 return None

def dtparse(s):
 if not s:return None
 try:
  d=datetime.fromisoformat(str(s).replace('Z','+00:00'))
  if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
  return d.astimezone(SGT)
 except:return None

def norm(t):return ' '.join(re.sub(r'[^a-z0-9\u4e00-\u9fff]+',' ',str(t).lower()).split())
def sim(a,b):
 x=set(norm(a).split());y=set(norm(b).split());return len(x&y)/len(x|y) if x and y else 0
def sid(t,d):return hashlib.sha1((norm(t)+'|'+str(d)[:10]).encode()).hexdigest()[:14]
def output_text(r):
 if isinstance(r.get('output_text'),str):return r['output_text']
 parts=[]
 for o in r.get('output',[]) or []:
  for c in o.get('content',[]) or []:
   if c.get('type') in ('output_text','text') and c.get('text'):parts.append(c['text'])
 return '\n'.join(parts)

def call_search(key,mode,focus):
 deep=mode=='deep'; since=(NOW-timedelta(days=7) if deep else NOW-timedelta(hours=8)).isoformat(timespec='minutes')
 instr='''You are the news analyst for an AI-bubble risk dashboard. You MUST use web_search and ground every event in search results. Only use reliable established news organizations or official company/regulator/government websites. Never invent URLs, dates, facts, companies or amounts. Merge multiple reports of the same underlying event. Classify every event into exactly one allowed category. importance_score is 0-100 for significance to AI bubble formation/unwind. bubble_risk_score is -100..100: positive means higher bubble/unwind risk; negative means stronger fundamental support/lower bubble risk. summary_zh and reason_zh must be concise Chinese. If evidence is weak, omit the event.'''
 prompt=f'''Search the web for AI-bubble-relevant events published since {since} Singapore time.\nFocus: {focus}\nAllowed categories: {', '.join(CATS)}.\nPrioritize Reuters, Bloomberg, Financial Times, WSJ, CNBC, AP and primary official sources. Use TechCrunch/The Information/Semafor/Fortune only when useful.\nReturn only events with importance_score >= 50. Each source URL must be an exact page you found through web search.'''
 body={'model':MODEL,'instructions':instr,'input':prompt,'tools':[{'type':'web_search'}],'tool_choice':{'type':'web_search'},'reasoning':{'effort':'high' if deep else 'low'},'max_output_tokens':16000 if deep else 10000,'text':{'format':{'type':'json_schema','name':'ai_bubble_news','schema':SCHEMA}}}
 h={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
 for i in range(2):
  try:
   r=requests.post(API,headers=h,json=body,timeout=210);r.raise_for_status();return json.loads(output_text(r.json()).strip())
  except Exception as e:
   if i==1:raise
   print('[news] retry DeepSeek search:',e);time.sleep(3)

def validate(raw):
 out=[];cut=NOW-timedelta(days=7,hours=3)
 for s in raw.get('stories',[]) or []:
  if s.get('category') not in CATS:continue
  try:imp=max(0,min(100,int(s.get('importance_score',0))));risk=max(-100,min(100,int(s.get('bubble_risk_score',0))))
  except:continue
  if imp<50:continue
  src=[];seen=set()
  for z in s.get('sources',[]) or []:
   u=str(z.get('url') or '').strip();hi=hostinfo(u)
   if not hi or u in seen:continue
   seen.add(u);src.append({'name':hi[1],'domain':hi[0],'url':u})
   if len(src)>=4:break
  if not src:continue
  when=dtparse(s.get('published_at')) or NOW
  if when<cut:continue
  head=' '.join(str(s.get('headline') or '').split())
  if len(head)<10:continue
  out.append({'id':sid(head,when.isoformat()),'headline':head,'summary_zh':' '.join(str(s.get('summary_zh') or '').split()),'category':s['category'],'importance_score':imp,'bubble_direction':s.get('bubble_direction') if s.get('bubble_direction') in ('risk_up','risk_down','neutral') else 'neutral','bubble_risk_score':risk,'reason_zh':' '.join(str(s.get('reason_zh') or '').split()),'companies':[str(x).strip() for x in s.get('companies',[]) if str(x).strip()][:8],'published_at':when.isoformat(timespec='minutes'),'sources':src})
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
  m=next((x for x in res if s.get('id')==x.get('id') or sim(s.get('headline',''),x.get('headline',''))>=.63 or ({z.get('url') for z in s.get('sources',[])}&{z.get('url') for z in x.get('sources',[])})),None)
  if m:
   src={z.get('url'):z for z in m.get('sources',[])+s.get('sources',[]) if z.get('url')};m['sources']=list(src.values())[:4];m['importance_score']=max(int(m.get('importance_score',0)),int(s.get('importance_score',0)));continue
  imp=max(0,min(100,int(s.get('importance_score',0))));risk=max(-100,min(100,int(s.get('bubble_risk_score',0))));s['importance_score']=imp;s['bubble_risk_score']=risk;s['critical']=imp>=85 or (imp>=75 and abs(risk)>=60);res.append(s)
 res.sort(key=lambda s:(int(s.get('importance_score',0)),str(s.get('published_at',''))),reverse=True);return res[:120]
def save(mode,stories):
 p={'generated_at_sgt':NOW.isoformat(timespec='seconds'),'timezone':'Asia/Singapore','model':'deepseek-flash','model_display':'DeepSeek V4.1 Flash','scan_mode':mode,'acquisition':'DeepSeek V4.1 Flash server-side web_search','display_window_days':7,'homepage_limits':{'critical':10,'feed':10},'policy':{'important_threshold':60,'critical_rule':'importance>=85 OR (importance>=75 AND abs(bubble_risk_score)>=60)','trusted_sources_only':True,'sort':'importance_score desc, then published_at desc'},'categories':CATS,'stats':{'stored_stories':len(stories),'important_7d':sum(int(s.get('importance_score',0))>=60 for s in stories),'critical_7d':sum(bool(s.get('critical')) for s in stories)},'stories':stories}
 OUT.write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
 key=os.getenv('DEEPSEEK_API_KEY','').strip();mode=os.getenv('NEWS_SCAN_MODE','auto').lower()
 if not key:raise SystemExit('DEEPSEEK_API_KEY missing')
 if mode=='auto':mode='deep' if NOW.hour==8 else 'incremental'
 if mode not in ('deep','incremental'):raise SystemExit('bad NEWS_SCAN_MODE')
 print('[news] mode=',mode,'now=',NOW.isoformat())
 focuses=['AI company revenue/monetization; hyperscaler AI CAPEX; AI valuations/funding; semiconductor/GPU demand','data centers/power; AI credit/debt; layoffs/cancellations; macro policy/regulation'] if mode=='deep' else ['all eight AI bubble categories; emphasize events newly published in the last 8 hours']
 fresh=[]
 for focus in focuses:
  data=call_search(key,mode,focus); batch=validate(data);fresh.extend(batch);print('[news] validated batch=',len(batch))
 stories=merge(fresh,old());save(mode,stories);print('[news] saved',len(stories),'important',sum(s.get('importance_score',0)>=60 for s in stories))
if __name__=='__main__':main()
