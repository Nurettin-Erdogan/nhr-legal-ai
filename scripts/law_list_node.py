"""Sunucu tarafı: Bedesten'deki kanun/KHK/CB kararnamesi listesini (mevzuatNo, mevzuatId, ad) çıkarır (yalnız standart kütüphane)."""
import json
import sys
import time
import urllib.request
URL = "https://bedesten.adalet.gov.tr/mevzuat/searchDocuments"
H = {"Accept": "application/json", "Content-Type": "application/json; charset=utf-8", "AdaletApplicationName": "UyapMevzuat",
     "Origin": "https://mevzuat.adalet.gov.tr", "Referer": "https://mevzuat.adalet.gov.tr/", "User-Agent": "nhr-legal-ai/0.1 (official-public-source-ingestion)"}
out = {}
for tur in sys.argv[2:]:
    page = 1
    while True:
        body = json.dumps({"data": {"pageSize": 20, "pageNumber": page, "mevzuatTurList": [tur], "sortFields": ["RESMI_GAZETE_TARIHI"], "sortDirection": "desc"},
                           "applicationName": "UyapMevzuat", "paging": True}).encode()
        for attempt in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(URL, data=body, headers=H, method="POST"), timeout=40) as r:
                    data = json.loads(r.read().decode("utf-8-sig"))["data"]
                break
            except Exception:
                time.sleep(5 * (attempt + 1))
        else:
            break
        if not isinstance(data, dict):
            break
        rows = data.get("mevzuatList") or []
        for row in rows:
            out[str(row.get("mevzuatId"))] = {"no": row.get("mevzuatNo"), "ad": row.get("mevzuatAdi"), "tur": tur, "tertip": row.get("mevzuatTertip")}
        if not rows or page * 20 >= int(data.get("total") or 0):
            break
        page += 1
        time.sleep(0.7)
    json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False)
json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False)
