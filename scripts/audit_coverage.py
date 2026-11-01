"""Read-only coverage audit: what the official portals have that the corpus does not, and which stored fields are still empty.

Complements `audit_data_final.py` (integrity: chunks, identities, proofs). Every check runs on its own connection with a time limit and
prints one JSON line, so one slow check never hides the others.

  python scripts/audit_coverage.py            # all checks
  python scripts/audit_coverage.py --only portal
"""

import argparse
import base64
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from api.db import admin_database_connection  # noqa: E402

CHECKS: dict = {}
_LINK = re.compile(r"MevzuatNo=(\d+)&MevzuatTur=(\d+)&MevzuatTertip=(\d+)", re.I)
_PDF = re.compile(r"MevzuatMetin/(\d+)\.(\d+)\.(\d+)\.", re.I)


def check(name):
    def wrap(fn):
        CHECKS[name] = fn
        return fn
    return wrap


def rows(db, sql, params=()):
    return [dict(r) for r in db.execute(sql, params).fetchall()]


@check("portal")
def portal(db):
    """Portal documents by type against the stored ones (number, type, series read from each stored link)."""
    from ingestion.mevzuat_bilgi_sistemi import portal as mbs
    client = mbs.MbsClient(timeout_seconds=40, max_retries=2)
    stored: dict[int, set[tuple[str, str]]] = {}
    for row in rows(db, "SELECT DISTINCT s.source_url FROM legal_sources s WHERE s.source_type='legislation' AND s.deleted_at IS NULL"):
        url = row['source_url'] or ''
        match = _LINK.search(url)
        if match:
            stored.setdefault(int(match.group(2)), set()).add((match.group(1), match.group(3)))
            continue
        match = _PDF.search(url)
        if match:
            stored.setdefault(int(match.group(1)), set()).add((match.group(3), match.group(2)))
    names = {1: 'Kanun', 2: 'Tüzük', 3: 'Yönetmelik (7+8 dahil)', 4: 'KHK', 5: 'Mülga/diğer kanun', 7: 'Kurum yönetmeliği',
             8: 'Üniversite yönetmeliği', 9: 'Tebliğ', 19: 'CB Kararnamesi', 20: 'CB Kararı', 21: 'CB Yönetmeliği',
             22: 'CB Genelgesi', 23: 'CB Kararname Fihristi'}
    out = {}
    for tur, name in names.items():
        if tur == 3:
            continue  # the "Yönetmelik" list is the union of 3, 7 and 8
        body = {"draw": 1, "start": 0, "length": 1, "parameters": {"AranacakIfade": base64.b64encode(b'').decode(),
                "AranacakYer": "Baslik", "TamCumle": False, "MevzuatTur": tur, "GenelArama": True}}
        total = json.loads(client._request(mbs.urljoin(client.base_url, mbs.SEARCH_PATH), body=body).decode('utf-8-sig'))['recordsTotal']
        out[f'{tur} {name}'] = dict(portalda=total, korpusta=len(stored.get(tur, ())), eksik=max(total - len(stored.get(tur, ())), 0))
        time.sleep(1.2)
    return out


@check("decisions_by_year")
def decisions_by_year(db):
    """Stored decisions per court and decade, to see holes in time (index range scans on the decision date)."""
    result = {}
    for court in ('Yargıtay', 'Danıştay', 'Anayasa Mahkemesi'):
        counts = rows(db, """SELECT (extract(year FROM decision_date)::int / 5) * 5 AS bastan, count(*) n FROM court_decision_details
                             WHERE court_name = %s AND decision_date IS NOT NULL GROUP BY 1 ORDER BY 1""", (court,))
        result[court] = {str(r['bastan']): r['n'] for r in counts}
    return result


@check("pending_and_unverified")
def pending(db):
    return rows(db, """SELECT source_type, ingest_status, ingestion_method, count(*) n FROM legal_sources
                       WHERE deleted_at IS NULL AND ingest_status <> 'ready' GROUP BY 1, 2, 3 ORDER BY 4 DESC""")


@check("legislation_fields")
def legislation_fields(db):
    return rows(db, """SELECT d.legislation_type AS tur, count(*) madde,
        count(*) FILTER (WHERE d.official_gazette_date IS NULL) rg_tarihi_yok,
        count(*) FILTER (WHERE d.official_gazette_no IS NULL OR d.official_gazette_no = '') rg_sayisi_yok,
        count(*) FILTER (WHERE d.article_title IS NULL OR d.article_title LIKE 'Madde No:%%') baslik_yok_ya_da_yer_tutucu,
        count(*) FILTER (WHERE NOT jsonb_exists(s.metadata, 'law_identity')) kunye_metadata_yok
        FROM legislation_details d JOIN legal_sources s ON s.id = d.legal_source_id
        WHERE s.is_current AND s.deleted_at IS NULL AND s.ingest_status = 'ready' GROUP BY 1 ORDER BY 2 DESC""")


@check("embeddings")
def embeddings(db):
    """Embedded share of the chunks per source type (the embedding job belongs to the user: reported, never touched)."""
    return rows(db, """SELECT s.source_type, count(*) parca, count(*) FILTER (WHERE c.embedding IS NULL) gomme_yok
                       FROM legal_chunks c TABLESAMPLE SYSTEM (0.4) JOIN legal_sources s ON s.id = c.legal_source_id
                       WHERE s.deleted_at IS NULL GROUP BY 1 ORDER BY 2 DESC""")


@check("text_differences_left")
def text_differences(db):
    path = ROOT / ".local" / "article_text_real_missing.jsonl"
    if not path.exists():
        return {"dosya": "yok"}
    counts = Counter(json.loads(line)['verdict'] for line in path.read_text(encoding='utf-8').splitlines() if line.strip())
    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--only')
    args = parser.parse_args()
    for name, fn in CHECKS.items():
        if args.only and name != args.only:
            continue
        started = time.time()
        try:
            with admin_database_connection() as db:
                db.execute('SET TRANSACTION READ ONLY')
                db.execute("SET LOCAL statement_timeout = '280s'")
                result = fn(db)
            print(json.dumps(dict(check=name, seconds=round(time.time() - started, 1), result=result), ensure_ascii=False, default=str), flush=True)
        except Exception as exc:  # one failing check never hides the rest
            print(json.dumps(dict(check=name, error=type(exc).__name__, detail=str(exc)[:140])), flush=True)


if __name__ == '__main__':
    main()
