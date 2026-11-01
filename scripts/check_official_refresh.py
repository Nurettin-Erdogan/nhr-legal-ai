"""Read-only post-refresh integrity counts, public corpus only."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import database_connection

with database_connection() as db:
    db.execute('SET TRANSACTION READ ONLY')
    rows = db.execute("""SELECT d.law_no, count(*) AS current_records,
        count(*) FILTER (WHERE s.ingest_status='ready'
            AND s.metadata->'mbs_text_verification'->>'article_hash'=s.content_hash) AS exact_pdf_proofs,
        count(*) FILTER (WHERE s.metadata->'corpus_refresh' IS NOT NULL) AS refreshed
        FROM legal_sources s JOIN legislation_details d ON d.legal_source_id=s.id
        WHERE s.source_type='legislation' AND s.is_current AND s.deleted_at IS NULL
          AND d.legislation_type='law' AND d.law_no=ANY(%s)
        GROUP BY d.law_no ORDER BY d.law_no""", (['6325','6098','4857','6361','4458','1512'],)).fetchall()
    duplicates = db.execute("""SELECT count(*) AS groups FROM (
        SELECT d.legislation_identity_id FROM legislation_details d
        JOIN legal_sources s ON s.id=d.legal_source_id
        WHERE s.is_current AND s.deleted_at IS NULL GROUP BY d.legislation_identity_id HAVING count(*)>1
        ) duplicates""").fetchone()
    bad = db.execute("""SELECT count(*) AS visible_bad_identity FROM legal_sources
        WHERE source_type='legislation' AND metadata->>'corpus_identity_error'='true' AND ingest_status='ready'
          AND deleted_at IS NULL""").fetchone()
    print(json.dumps(dict(laws=rows, duplicate_current_identities=duplicates['groups'],
                         ready_flagged_identity_errors=bad['visible_bad_identity']), ensure_ascii=False))
