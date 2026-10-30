"""Sunucu tarafı mevzuat boşluk taraması (yalnız standart kütüphane).

  python3 law_gap_node.py <db_laws.json> <shard> <shards> <çıktı.json>

`db_laws.json` (PC'nin veritabanından): mevzuat_id → {law_no, name, have: [madde no]}. Her kanun için Bedesten `mevzuatMaddeTree`
okunur; portalda olup veritabanında olmayan maddeler (madde no + madde id) çıktıya yazılır. PC portala istek atmaz.
"""
import json
import sys
import time
import urllib.request

BASE = "https://bedesten.adalet.gov.tr/mevzuat/mevzuatMaddeTree"
HEADERS = {"Accept": "application/json", "Content-Type": "application/json; charset=utf-8", "AdaletApplicationName": "UyapMevzuat",
           "Origin": "https://mevzuat.adalet.gov.tr", "Referer": "https://mevzuat.adalet.gov.tr/", "User-Agent": "nhr-legal-ai/0.1 (official-public-source-ingestion)"}


def walk(nodes, out):
    for node in nodes or []:
        if isinstance(node, dict):
            no, mid = node.get("maddeNo"), node.get("maddeId")
            if no and mid:
                out.append((str(no).strip(), str(mid).strip()))
            walk(node.get("children"), out)


def tree(mevzuat_id):
    body = json.dumps({"data": {"mevzuatId": mevzuat_id}, "applicationName": "UyapMevzuat"}).encode()
    for attempt in range(4):
        try:
            req = urllib.request.Request(BASE, data=body, headers=HEADERS, method="POST")
            with urllib.request.urlopen(req, timeout=40) as resp:
                data = json.loads(resp.read().decode("utf-8-sig")).get("data") or {}
            out = []
            walk(data.get("children") if "children" in data else data, out) if isinstance(data, dict) else walk(data, out)
            return out
        except Exception as exc:  # noqa: BLE001
            if "429" in str(exc):
                time.sleep(30 * (attempt + 1))
            else:
                time.sleep(3 * (attempt + 1))
            last = str(exc)[:100]
    raise RuntimeError(last)


def main():
    laws = json.load(open(sys.argv[1], encoding="utf-8"))
    shard, shards = int(sys.argv[2]), int(sys.argv[3])
    ids = sorted(laws)[shard::shards]
    result, errors = {}, {}
    for index, mid in enumerate(ids):
        info = laws[mid]
        try:
            arts = tree(mid)
        except Exception as exc:  # noqa: BLE001
            errors[mid] = str(exc)
            continue
        have = set(info["have"])
        missing = [[no, madde] for no, madde in arts if no not in have]
        result[mid] = {"law_no": info["law_no"], "name": info["name"][:80], "portal": len(arts), "db": len(have), "missing": missing}
        if index % 50 == 0:
            json.dump({"result": result, "errors": errors, "done": index + 1, "total": len(ids)}, open(sys.argv[4], "w", encoding="utf-8"), ensure_ascii=False)
        time.sleep(0.7)
    json.dump({"result": result, "errors": errors, "done": len(ids), "total": len(ids), "finished": True}, open(sys.argv[4], "w", encoding="utf-8"), ensure_ascii=False)


main()
