"""Preview/apply: bring the stored statutes level with the official MBS list of laws.

Two things, both from the portal's own list of laws (acceptance date, Official Gazette date and number come with every entry):

1. FILL. Most stored law articles carry no Official Gazette date/number (measured 2026-10-31: 28 617 of 31 031). Where a column is
   empty it is filled from the portal list entry of the same law number; a value that is already there is never changed. The
   acceptance date has no column; it is stored once per article as `metadata.law_identity` together with the other two.
2. MISSING LAWS. A law the portal lists and the corpus lacks (measured: 24, among them 7596 of 27.10.2026 and 7589 of 31.07.2026)
   is imported from its official PDF exactly like `import_missing_official_articles.py` does it (the PDF header must carry the same
   law number, every article is the exact extract, repealed text is left out, one transaction per article, backup, proof). Lists of
   repealed provisions ("... YÜRÜRLÜKTEN KALDIRILMIŞ HÜKÜMLERİ") are not laws in force and are skipped.

Default is a read-only preview.

  python scripts/sync_laws_from_portal.py                       # preview both
  python scripts/sync_laws_from_portal.py --fill --apply        # write the Gazette fields only
  python scripts/sync_laws_from_portal.py --missing --apply     # import the missing laws only
"""

import base64
import importlib.util
import json
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psycopg.rows import tuple_row  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from api.ai.currency_note import law_identity  # noqa: E402
from api.db import admin_database_connection  # noqa: E402
from ingestion.mevzuat.models import LegislationRecord  # noqa: E402
from ingestion.mevzuat.parser import article_external_id, article_title_line  # noqa: E402
from ingestion.mevzuat.store import upsert_legislation  # noqa: E402
from ingestion.mevzuat.text_verify import fetch_official_pdf_text  # noqa: E402
from ingestion.mevzuat_bilgi_sistemi import portal as mbs  # noqa: E402
from ingestion.text import content_hash  # noqa: E402

spec = importlib.util.spec_from_file_location("import_missing", ROOT / "scripts" / "import_missing_official_articles.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

_PAUSE_SECONDS = 2.0
_BACKUPS = ROOT / ".local" / "corpus-repair-backups"
_LAW_TYPES = (1, 5)  # "Kanun" and the portal's second law series


def _date(value) -> date | None:
    try:
        day, month, year = str(value).strip().split('.')
        return date(int(year), int(month), int(day))
    except (ValueError, AttributeError):
        return None


def portal_laws(client) -> list[dict]:
    """Every entry of the portal's law lists (types 1 and 5). A number can repeat in another series, so nothing is merged here."""
    entries: list[dict] = []
    for tur in _LAW_TYPES:
        start = 0
        while True:
            body = {"draw": 1, "start": start, "length": 100, "parameters": {
                "AranacakIfade": base64.b64encode(b'').decode(), "AranacakYer": "Baslik", "TamCumle": False,
                "MevzuatTur": tur, "GenelArama": True}}
            page = json.loads(client._request(mbs.urljoin(client.base_url, mbs.SEARCH_PATH), body=body).decode('utf-8-sig'))
            entries.extend(page['data'])
            start += 100
            if start >= page['recordsTotal'] or not page['data']:
                break
            time.sleep(1.5)
    return entries


def _in_force(item: dict) -> bool:
    return 'YÜRÜRLÜKTEN KALDIRILMIŞ' not in str(item.get('mevAdi') or '').upper()


def unique_by_number(entries: list[dict]) -> dict[str, dict]:
    """{law_no: entry} only for numbers that name exactly one law in force: an ambiguous number is never guessed."""
    grouped: dict[str, list[dict]] = {}
    for item in entries:
        if _in_force(item):
            grouped.setdefault(str(item.get('mevzuatNo') or '').strip(), []).append(item)
    return {number: items[0] for number, items in grouped.items() if number and len(items) == 1}


def fill(db, laws: dict[str, dict], apply_requested: bool) -> dict:
    """Fill the empty Official Gazette columns and the per-article law identity from the portal list."""
    stored = db.execute("""SELECT DISTINCT d.law_no FROM legislation_details d JOIN legal_sources s ON s.id = d.legal_source_id
        WHERE d.legislation_type='law' AND s.deleted_at IS NULL AND d.law_no IS NOT NULL""").fetchall()
    counts: Counter = Counter()
    for row in stored:
        number = row['law_no']
        item = laws.get(number)
        if item is None:
            counts['not_in_portal_law_list'] += 1
            continue
        gazette_date, gazette_no, accepted = _date(item.get('resmiGazeteTarihi')), str(item.get('resmiGazeteSayisi') or '').strip() or None, _date(item.get('kabulTarih'))
        if gazette_date is None and gazette_no is None and accepted is None:
            counts['portal_entry_without_dates'] += 1
            continue
        identity = {'accepted': accepted.isoformat() if accepted else None, 'gazette_date': gazette_date.isoformat() if gazette_date else None,
                    'gazette_no': gazette_no, 'source': 'mbs_law_list', 'checked_at': datetime.now(timezone.utc).isoformat()}
        if not apply_requested:
            counts['laws_to_fill'] += 1
            continue
        with db.transaction():
            db.execute("SET LOCAL lock_timeout = '3s'")
            columns = db.execute("""UPDATE legislation_details d SET
                    official_gazette_date = COALESCE(d.official_gazette_date, %s),
                    official_gazette_no = CASE WHEN d.official_gazette_no IS NULL OR d.official_gazette_no = '' THEN %s ELSE d.official_gazette_no END
                FROM legal_sources s WHERE s.id = d.legal_source_id AND d.law_no = %s AND d.legislation_type = 'law' AND s.deleted_at IS NULL
                  AND (d.official_gazette_date IS NULL OR d.official_gazette_no IS NULL OR d.official_gazette_no = '')""",
                (gazette_date, gazette_no, number)).rowcount
            meta = db.execute("""UPDATE legal_sources s SET metadata = s.metadata || jsonb_build_object('law_identity', %s::jsonb)
                FROM legislation_details d WHERE d.legal_source_id = s.id AND d.law_no = %s AND d.legislation_type = 'law'
                  AND s.deleted_at IS NULL AND NOT jsonb_exists(s.metadata, 'law_identity')""", (Jsonb(identity), number)).rowcount
        counts['laws_filled'] += 1
        counts['detail_rows_updated'] += columns
        counts['source_rows_updated'] += meta
    return dict(counts)


def import_law(client, db, item: dict, apply_requested: bool, backup: Path, now: datetime) -> dict:
    number = str(item['mevzuatNo']).strip()
    document = client.search_law(number, law_name=item.get('mevAdi'))
    if not document.pdf_url:
        return dict(law=number, skipped='no_official_pdf')
    full = fetch_official_pdf_text(document.pdf_url, timeout_seconds=60)
    if not law_identity(full, number):
        return dict(law=number, skipped='pdf_header_is_another_law')
    entry = dict(url=document.pdf_url, name=document.law_name, have=set())
    found, document_hash, skipped = base.missing_articles(number, entry)
    line = dict(law=number, name=document.law_name[:50], articles=len(found), skipped=dict(skipped))
    if not apply_requested or not found:
        return line
    gazette_date, accepted = _date(item.get('resmiGazeteTarihi')), _date(item.get('kabulTarih'))
    gazette_no = str(item.get('resmiGazeteSayisi') or '').strip() or None
    for article in found:
        proof = {'verified': True, 'url': document.pdf_url, 'article_no': article['article'], 'checked_at': now.isoformat(),
                 'article_hash': article['hash'], 'document_text_hash': document_hash, 'method': 'exact_official_article_extraction'}
        record = LegislationRecord(
            record_type='legislation', legislation_type='law', law_name=document.law_name, law_no=number,
            article_no=article['article'], article_title=None, title=article_title_line(document.law_name, article['article'], None),
            raw_text=article['body'], external_id=article_external_id(number, article['article'], portal_type='KANUN'),
            content_hash=article['hash'], source_url=document.pdf_url, official_gazette_no=gazette_no,
            official_gazette_date=gazette_date, scraped_at=now,
            metadata={'verified_against_mbs': True, 'mbs_text_verification': proof, 'source': 'official_mbs_pdf', 'mevzuat_tur': 'KANUN',
                      'import': 'missing_law_v1', 'law_identity': {'accepted': accepted.isoformat() if accepted else None,
                      'gazette_date': gazette_date.isoformat() if gazette_date else None, 'gazette_no': gazette_no,
                      'source': 'mbs_law_list'}})
        original = db.row_factory
        try:
            db.row_factory = tuple_row
            with db.transaction():
                source_id = upsert_legislation(db, record).legal_source_id
                db.execute("UPDATE legal_sources SET ingestion_method='official_mbs_pdf_http', ingest_status='ready', "
                           "metadata = metadata || %s, last_verified_at = NOW() WHERE id=%s",
                           (Jsonb({'verified_against_mbs': True, 'mbs_text_verification': proof}), source_id))
        finally:
            db.row_factory = original
        with backup.open('a', encoding='utf-8') as file:
            file.write(json.dumps(dict(law=number, article=article['article'], source_id=str(source_id), content_hash=article['hash']),
                                  ensure_ascii=False) + chr(10))
    line['inserted'] = len(found)
    return line


def stored_series(db) -> set[tuple[str, str]]:
    """{(law_no, series)} of the stored laws, read from each law's own official link (".../1.5.4857.pdf" -> type 1, series 5)."""
    import re
    found: set[tuple[str, str]] = set()
    for row in db.execute("SELECT DISTINCT d.law_no, s.source_url FROM legislation_details d JOIN legal_sources s ON s.id=d.legal_source_id "
                          "WHERE d.legislation_type IN ('law', 'constitution') AND s.deleted_at IS NULL AND d.law_no IS NOT NULL").fetchall():
        match = re.search(r'MevzuatMetin/\d+\.(\d+)\.\d+\.', row['source_url'] or '', re.I) or re.search(r'MevzuatTertip=(\d+)', row['source_url'] or '', re.I)
        found.add((row['law_no'], match.group(1) if match else ''))
    return found


def main():
    args = sys.argv[1:]
    apply_requested = '--apply' in args
    do_fill = '--fill' in args or '--missing' not in args
    do_missing = '--missing' in args or '--fill' not in args
    now = datetime.now(timezone.utc)
    _BACKUPS.mkdir(parents=True, exist_ok=True)
    backup = _BACKUPS / ('missing-laws-' + now.strftime('%Y%m%dT%H%M%S') + '.jsonl')
    client = mbs.MbsClient(timeout_seconds=40, max_retries=2)
    entries = portal_laws(client)
    unique = unique_by_number(entries)
    print(json.dumps(dict(portal_entries=len(entries), unambiguous_laws=len(unique), fill=do_fill, missing=do_missing,
                          apply=apply_requested)), flush=True)
    if do_fill:
        with admin_database_connection() as db:
            db.execute("SET LOCAL statement_timeout = '280s'")
            print(json.dumps(dict(fill=fill(db, unique, apply_requested)), ensure_ascii=False), flush=True)
    if do_missing:
        with admin_database_connection() as db:
            have = stored_series(db)
        have_numbers = {number for number, _ in have}
        absent = [item for item in entries if int(item.get('mevzuatTur') or 0) == 1 and _in_force(item)
                  and (str(item['mevzuatNo']).strip(), str(item.get('mevzuatTertip'))) not in have
                  and str(item['mevzuatNo']).strip() not in have_numbers]
        print(json.dumps(dict(missing_laws=len(absent), numbers=[str(i['mevzuatNo']) for i in absent])), flush=True)
        for item in absent:
            try:
                with admin_database_connection() as db:
                    db.execute("SET LOCAL statement_timeout = '120s'")
                    print(json.dumps(import_law(client, db, item, apply_requested, backup, now), ensure_ascii=False), flush=True)
            except Exception as exc:  # one law failing must not stop the others
                print(json.dumps(dict(law=str(item.get('mevzuatNo')), error=type(exc).__name__, detail=str(exc)[:140]), ensure_ascii=False), flush=True)
            time.sleep(_PAUSE_SECONDS)


if __name__ == '__main__':
    main()
