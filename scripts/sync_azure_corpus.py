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
from uuid import UUID

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
STATE_PATH = ROOT / "data" / "azure-corpus-sync-state.json"
BATCH_ROWS = 1500  # rows per ssh call; a dropped connection only costs one batch
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


def _remote_sql(since: str | None, *, after: tuple[datetime, str] | None = None,
                limit: int | None = None) -> str:
    # since comes only from our validated state file, never directly from CLI.
    where = "s.deleted_at IS NULL"
    if since:
        timestamp = datetime.fromisoformat(since)
        if timestamp.tzinfo is None:
            raise ValueError("State timestamp needs timezone")
        safe = timestamp.astimezone(timezone.utc).isoformat()
        where += f" AND s.updated_at >= TIMESTAMPTZ '{safe}'"
    if after:
        # Keyset cursor (updated_at, id) of the last row already processed in this run, so a
        # dropped connection resumes after it instead of rescanning from the watermark.
        after_stamp, after_id = after
        if after_stamp.tzinfo is None:
            raise ValueError("Cursor timestamp needs timezone")
        cursor_id = str(UUID(str(after_id)))
        where += (f" AND (s.updated_at, s.id) > (TIMESTAMPTZ "
                  f"'{after_stamp.astimezone(timezone.utc).isoformat()}', '{cursor_id}'::uuid)")
    row_limit = f" LIMIT {int(limit)}" if limit else ""
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
        ORDER BY s.updated_at, s.id{row_limit}
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
        cur.execute("SELECT id, content_hash, revision, raw_text, ingestion_method, ingest_status FROM legal_sources WHERE id=%s", (row["id"],))
        found = cur.fetchone()
        if found or not row.get("external_id"):
            return found
        # Revision numbers are local to each machine: the same decision can be revision 1
        # on Azure and revision 2 here. Match the same revision first, otherwise fall back
        # to the current row, which is what the unique index on external_id protects.
        cur.execute(
            """SELECT id, content_hash, revision, raw_text, ingestion_method, ingest_status FROM legal_sources
               WHERE source_type=%s AND external_id=%s
               ORDER BY (revision = %s) DESC, is_current DESC LIMIT 1""",
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


VERIFICATION_FLAGS = (
    ("verified_against_gazette", "official_gazette_verification"),
    ("verified_against_mbs", "mbs_verification"),
)


def verification_patch(local_metadata: dict[str, Any] | None,
                       remote_metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Metadata keys that only ADD an official verification the local row lacks.

    Monotonic by design: a verification is never revoked here, and operational
    counters (attempt counts, retry stamps) are never copied between machines.
    """
    local = local_metadata or {}
    remote = remote_metadata or {}
    patch: dict[str, Any] = {}
    for flag, detail in VERIFICATION_FLAGS:
        if remote.get(flag) is True and local.get(flag) is not True:
            patch[flag] = True
            if detail in remote:
                patch[detail] = remote[detail]
    return patch


def _upgrade_verification(conn: psycopg.Connection, local_id: str,
                          source: dict[str, Any], *, dry_run: bool) -> bool:
    """Carry Azure's mevzuat verification progress into the local row."""
    row = conn.execute(
        "SELECT metadata FROM legal_sources WHERE id=%s", (local_id,)
    ).fetchone()
    patch = verification_patch(row[0] if row else None, source.get("metadata"))
    if not patch:
        return False
    if dry_run:
        return True
    merged = {**(row[0] or {}), **patch}
    both = all(merged.get(flag) is True for flag, _ in VERIFICATION_FLAGS)
    conn.execute(
        """UPDATE legal_sources
           SET metadata = %s,
               ingest_status = CASE WHEN %s THEN 'ready' ELSE ingest_status END,
               last_verified_at = CASE WHEN %s
                   THEN COALESCE(%s, now()) ELSE last_verified_at END
           WHERE id = %s""",
        (Jsonb(merged), both, both, source.get("last_verified_at"), local_id),
    )
    return True


def seed_promotion(existing: dict[str, Any], source: dict[str, Any]) -> bool:
    """True when the local row is an unverified bulk seed and Azure holds the official fetch.

    Only an official portal row (not itself a bulk seed, status ready) whose text equals the
    seed text ignoring whitespace may replace the seed. Any other difference stays a conflict.
    """
    if existing.get("ingestion_method") != "bulk_seed" or existing.get("ingest_status") != "pending":
        return False
    if source.get("ingestion_method") in (None, "bulk_seed") or source.get("ingest_status") != "ready":
        return False
    if (source.get("metadata") or {}).get("third_party") is True:
        return False
    from ingestion.seed_verify import seed_matches_official

    return seed_matches_official(existing.get("raw_text") or "", source.get("raw_text") or "")


def _promote_seed(conn: psycopg.Connection, local_id: str, source: dict[str, Any]) -> None:
    """Replace a verified-equal bulk seed with the official text fetched by Azure."""
    from ingestion.yargitay.store import _SNAPSHOT_SOURCE

    conn.execute(_SNAPSHOT_SOURCE, (local_id,))
    flags = {
        "official_verified": True,
        "third_party": False,
        "provenance": "official_portal",
        "verified_via": "azure_collector_sync",
        "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verification": "text_equal_ignoring_whitespace",
    }
    conn.execute(
        """UPDATE legal_sources
           SET ingest_status = 'ready',
               ingestion_method = %s,
               canonical_source_name = %s,
               official_source_url = %s,
               source_url = COALESCE(%s, source_url),
               raw_text = %s,
               content_hash = %s,
               source_version = %s,
               metadata = metadata || %s,
               last_ingested_at = NOW(),
               fetched_at = COALESCE(%s, NOW()),
               last_verified_at = COALESCE(%s, NOW())
           WHERE id = %s AND ingestion_method = 'bulk_seed' AND ingest_status = 'pending'""",
        (source["ingestion_method"], source.get("canonical_source_name"),
         source.get("official_source_url"), source.get("official_source_url"),
         source["raw_text"], source["content_hash"], source.get("source_version"),
         Jsonb(flags), source.get("fetched_at"), source.get("last_verified_at"), local_id),
    )


def merge_record(conn: psycopg.Connection, payload: dict[str, Any],
                 *, dry_run: bool = False) -> str:
    """Import a source atomically; never overwrite a divergent local source."""
    source = {column: payload.get(column) for column in SOURCE_COLUMNS}
    existing = _existing_source(conn, source)
    promote = False
    if existing and existing["content_hash"] != source["content_hash"]:
        if not seed_promotion(existing, source):
            return "conflict"
        if dry_run:
            return "promoted"
        promote = True
    if not promote and existing and existing.get("revision", source["revision"]) != source["revision"] and existing["id"] != source["id"]:
        # Identical content under a different local revision number: nothing to import.
        return "same"
    if dry_run:
        if existing and source["source_type"] == "legislation" and _upgrade_verification(
            conn, str(existing["id"]), source, dry_run=True
        ):
            return "verified"
        return "same" if existing else "new"
    local_id = str(existing["id"]) if existing else source["id"]
    if promote:
        _promote_seed(conn, local_id, source)
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
            # The source text is identical (checked above); a differing chunk only means the
            # two machines chunked it with different parameters. Local chunks stay as they are.
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
            # Revision history is local bookkeeping; the current source content already
            # matched above, so a differing historical row is kept as is, not overwritten.
            continue
        revision = dict(revision)
        revision["legal_source_id"] = local_id
        _insert(conn, "legal_source_revisions", revision, REVISION_COLUMNS)
    if existing and source["source_type"] == "legislation" and _upgrade_verification(
        conn, local_id, source, dry_run=False
    ):
        return "verified"
    if promote:
        return "promoted"
    return "same" if existing else "new"


def _load_since(path: Path, *, full: bool) -> str | None:
    if full or not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    stamp = datetime.fromisoformat(state["last_updated_at"])
    if stamp.tzinfo is None:
        raise ValueError("State timestamp needs timezone")
    return (stamp - timedelta(minutes=1)).astimezone(timezone.utc).isoformat()


def _embed_missing(db_url: str, limit: int) -> None:
    """Fill missing vectors without changing the local corpus embedding model."""
    from api.ai.embeddings import create_embedding_provider
    from ingestion.embeddings import embed_legal_chunks

    model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
    with psycopg.connect(db_url) as conn:
        rows = conn.execute(
            "SELECT DISTINCT embedding_model FROM legal_chunks WHERE embedding IS NOT NULL"
        ).fetchall()
        existing_models = {row[0] for row in rows}
        if existing_models and existing_models != {model}:
            raise ValueError(
                f"Local embedding model {existing_models} differs from configured {model}"
            )
        provider = create_embedding_provider(
            provider_name=os.getenv("EMBEDDING_PROVIDER", "ollama"),
            model=model,
            dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "768")),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        )
        summary = embed_legal_chunks(
            conn, provider, limit=limit, batch_size=8, delay_seconds=0,
            max_retries=2, retry_backoff_seconds=5,
        )
        LOG.info("Embedding pass embedded=%s remaining=%s", summary.embedded,
                 summary.remaining)


LOCK_PATH = ROOT / "data" / "azure-corpus-sync.lock"
LOCK_STALE_SECONDS = 6 * 3600


def _acquire_lock(path: Path = LOCK_PATH) -> bool:
    """One sync at a time: the hourly task and a manual run must not write concurrently."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = datetime.now().timestamp() - path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age < LOCK_STALE_SECONDS:
                return False
            path.unlink(missing_ok=True)  # left behind by a killed run
            continue
        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    if not _acquire_lock():
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        LOG.warning("Another Azure corpus sync is running; skipping this run")
        return 0
    try:
        return _sync(argv)
    finally:
        LOCK_PATH.unlink(missing_ok=True)


def _sync(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="nhr@20.91.186.253")
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--full", action="store_true", help="Ignore incremental watermark")
    parser.add_argument("--dry-run", action="store_true", help="Read both DBs, write neither")
    parser.add_argument("--embed-limit", type=int, default=0,
                        help="Fill at most N missing local legal embeddings after sync")
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
    if args.embed_limit < 0:
        parser.error("--embed-limit must be nonnegative")
    since = _load_since(args.state, full=args.full)
    totals = {"new": 0, "same": 0, "verified": 0, "promoted": 0, "conflict": 0,
              "deferred": 0, "failed": 0}
    highest: datetime | None = None
    blocked: datetime | None = None  # first failed/deferred record: never advance past it
    conflicts_path = args.state.with_name("azure-corpus-sync-conflicts.jsonl")

    def save_watermark() -> None:
        if not highest or args.dry_run:
            return
        watermark = highest if blocked is None else min(highest, blocked)
        args.state.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.state.with_suffix(".tmp")
        temporary.write_text(json.dumps({"last_updated_at": watermark.isoformat()}) + "\n",
                             encoding="utf-8")
        temporary.replace(args.state)

    def log_conflict(payload: dict[str, Any], reason: str) -> None:
        if args.dry_run:
            return
        with conflicts_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "at": datetime.now(timezone.utc).isoformat(),
                "external_id": payload.get("external_id"),
                "source_type": payload.get("source_type"),
                "reason": reason,
                "remote_content_hash": payload.get("content_hash"),
            }) + "\n")

    cursor: tuple[datetime, str] | None = None  # last row fully processed in this run
    interrupted_batches = 0
    with psycopg.connect(db_url, autocommit=False) as conn:
        while True:
            sql = _remote_sql(since, after=cursor, limit=BATCH_ROWS)
            remote = ("docker exec -i nhr-legal-ai-db psql -X -A -t -q -v ON_ERROR_STOP=1 "
                      "-U nhr_app -d nhr_legal_ai -c " + shlex.quote(sql))
            command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                       "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
                       "-o", "ServerAliveCountMax=4", args.host, remote]
            rows = 0
            truncated = False
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  ) as process:
                assert process.stdout is not None
                for line in process.stdout:
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except ValueError:  # JSONDecodeError or a multibyte char cut in half
                        # The connection dropped mid-row. Nothing partial is imported.
                        truncated = True
                        break
                    stamp = datetime.fromisoformat(payload["updated_at"])
                    rows += 1
                    cursor = (stamp, payload["id"])
                    try:
                        with conn.transaction():
                            status = merge_record(conn, payload, dry_run=args.dry_run)
                    except psycopg.errors.UniqueViolation as exc:
                        # The same decision already exists locally under another external_id
                        # (natural key: court, chamber, docket, decision no). Keep the local row.
                        totals["conflict"] += 1
                        highest = max(highest or stamp, stamp)
                        constraint = exc.diag.constraint_name or "unique_violation"
                        LOG.warning("duplicate (%s) external_id=%s: %s", constraint,
                                    payload.get("external_id"), str(exc).splitlines()[0])
                        log_conflict(payload, constraint)
                        continue
                    except (psycopg.Error, ValueError) as exc:
                        totals["failed"] += 1
                        blocked = min(blocked or stamp, stamp)
                        LOG.error("record failed external_id=%s: %s",
                                  payload.get("external_id"), exc)
                        continue
                    totals[status] += 1
                    if status == "deferred":
                        blocked = min(blocked or stamp, stamp)
                        continue
                    if status == "conflict":
                        # Divergent content is never overwritten. It is recorded for review and
                        # does not block the watermark, otherwise every run would rescan all.
                        LOG.warning("conflict external_id=%s", payload.get("external_id"))
                        log_conflict(payload, "content_differs")
                    highest = max(highest or stamp, stamp)
                if truncated:
                    process.kill()
                assert process.stderr is not None
                stderr = process.stderr.read().decode("utf-8", errors="replace")
                code = process.wait()
            save_watermark()
            if truncated or (code and not truncated):
                interrupted_batches += 1
                LOG.warning("Azure export interrupted (exit %s, %s rows this batch, attempt %s/3): %s",
                            code, rows, interrupted_batches, stderr.strip()[:300])
                if interrupted_batches >= 3:
                    LOG.error("Azure export keeps failing; progress saved, run again to resume")
                    LOG.info("Azure corpus sync interrupted: %s", totals)
                    return 1
                continue  # resume right after the last processed row
            interrupted_batches = 0
            if rows < BATCH_ROWS:
                break
    LOG.info("Azure corpus sync %s: %s", "dry-run" if args.dry_run else "finished", totals)
    if totals["failed"] or totals["deferred"]:
        return 2
    if args.embed_limit and not args.dry_run:
        try:
            _embed_missing(db_url, args.embed_limit)
        except Exception as exc:  # noqa: BLE001
            LOG.error("Local embedding pass failed: %s", exc)
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
