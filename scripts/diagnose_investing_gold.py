from curl_cffi import requests

for host in ('uk.investing.com','au.investing.com','ca.investing.com'):
    base='https://'+host
    hist=base+'/currencies/xau-usd-historical-data'
    print('\nDIRECT AJAX HOST',host)
    try:
        s=requests.Session(impersonate='chrome')
        h={
            'user-agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36',
            'accept-language':'en-GB,en;q=0.9',
            'x-requested-with':'XMLHttpRequest',
            'content-type':'application/x-www-form-urlencoded; charset=UTF-8',
            'referer':hist,
            'origin':base,
        }
        payload={'curr_id':'68','smlID':'12345678','header':'XAU/USD Historical Data','st_date':'01/01/2000','end_date':'12/31/2000','interval_sec':'Daily','sort_col':'date','sort_ord':'DESC','action':'historical_data'}
        r=s.post(base+'/instruments/HistoricalDataAjax',headers=h,data=payload,timeout=60)
        print('DIRECT',r.status_code,len(r.text),r.text[:500].replace('\n','\\n'))
    except Exception as e:
        print('ERROR',repr(e))
