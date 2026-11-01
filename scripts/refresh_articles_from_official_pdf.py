"""Preview/apply: bring chosen stored articles (any document type) level with their official PDF, as a NEW revision.

For articles that the triage proved to lack an amended paragraph (`.local/article_text_real_missing.jsonl`, e.g. a regulation article
whose "(2) (Ek:RG-25/4/2026-...)" paragraph is missing). Same safety rules as `refresh_official_law.py`, which handles laws only:

  * the official text is the PDF extract of that article with the page footnotes removed (`strip_footnotes`), nothing else changed;
  * the stored text must be (almost) contained in it (at most 5 % of the stored text may be absent from the official one), so a refresh
    only ADDS official text; an article that would lose stored text is refused;
  * a new revision is written through the ingestion store (same `external_id`, new content hash); the old row stays as history;
  * preview by default; every applied row is backed up first; one transaction per article.

  python scripts/refresh_articles_from_official_pdf.py --ids ID1,ID2 [--apply]
"""

import importlib.util
import json
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psycopg.rows import tuple_row  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from api.db import admin_database_connection  # noqa: E402
from ingestion.mevzuat.models import LegislationRecord  # noqa: E402
from ingestion.mevzuat.store import upsert_legislation  # noqa: E402
from ingestion.mevzuat.text_verify import _comparison_key, fetch_official_pdf_text  # noqa: E402
from ingestion.text import content_hash  # noqa: E402


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


refresh = _load("refresh_official_law", "refresh_official_law.py")
triage = _load("triage_text_differences", "triage_text_differences.py")
_BACKUPS = ROOT / ".local" / "corpus-repair-backups"


def plan(db, source_id: str, pdf_cache: dict) -> dict:
    row = db.execute("""SELECT to_jsonb(s) AS source, to_jsonb(d) AS details FROM legal_sources s
        JOIN legislation_details d ON d.legal_source_id = s.id WHERE s.id = %s AND s.is_current AND s.deleted_at IS NULL""",
                     (source_id,)).fetchone()
    if not row:
        return dict(id=source_id, status='not_current_or_missing')
    source, detail = row['source'], row['details']
    proof = (source.get('metadata') or {}).get('mbs_text_verification') or {}
    triage_row = next((r for r in _triage_rows() if r['id'] == source_id), None)
    if not triage_row:
        return dict(id=source_id, status='not_in_triage')
    pdf = triage_row['pdf']
    if pdf not in pdf_cache:
        pdf_cache[pdf] = fetch_official_pdf_text('https://www.mevzuat.gov.tr/MevzuatMetin/' + pdf, timeout_seconds=60)
    full = pdf_cache[pdf]
    official = triage.strip_footnotes(refresh.official_article(full, detail['article_no']))
    stored_key, official_key = _comparison_key(triage.strip_footnotes(triage.without_caption(source['raw_text'] or ''))), _comparison_key(
        triage.without_caption(official))
    matched = sum(block.size for block in SequenceMatcher(None, stored_key, official_key, autojunk=False).get_matching_blocks())
    lost = 1 - matched / max(len(stored_key), 1)
    return dict(id=source_id, status='refreshable' if lost <= 0.05 and len(official_key) > len(stored_key) else 'refused_would_lose_text',
                pdf=pdf, article=detail['article_no'], law_no=detail['law_no'], type=detail['legislation_type'],
                stored_chars=len(source['raw_text'] or ''), official_chars=len(official), stored_text_lost=round(lost, 3),
                official_text=official, official_hash=content_hash(official), document_hash=content_hash(full),
                source=source, detail=detail, proof_url=proof.get('url'))


def _triage_rows() -> list[dict]:
    path = ROOT / ".local" / "article_text_real_missing.jsonl"
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def apply_plan(db, item: dict, now: datetime) -> str:
    source, detail = item['source'], item['detail']
    proof = {'verified': True, 'url': 'https://www.mevzuat.gov.tr/MevzuatMetin/' + item['pdf'], 'article_no': item['article'],
             'checked_at': now.isoformat(), 'article_hash': item['official_hash'], 'document_text_hash': item['document_hash'],
             'method': 'official_pdf_article_extraction_footnotes_removed'}
    metadata = dict(verified_against_mbs=True, mbs_text_verification=proof,
                    corpus_refresh=dict(reason='amended_paragraph_missing', previous_source_id=source['id']))
    record = LegislationRecord(record_type='legislation', legislation_type=detail['legislation_type'], law_name=detail['law_name'],
                               law_no=detail['law_no'], article_no=detail['article_no'], article_title=detail['article_title'],
                               title=source['title'], raw_text=item['official_text'], external_id=source['external_id'],
                               content_hash=item['official_hash'], source_url=source['source_url'], scraped_at=now, metadata=metadata)
    original = db.row_factory
    try:
        db.row_factory = tuple_row
        with db.transaction():
            result = upsert_legislation(db, record, max_chunk_chars=16000)
            new_id = result.legal_source_id
            db.execute("UPDATE legal_sources SET metadata = metadata || %s, ingest_status='ready', "
                       "ingestion_method='official_mbs_pdf_http', last_verified_at=NOW() WHERE id=%s", (Jsonb(metadata), new_id))
    finally:
        db.row_factory = original
    return str(new_id)


def main() -> None:
    args = sys.argv[1:]
    apply_requested = '--apply' in args
    ids = args[args.index('--ids') + 1].split(',')
    now = datetime.now(timezone.utc)
    pdf_cache: dict = {}
    with admin_database_connection() as db:
        db.execute("SET LOCAL statement_timeout = '120s'")
        plans = [plan(db, source_id, pdf_cache) for source_id in ids]
    for item in plans:
        print(json.dumps({k: v for k, v in item.items() if k not in ('official_text', 'source', 'detail')}, ensure_ascii=False), flush=True)
    refreshable = [item for item in plans if item['status'] == 'refreshable']
    if not apply_requested or not refreshable:
        return
    _BACKUPS.mkdir(parents=True, exist_ok=True)
    backup = _BACKUPS / ('official-refresh-other-' + now.strftime('%Y%m%dT%H%M%S') + '.json')
    backup.write_text(json.dumps([dict(id=i['id'], source=i['source'], detail=i['detail']) for i in refreshable],
                                 ensure_ascii=False, default=str), encoding='utf-8')
    for item in refreshable:
        with admin_database_connection() as db:
            db.execute("SET LOCAL statement_timeout = '120s'")
            print(json.dumps(dict(refreshed=item['id'], new_source_id=apply_plan(db, item, now), article=item['article']),
                             ensure_ascii=False), flush=True)
    print('backup:', backup)


if __name__ == '__main__':
    main()
