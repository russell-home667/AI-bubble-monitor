import json
from urllib.parse import urlencode
from curl_cffi import requests

urls = [
  'https://r.jina.ai/http://www.investing.com/currencies/xau-usd',
  'https://r.jina.ai/http://www.investing.com/currencies/xau-usd-historical-data',
  'https://r.jina.ai/http://www.investing.com/currencies/xau-usd-historical-data?st_date=01%2F01%2F2000&end_date=12%2F31%2F2000',
  'https://r.jina.ai/http://api.investing.com/api/financialdata/historical/68?' + urlencode({'start-date':'2000-01-01','end-date':'2000-12-31','time-frame':'Daily','add-missing-rows':'false'}),
  'https://r.jina.ai/http://api.investing.com/api/financialdata/68/historical/chart?period=MAX&interval=P1D&pointscount=120',
]
for u in urls:
    print('\nURL', u)
    try:
        r=requests.get(u, impersonate='chrome', timeout=60)
        print('STATUS',r.status_code,'LEN',len(r.text))
        print(r.text[:1500].replace('\n','\\n'))
    except Exception as e:
        print('ERROR',repr(e))
