"""Preview/apply PDF-layout-backed caption proofs for every current statute article that the answer writer refuses as cut off.

A statute article's stored text often ends with the NEXT section's heading (the official PDF extract runs up to the next
"MADDE"). The writer treats such an unfinished tail as a possibly truncated rule, so the article is not usable as evidence
(measured 2026-10-31: TBK m. 342 "güvence en çok üç aylık kira bedelini aşamaz" was never cited).

This script reuses `repair_pdf_layout_proofs.py` unchanged for the proof itself (exact verified official text, the same line bold in
the matching official PDF, hashes bound to the existing verification proof) and only widens WHICH articles it looks at:
every current, verified `law` article whose text is not usable evidence today. It writes public source metadata only
(`mbs_pdf_layout`), never the legal text, revision, chunks, verification status or user data, backs the previous metadata up
first, and rolls a law's batch back if any row changed concurrently. Default is read-only.

  python scripts/repair_pdf_layout_proofs_all.py                         # preview every law with candidates (count only)
  python scripts/repair_pdf_layout_proofs_all.py --laws 6098,4857        # preview chosen laws
  python scripts/repair_pdf_layout_proofs_all.py --laws 6098 --apply     # write the proofs of those laws
"""

import importlib.util
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("repair_pdf_layout_proofs", ROOT / "scripts" / "repair_pdf_layout_proofs.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

from api.ai.free_answer import _usable  # noqa: E402
from api.db import admin_database_connection, database_connection  # noqa: E402
from ingestion.mevzuat.identity import canonical_article  # noqa: E402

_PAUSE_SECONDS = 2.0  # between official PDF downloads


def candidates(connection) -> dict[str, list[tuple[str, str]]]:
    """{law_no: [(law_no, article_no), ...]} of current verified law articles that are not usable evidence today."""
    connection.execute("SET LOCAL statement_timeout = '300s'")
    rows = connection.execute("""
        SELECT s.id, s.raw_text, s.content_hash, s.metadata, s.source_url, s.source_version, s.revision,
               d.law_no, d.article_no, d.law_name, d.article_title, s.title
        FROM legal_sources s JOIN legislation_details d ON d.legal_source_id=s.id
        WHERE s.source_type='legislation' AND s.deleted_at IS NULL AND s.is_current AND s.ingest_status='ready'
          AND d.legislation_type='law' AND d.law_no IS NOT NULL AND d.article_no IS NOT NULL
          AND s.metadata->'mbs_text_verification'->>'verified' = 'true'
          AND NOT jsonb_exists(s.metadata, 'mbs_pdf_layout')
    """).fetchall()
    result: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        text = row['raw_text'] or ''
        head = text[:80].casefold()
        if 'mülga' in head or 'mulga' in head or len(text) > 16000:
            continue  # repealed articles are not evidence; oversized ones fail for another reason
        article = canonical_article(row['article_no'])
        if _usable(base._context(row, article), 36000) is not None:
            continue
        result.setdefault(row['law_no'], []).append((row['law_no'], article))
    return result


def main():
    args = sys.argv[1:]
    apply_requested = '--apply' in args
    chosen = set(args[args.index('--laws') + 1].split(',')) if '--laws' in args else None
    with admin_database_connection() as read:
        read.execute('SET TRANSACTION READ ONLY')
        by_law = candidates(read)
    laws = sorted(by_law, key=lambda law: -len(by_law[law]))
    if chosen:
        laws = [law for law in laws if law in chosen]
    print(json.dumps(dict(laws_with_candidates=len(by_law), candidate_articles=sum(map(len, by_law.values())),
                          selected_laws=len(laws), apply=apply_requested), ensure_ascii=False), flush=True)
    if not chosen and not apply_requested and '--fetch' not in args:
        for law in laws[:15]:
            print(law, len(by_law[law]), flush=True)
        return
    total = Counter()
    for law in laws:
        references = sorted(by_law[law])
        base._references = lambda references=references: references
        try:
            with (admin_database_connection() if apply_requested else database_connection()) as db:
                if not apply_requested:
                    db.execute('SET TRANSACTION READ ONLY')
                outcomes, digest = base.preview(db)
                counts = Counter(item['status'] for item in outcomes)
                total.update(counts)
                line = dict(law=law, candidates=len(references), counts=dict(counts), digest=digest[:12])
                if apply_requested:
                    changed, backup = base.apply(db, outcomes, digest, digest)
                    line.update(written=changed, backup=backup)
                print(json.dumps(line, ensure_ascii=False), flush=True)
        except Exception as exc:  # one law failing must not stop the others; nothing of it was written
            print(json.dumps(dict(law=law, error=type(exc).__name__, detail=str(exc)[:160]), ensure_ascii=False), flush=True)
        time.sleep(_PAUSE_SECONDS)
    print(json.dumps(dict(total=dict(total)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
