"""Read-only audit of the stored court decisions: missing metadata, impossible dates, damaged text, orphans and duplicates.

Eleven million rows cannot be scanned on a loaded database, so the checks run on a random page sample (TABLESAMPLE SYSTEM) of the
details table and are reported as a rate with the sample size; exact counts are used only where an index makes them cheap.

  python scripts/audit_decisions.py [--percent 0.3]
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from api.db import admin_database_connection  # noqa: E402


def run(db, label: str, sql: str, params=()) -> None:
    started = time.time()
    try:
        rows = db.execute(sql, params).fetchall()
        print(json.dumps(dict(check=label, seconds=round(time.time() - started, 1), result=[dict(r) for r in rows]),
                         ensure_ascii=False, default=str), flush=True)
    except Exception as exc:  # a check that cannot run says so; it never hides the rest
        print(json.dumps(dict(check=label, error=type(exc).__name__, detail=str(exc)[:120])), flush=True)
        db.rollback()
        db.execute('SET TRANSACTION READ ONLY')
        db.execute("SET LOCAL statement_timeout = '240s'")


def main() -> None:
    percent = float(sys.argv[sys.argv.index('--percent') + 1]) if '--percent' in sys.argv else 0.3
    with admin_database_connection() as db:
        db.execute('SET TRANSACTION READ ONLY')
        db.execute("SET LOCAL statement_timeout = '240s'")
        sample = f"court_decision_details d TABLESAMPLE SYSTEM ({percent})"
        run(db, 'sample size and missing metadata (rate in the sample)', f"""
            SELECT count(*) n,
                   count(*) FILTER (WHERE d.decision_date IS NULL) no_date,
                   count(*) FILTER (WHERE d.docket_no IS NULL OR d.docket_no = '') no_docket,
                   count(*) FILTER (WHERE d.decision_no IS NULL OR d.decision_no = '') no_decision_no,
                   count(*) FILTER (WHERE d.chamber IS NULL OR d.chamber = '') no_chamber,
                   count(*) FILTER (WHERE d.outcome IS NULL OR d.outcome = '') no_outcome
            FROM {sample} JOIN legal_sources s ON s.id = d.legal_source_id
            WHERE s.deleted_at IS NULL AND s.ingest_status = 'ready' AND d.is_current""")
        run(db, 'impossible or suspicious dates (sample)', f"""
            SELECT count(*) FILTER (WHERE d.decision_date < date '1920-01-01') before_1920,
                   count(*) FILTER (WHERE d.decision_date > current_date) in_the_future,
                   count(*) FILTER (WHERE d.docket_no ~ '^[0-9]{{4}}/' AND d.decision_date IS NOT NULL
                       AND extract(year FROM d.decision_date) < substring(d.docket_no from '^[0-9]{{4}}')::int - 1) decided_before_docket_year,
                   count(*) FILTER (WHERE d.docket_no ~ '^[0-9]{{4}}/' AND d.decision_date IS NOT NULL
                       AND extract(year FROM d.decision_date) > substring(d.docket_no from '^[0-9]{{4}}')::int + 12) decided_12y_after_docket_year
            FROM {sample} JOIN legal_sources s ON s.id = d.legal_source_id
            WHERE s.deleted_at IS NULL AND s.ingest_status = 'ready' AND d.is_current""")
        run(db, 'exact: decisions dated in the future or before 1920 (index range)', """
            SELECT count(*) FILTER (WHERE decision_date > current_date) in_the_future,
                   count(*) FILTER (WHERE decision_date < date '1920-01-01') before_1920 FROM court_decision_details""")
        run(db, 'text damage (sample of sources)', """
            SELECT count(*) n,
                   count(*) FILTER (WHERE length(raw_text) < 200) shorter_than_200,
                   count(*) FILTER (WHERE strpos(raw_text, chr(65533)) > 0) replacement_char,
                   count(*) FILTER (WHERE raw_text ~* '<(div|p|span|table|br)[ >/]') html_tags,
                   count(*) FILTER (WHERE raw_text ~ '&(nbsp|amp|quot|lt|gt);') html_entities,
                   count(*) FILTER (WHERE raw_text ~ '[A-Za-zÇĞİÖŞÜçğıöşü] [a-zçğıöşü] [a-zçğıöşü] [a-zçğıöşü] ') spaced_out_letters,
                   count(*) FILTER (WHERE content_hash IS NULL) no_hash
            FROM legal_sources TABLESAMPLE SYSTEM (0.15)
            WHERE source_type = 'court_decision' AND deleted_at IS NULL AND ingest_status = 'ready'""")
        run(db, 'sources without any chunk / chunks without a live source (sample)', """
            SELECT (SELECT count(*) FROM legal_sources s TABLESAMPLE SYSTEM (0.15) WHERE s.source_type='court_decision'
                      AND s.deleted_at IS NULL AND s.ingest_status='ready'
                      AND NOT EXISTS (SELECT 1 FROM legal_chunks c WHERE c.legal_source_id = s.id)) sources_without_chunks,
                   (SELECT count(*) FROM legal_sources s TABLESAMPLE SYSTEM (0.15) WHERE s.source_type='court_decision'
                      AND s.deleted_at IS NULL AND s.ingest_status='ready') sampled_sources""")
        run(db, 'duplicate decisions inside one chamber-year (Yargıtay 9. HD, 2019)', """
            SELECT count(*) duplicate_groups, coalesce(sum(n - 1), 0) extra_rows FROM (
              SELECT d.docket_no, d.decision_no, count(*) n FROM court_decision_details d
              JOIN legal_sources s ON s.id = d.legal_source_id
              WHERE d.court_name = 'Yargıtay' AND d.chamber = '9. Hukuk Dairesi' AND d.decision_date >= date '2019-01-01'
                AND d.decision_date < date '2020-01-01' AND s.deleted_at IS NULL AND d.is_current
              GROUP BY 1, 2 HAVING count(*) > 1) x""")
        run(db, 'same decision stored from two portals (Yargıtay + UYAP Emsal), one chamber-year', """
            SELECT count(*) pairs FROM (
              SELECT d.docket_no, d.decision_no FROM court_decision_details d JOIN legal_sources s ON s.id = d.legal_source_id
              WHERE d.chamber = '9. Hukuk Dairesi' AND d.decision_date >= date '2019-01-01' AND d.decision_date < date '2020-01-01'
                AND s.deleted_at IS NULL AND d.is_current GROUP BY 1, 2 HAVING count(DISTINCT s.ingestion_method) > 1) x""")
        run(db, 'unverified bulk records still stored (not shown in the app)', """
            SELECT ingest_status, ingestion_method, count(*) FROM legal_sources
            WHERE ingest_status <> 'ready' AND deleted_at IS NULL GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 8""")


if __name__ == '__main__':
    main()
