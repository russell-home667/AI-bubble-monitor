from bs4 import BeautifulSoup
from curl_cffi import requests

host='uk.investing.com'
base='https://'+host
hist=base+'/currencies/xau-usd-historical-data'
s=requests.Session(impersonate='chrome')
h={
    'user-agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36',
    'accept-language':'en-GB,en;q=0.9',
    'x-requested-with':'XMLHttpRequest',
    'content-type':'application/x-www-form-urlencoded; charset=UTF-8',
    'referer':hist,
    'origin':base,
}
for start,end in [('01/01/1970','12/31/1971'),('01/01/1975','12/31/1976'),('01/01/1980','12/31/1981'),('01/01/1985','12/31/1986')]:
    payload={'curr_id':'68','smlID':'12345678','header':'XAU/USD Historical Data','st_date':start,'end_date':end,'interval_sec':'Daily','sort_col':'date','sort_ord':'DESC','action':'historical_data'}
    r=s.post(base+'/instruments/HistoricalDataAjax',headers=h,data=payload,timeout=60)
    soup=BeautifulSoup(r.text,'html.parser')
    rows=[]
    for tr in soup.select('table#curr_table tbody tr'):
        td=tr.find_all('td')
        if len(td)>=2:
            rows.append((td[0].get_text(' ',strip=True),td[1].get_text(' ',strip=True)))
    print(start,end,'STATUS',r.status_code,'ROWS',len(rows),'NEWEST',rows[0] if rows else None,'OLDEST',rows[-1] if rows else None)
