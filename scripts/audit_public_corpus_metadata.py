"""Exact read-only public source inventory; no generation or portal traffic.

Verification metadata is evidence of provenance, not proof of legal accuracy.
No private tables, writes, or full-text/embedding export are performed.
"""
from pathlib import Path
import json
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import database_connection


def audit():
    started = monotonic()
    with database_connection() as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        connection.execute("SET LOCAL statement_timeout = '0'")
        connection.execute("SET LOCAL lock_timeout = '2s'")
        rows = connection.execute("""
            SELECT source_type, ingest_status, ingestion_method,
                   count(*) AS records,
                   count(*) FILTER (WHERE is_current) AS current_records,
                   count(*) FILTER (WHERE source_url IS NULL OR btrim(source_url) = '') AS missing_url,
                   count(*) FILTER (WHERE content_hash IS NULL OR btrim(content_hash) = '') AS missing_hash,
                   count(*) FILTER (WHERE metadata->>'verify_status' = 'mismatch') AS recorded_mismatch,
                   count(*) FILTER (WHERE metadata->>'official_verified' = 'true') AS official_verified_flag,
                   count(*) FILTER (WHERE metadata->'mbs_text_verification'->>'verified' = 'true'
                                       OR metadata->>'verified_text_against_mbs' = 'true') AS mbs_text_proof_flag,
                   count(*) FILTER (WHERE metadata->>'verified_against_mbs' = 'true'
                                       OR metadata->>'verified_against_gazette' = 'true') AS legislation_portal_flag
            FROM legal_sources
            WHERE deleted_at IS NULL AND source_type IN ('legislation', 'court_decision', 'other')
            GROUP BY source_type, ingest_status, ingestion_method
            ORDER BY source_type, ingest_status, ingestion_method
        """).fetchall()
    return dict(scope='All nondeleted public legal_sources metadata; no private data',
                read_only=True, seconds=round(monotonic()-started, 2), groups=rows,
                caveat='Flags are stored provenance only; this is not a fresh official text comparison.')


if __name__ == '__main__':
    print('Public metadata scan started (read-only)', flush=True)
    print(json.dumps(audit(), ensure_ascii=False, default=str), flush=True)
