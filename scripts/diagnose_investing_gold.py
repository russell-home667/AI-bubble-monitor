from datetime import date
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
payload={'curr_id':'68','smlID':'12345678','header':'XAU/USD Historical Data','st_date':'01/01/1970','end_date':date.today().strftime('%m/%d/%Y'),'interval_sec':'Daily','sort_col':'date','sort_ord':'DESC','action':'historical_data'}
r=s.post(base+'/instruments/HistoricalDataAjax',headers=h,data=payload,timeout=120)
print('STATUS',r.status_code,'LEN',len(r.text))
soup=BeautifulSoup(r.text,'html.parser')
rows=[]
for tr in soup.select('table#curr_table tbody tr'):
    td=tr.find_all('td')
    if len(td)>=2:
        rows.append((td[0].get_text(' ',strip=True),td[1].get_text(' ',strip=True)))
print('ROW_COUNT',len(rows))
print('FIRST_HTML_ROW',rows[0] if rows else None)
print('LAST_HTML_ROW',rows[-1] if rows else None)
