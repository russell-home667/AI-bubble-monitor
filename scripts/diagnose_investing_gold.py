from curl_cffi import requests

urls = [
  'https://uk.investing.com/currencies/xau-usd',
  'https://uk.investing.com/currencies/xau-usd-historical-data',
  'https://au.investing.com/currencies/xau-usd',
  'https://au.investing.com/currencies/xau-usd-historical-data',
  'https://ca.investing.com/currencies/xau-usd-historical-data',
]
for u in urls:
    print('\nGET',u)
    try:
        r=requests.get(u, impersonate='chrome', timeout=45, headers={'accept-language':'en-GB,en;q=0.9'})
        print('STATUS',r.status_code,'LEN',len(r.text),'URL',r.url)
        print(r.text[:400].replace('\n','\\n'))
    except Exception as e:
        print('ERROR',repr(e))

# Also test regional HistoricalDataAjax with a normal page session.
for host in ('uk.investing.com','au.investing.com','ca.investing.com'):
    base='https://'+host
    hist=base+'/currencies/xau-usd-historical-data'
    print('\nAJAX HOST',host)
    try:
        s=requests.Session(impersonate='chrome')
        h={'user-agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36','accept-language':'en-GB,en;q=0.9'}
        p=s.get(hist,headers=h,timeout=45)
        print('PAGE',p.status_code,len(p.text))
        payload={'curr_id':'68','smlID':'12345678','header':'XAU/USD Historical Data','st_date':'01/01/2000','end_date':'12/31/2000','interval_sec':'Daily','sort_col':'date','sort_ord':'DESC','action':'historical_data'}
        ah=dict(h); ah.update({'x-requested-with':'XMLHttpRequest','content-type':'application/x-www-form-urlencoded; charset=UTF-8','referer':hist,'origin':base})
        r=s.post(base+'/instruments/HistoricalDataAjax',headers=ah,data=payload,timeout=45)
        print('AJAX',r.status_code,len(r.text),r.text[:600].replace('\n','\\n'))
    except Exception as e:
        print('ERROR',repr(e))
