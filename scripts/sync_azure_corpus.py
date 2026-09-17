"""Safely merge the public legal corpus from the Azure collector into local PG.

The SSH host runs psql inside its DB container, so PostgreSQL never needs a
public listener. User/project/document tables and local embeddings are untouched.
"""

from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "azure-corpus-sync-state.json"
LOG = logging.getLogger("azure-corpus-sync")

SOURCE_COLUMNS = (
    "id source_type title source_url raw_text metadata created_at updated_at "
    "external_id authority jurisdiction published_at effective_from effective_to "
    "version_label content_hash ingest_status last_ingested_at deleted_at "
    "canonical_source_name official_source_url ingestion_method fetched_at "
    "last_verified_at source_version revision is_current superseded_by_id"
).split()
CHUNK_COLUMNS = (
    "id legal_source_id chunk_index content metadata created_at section_title "
    "paragraph_start paragraph_end token_count content_hash updated_at"
).split()
COURT_COLUMNS = (
    "legal_source_id court_name chamber docket_no decision_no decision_date "
    "decision_type outcome created_at updated_at is_current"
).split()
LAW_COLUMNS = (
    "legal_source_id legislation_type law_name law_no article_no article_title "
    "paragraph_no clause_no official_gazette_no official_gazette_date "
    "version_date created_at updated_at legislation_identity_id version_identity "
    "amendment_source is_current"
).split()
IDENTITY_COLUMNS = (
    "id legislation_type law_no article_no canonical_name jurisdiction created_at updated_at"
).split()
REVISION_COLUMNS = (
    "id legal_source_id revision source_version content_hash raw_text metadata "
    "provenance recorded_at"
).split()


def _remote_sql(since: str | None) -> str:
    # since comes only from our validated state file, never directly from CLI.
    where = "s.deleted_at IS NULL"
    if since:
        timestamp = datetime.fromisoformat(since)
        if timestamp.tzinfo is None:
            raise ValueError("State timestamp needs timezone")
        safe = timestamp.astimezone(timezone.utc).isoformat()
        where += f" AND s.updated_at >= TIMESTAMPTZ '{safe}'"
    return f"""SELECT row_to_json(payload)::text FROM (
        SELECT s.*,
          (SELECT coalesce(json_agg(row_to_json(c)), '[]'::json) FROM
            (SELECT {', '.join(CHUNK_COLUMNS)} FROM legal_chunks
             WHERE legal_source_id=s.id ORDER BY chunk_index) c) AS chunks,
          (SELECT row_to_json(d) FROM
            (SELECT {', '.join(COURT_COLUMNS)} FROM court_decision_details
             WHERE legal_source_id=s.id) d) AS court_detail,
          (SELECT row_to_json(d) FROM
            (SELECT {', '.join(LAW_COLUMNS)} FROM legislation_details
             WHERE legal_source_id=s.id) d) AS law_detail,
          (SELECT row_to_json(i) FROM
            (SELECT {', '.join(IDENTITY_COLUMNS)} FROM legislation_identities
             WHERE id=(SELECT legislation_identity_id FROM legislation_details
                       WHERE legal_source_id=s.id)) i) AS law_identity,
          (SELECT coalesce(json_agg(row_to_json(r)), '[]'::json) FROM
            (SELECT {', '.join(REVISION_COLUMNS)} FROM legal_source_revisions
             WHERE legal_source_id=s.id ORDER BY revision) r) AS revisions
        FROM legal_sources s WHERE {where}
        ORDER BY s.updated_at, s.id
      ) payload"""


def _insert(conn: psycopg.Connection, table: str, row: dict[str, Any],
            columns: list[str]) -> None:
    values = [Jsonb(row[c]) if isinstance(row.get(c), (dict, list)) else row.get(c)
              for c in columns]
    query = (f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
             f"({', '.join(['%s'] * len(columns))})")
    conn.execute(query, values)


def _existing_source(conn: psycopg.Connection, row: dict[str, Any]) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, content_hash FROM legal_sources WHERE id=%s", (row["id"],))
        found = cur.fetchone()
        if found or not row.get("external_id"):
            return found
        cur.execute(
            """SELECT id, content_hash FROM legal_sources
               WHERE source_type=%s AND external_id=%s AND revision=%s
               ORDER BY is_current DESC LIMIT 1""",
            (row["source_type"], row["external_id"], row["revision"]),
        )
        return cur.fetchone()


def _merge_identity(conn: psycopg.Connection, identity: dict[str, Any] | None) -> str | None:
    if not identity:
        return None
    row = conn.execute(
        """SELECT id FROM legislation_identities
           WHERE legislation_type=%s AND law_no=%s AND article_no=%s""",
        (identity["legislation_type"], identity["law_no"], identity["article_no"]),
    ).fetchone()
    if row:
        return str(row[0])
    _insert(conn, "legislation_identities", identity, IDENTITY_COLUMNS)
    return identity["id"]


def _merge_child(conn: psycopg.Connection, table: str, row: dict[str, Any] | None,
                 columns: list[str], local_id: str) -> None:
    if not row:
        return
    row = dict(row)
    row["legal_source_id"] = local_id
    exists = conn.execute(f"SELECT 1 FROM {table} WHERE legal_source_id=%s",
                          (local_id,)).fetchone()
    if not exists:
        _insert(conn, table, row, columns)


def merge_record(conn: psycopg.Connection, payload: dict[str, Any],
                 *, dry_run: bool = False) -> str:
    """Import a source atomically; never overwrite a divergent local source."""
    source = {column: payload.get(column) for column in SOURCE_COLUMNS}
    existing = _existing_source(conn, source)
    if existing and existing["content_hash"] != source["content_hash"]:
        return "conflict"
    if dry_run:
        return "same" if existing else "new"
    local_id = str(existing["id"]) if existing else source["id"]
    if not existing:
        # Source revisions may point to another source not imported yet. Do not
        # manufacture a relationship; report these for a dedicated pass.
        if source["superseded_by_id"]:
            return "deferred"
        _insert(conn, "legal_sources", source, SOURCE_COLUMNS)
    identity_id = _merge_identity(conn, payload.get("law_identity"))
    law_detail = payload.get("law_detail")
    if law_detail:
        law_detail = dict(law_detail)
        law_detail["legislation_identity_id"] = identity_id
    _merge_child(conn, "court_decision_details", payload.get("court_detail"),
                 COURT_COLUMNS, local_id)
    _merge_child(conn, "legislation_details", law_detail, LAW_COLUMNS, local_id)
    for chunk in payload.get("chunks") or []:
        old = conn.execute(
            "SELECT content_hash FROM legal_chunks WHERE legal_source_id=%s AND chunk_index=%s",
            (local_id, chunk["chunk_index"]),
        ).fetchone()
        if old:
            if old[0] != chunk.get("content_hash"):
                raise ValueError(f"chunk conflict source={source['external_id']} index={chunk['chunk_index']}")
            continue
        chunk = dict(chunk)
        chunk["legal_source_id"] = local_id
        _insert(conn, "legal_chunks", chunk, CHUNK_COLUMNS)
    for revision in payload.get("revisions") or []:
        old = conn.execute(
            "SELECT content_hash FROM legal_source_revisions WHERE legal_source_id=%s AND revision=%s",
            (local_id, revision["revision"]),
        ).fetchone()
        if old:
            if old[0] != revision.get("content_hash"):
                raise ValueError(f"revision conflict source={source['external_id']} revision={revision['revision']}")
            continue
        revision = dict(revision)
        revision["legal_source_id"] = local_id
        _insert(conn, "legal_source_revisions", revision, REVISION_COLUMNS)
    return "same" if existing else "new"


def _load_since(path: Path, *, full: bool) -> str | None:
    if full or not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    stamp = datetime.fromisoformat(state["last_updated_at"])
    if stamp.tzinfo is None:
        raise ValueError("State timestamp needs timezone")
    return (stamp - timedelta(minutes=1)).astimezone(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="nhr@20.91.186.253")
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--full", action="store_true", help="Ignore incremental watermark")
    parser.add_argument("--dry-run", action="store_true", help="Read both DBs, write neither")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not args.dry_run:
        log_path = ROOT / "data" / "azure-corpus-sync.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=2,
                                      encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger().addHandler(handler)
    load_dotenv(ROOT / ".env")
    db_url = os.getenv("DATABASE_ADMIN_URL")
    if not db_url:
        parser.error("DATABASE_ADMIN_URL is required in the local .env")
    since = _load_since(args.state, full=args.full)
    sql = _remote_sql(since)
    remote = ("docker exec -i nhr-legal-ai-db psql -X -A -t -q -v ON_ERROR_STOP=1 "
              "-U nhr_app -d nhr_legal_ai -c " + shlex.quote(sql))
    command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
               "-o", "ConnectTimeout=10", args.host, remote]
    totals = {"new": 0, "same": 0, "conflict": 0, "deferred": 0, "failed": 0}
    highest: datetime | None = None
    with psycopg.connect(db_url, autocommit=False) as conn:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8") as process:
            assert process.stdout is not None
            for line in process.stdout:
                payload = json.loads(line)
                try:
                    if args.dry_run:
                        with conn.transaction():
                            status = merge_record(conn, payload, dry_run=True)
                    else:
                        with conn.transaction():
                            status = merge_record(conn, payload)
                    totals[status] += 1
                    stamp = datetime.fromisoformat(payload["updated_at"])
                    highest = max(highest or stamp, stamp)
                except (psycopg.Error, ValueError) as exc:
                    totals["failed"] += 1
                    LOG.error("record failed external_id=%s: %s", payload.get("external_id"), exc)
            assert process.stderr is not None
            stderr = process.stderr.read()
            code = process.wait()
        if code:
            LOG.error("Azure export failed: %s", stderr.strip())
            return 1
    LOG.info("Azure corpus sync %s: %s", "dry-run" if args.dry_run else "finished", totals)
    if totals["failed"] or totals["conflict"] or totals["deferred"]:
        return 2
    if highest and not args.dry_run:
        args.state.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.state.with_suffix(".tmp")
        temporary.write_text(json.dumps({"last_updated_at": highest.isoformat()}) + "\n",
                             encoding="utf-8")
        temporary.replace(args.state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
