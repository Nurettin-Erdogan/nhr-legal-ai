import json,time
from datetime import date
from ingestion.yargitay.portal import YargitayPortalClient
from ingestion.yargitay.scraper import ScraperConfig as YConfig, _search_filters as y_filters
c=YargitayPortalClient(base_url="https://emsal.uyap.gov.tr/",timeout_seconds=40,max_retries=1)
out={}
for y in list(range(2026,2007,-1)):
    f=y_filters(YConfig(keyword="",chamber="",decision_date_from=date(y,1,1),decision_date_to=date(y,12,31)),page_number=1,page_size=1)
    try:
        c.begin_detailed_search(f); p=c.search_page(f); out[y]=p.records_filtered
        print(y,p.records_filtered,flush=True)
    except Exception as e:
        print(y,"HATA",type(e).__name__,str(e)[:100],flush=True); out[y]=None
        if "aptcha" in type(e).__name__.lower() or "aptcha" in str(e).lower(): break
    json.dump(out,open("data/campaign/coverage-emsal-portal.json","w"))
    time.sleep(8)
print("BITTI",flush=True)
