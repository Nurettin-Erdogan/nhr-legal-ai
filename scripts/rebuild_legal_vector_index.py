"""Plan, or explicitly build, the missing shared legal ANN index without stopping writes.

Default is read-only. ``--apply`` uses CREATE INDEX CONCURRENTLY, never the bulk
cleanup script (which deletes vectors). Existing indexes are preserved except
explicit recovery of a verified empty, invalid, not-ready placeholder.
Credentials are read in memory from project settings and never printed/saved.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import monotonic

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.config import get_settings
from api.ai.vector_index import INDEX_READY_SQL

CREATE_SQL = """CREATE INDEX CONCURRENTLY idx_legal_chunks_embedding_hnsw
ON public.legal_chunks USING hnsw (embedding vector_cosine_ops)
WHERE embedding IS NOT NULL"""


def run(connection, *, apply=False, repair_empty_invalid=False):
    # No table row is read or changed during planning.
    ready = connection.execute(INDEX_READY_SQL).fetchone()["ready"]
    named = connection.execute("""SELECT ix.indisvalid, ix.indisready,
        pg_relation_size(ix.indexrelid) AS bytes,
        ix.indrelid = 'public.legal_chunks'::regclass AS correct_table
        FROM pg_index ix WHERE ix.indexrelid = to_regclass('public.idx_legal_chunks_embedding_hnsw')""").fetchone()
    building = connection.execute("""SELECT phase FROM pg_stat_progress_create_index
        WHERE relid = to_regclass('public.legal_chunks')""").fetchall()
    plan = {"ready":ready,"named_index":named,"active_build":building,"apply":apply,
            "writes_remain_enabled":True,"maintenance_work_mem":"512MB","parallel_workers":0}
    print(json.dumps(plan),flush=True)
    if ready:
        return 0
    repairable = bool(named and named.get("indisvalid") is False and named.get("indisready") is False
                      and named.get("bytes") == 0 and named.get("correct_table") is True)
    if building or (named and not (repair_empty_invalid and repairable)):
        print("STOP: existing/invalid index or active build requires separate review; nothing dropped.",flush=True)
        return 2
    if not apply:
        print("Read-only plan; use --apply only after the operator approves the disk/CPU work.",flush=True)
        return 0
    connection.execute("SET statement_timeout = 0")
    # Existing embedding UPDATE transactions are compatible with the build but
    # concurrent index phases must wait for them. A short lock timeout aborts
    # normal writer waits, leaving an unusable empty index behind.
    connection.execute("SET lock_timeout = 0")
    connection.execute("SET maintenance_work_mem = '512MB'")
    connection.execute("SET max_parallel_maintenance_workers = 0")
    if named:
        # Explicit recovery only for a verified empty, invalid, not-ready index
        # on the intended table. Never drop a valid, nonempty or active index.
        connection.execute("DROP INDEX CONCURRENTLY public.idx_legal_chunks_embedding_hnsw")
        print("Removed only the empty invalid index placeholder; no vector rows changed.",flush=True)
    started = monotonic()
    print("BUILD STARTED: concurrent cosine HNSW, no vector deletion or worker restart.",flush=True)
    connection.execute(CREATE_SQL)
    ready = connection.execute(INDEX_READY_SQL).fetchone()["ready"]
    print(json.dumps({"ready":ready,"seconds":round(monotonic()-started,2)}),flush=True)
    return 0 if ready else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true",help="Actually create the concurrent index (heavy disk/CPU work)")
    parser.add_argument("--repair-empty-invalid",action="store_true",help="Recover only a verified 0-byte invalid/not-ready placeholder")
    args = parser.parse_args()
    url = get_settings().admin_database_url
    if not url:
        print("DATABASE_ADMIN_URL is not configured; nothing changed.",flush=True)
        return 2
    try:
        # CONCURRENTLY is forbidden inside a transaction block.
        with psycopg.connect(url,autocommit=True,row_factory=dict_row,connect_timeout=5) as connection:
            return run(connection,apply=args.apply,repair_empty_invalid=args.repair_empty_invalid)
    except psycopg.Error as exc:
        # Avoid traceback/connection strings or server text containing secrets.
        print(json.dumps({"error":type(exc).__name__,"sqlstate":exc.sqlstate,
                          "note":"Inspect index validity before retrying; no automatic drop performed."}),flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
