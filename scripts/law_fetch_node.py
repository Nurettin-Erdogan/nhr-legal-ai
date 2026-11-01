"""Sunucu tarafı: eksik mevzuat maddelerinin metnini Bedesten'den çeker (yalnız standart kütüphane).

  python3 law_fetch_node.py <gaps.json> <shard> <shards> <çıktı.jsonl>

`gaps.json`: mevzuat_id → {law_no, name, missing: [[madde_no, madde_id], ...]}. Her satır: {mevzuat_id, law_no, article_no, madde_id, html_b64}.
PC portala istek atmaz; çıktıyı toplayıp kendi veritabanına aktarır.
"""
import json
import sys
import time
import urllib.request

URL = "https://bedesten.adalet.gov.tr/mevzuat/getDocumentContent"
H = {"Accept": "application/json", "Content-Type": "application/json; charset=utf-8", "AdaletApplicationName": "UyapMevzuat",
     "Origin": "https://mevzuat.adalet.gov.tr", "Referer": "https://mevzuat.adalet.gov.tr/", "User-Agent": "nhr-legal-ai/0.1 (official-public-source-ingestion)"}

gaps = json.load(open(sys.argv[1], encoding="utf-8"))["missing"]
shard, shards = int(sys.argv[2]), int(sys.argv[3])
jobs = [(mid, info["law_no"], no, madde) for mid, info in sorted(gaps.items()) for no, madde in info["missing"]][shard::shards]
errors = 0
with open(sys.argv[4], "w", encoding="utf-8") as out:
    for mid, law_no, no, madde in jobs:
        body = json.dumps({"data": {"documentType": "MADDE", "id": madde}, "applicationName": "UyapMevzuat"}).encode()
        for attempt in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(URL, data=body, headers=H, method="POST"), timeout=40) as r:
                    data = json.loads(r.read().decode("utf-8-sig")).get("data") or {}
                if data.get("content"):
                    out.write(json.dumps({"mevzuat_id": mid, "law_no": law_no, "article_no": no, "madde_id": madde, "html_b64": data["content"],
                                          "mime": data.get("mimeType")}, ensure_ascii=False) + "\n")
                    out.flush()
                else:
                    errors += 1
                break
            except Exception:  # noqa: BLE001
                time.sleep(4 * (attempt + 1))
        else:
            errors += 1
        time.sleep(0.7)
    out.write(json.dumps({"finished": True, "errors": errors, "jobs": len(jobs)}) + "\n")
