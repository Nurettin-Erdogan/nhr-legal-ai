"""Inventory HTTP kuyruğundan Yargıtay getDokuman çeker. Chunk yazmaz."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from ingestion.hf_700k import OVERSIZED_CHARS, parse_case_no
from ingestion.text import content_hash, html_to_text, normalize_text
from ingestion.yargitay.parser import build_title, parse_chamber, parse_decision_date, parse_decision_no, parse_docket_no
from ingestion.yargitay.portal import (
    CaptchaRequiredError,
    PortalError,
    YargitayPortalClient,
    document_url,
    parse_portal_date,
    portal_external_id,
)

MIN_TEXT_CHARS = 80
INGESTION_METHOD = "bulk_seed"
CANONICAL_SOURCE_NAME = "Yargıtay Karar Arama HTTP kuyruk"

_CLAIM_SQL = """
UPDATE bulk_seed_fulltext_queue AS q
SET status = 'in_progress',
    attempts = q.attempts + 1,
    updated_at = NOW()
FROM (
  SELECT document_id
  FROM bulk_seed_fulltext_queue
  WHERE status = 'pending'
    AND (next_run_at IS NULL OR next_run_at <= NOW())
  ORDER BY document_id DESC
  LIMIT %s
  FOR UPDATE SKIP LOCKED
) AS due
WHERE q.document_id = due.document_id
RETURNING q.document_id
"""

_CLAIM_SHARDED_SQL = """
UPDATE bulk_seed_fulltext_queue AS q
SET status = 'in_progress',
    attempts = q.attempts + 1,
    updated_at = NOW()
FROM (
  SELECT document_id
  FROM bulk_seed_fulltext_queue
  WHERE status = 'pending'
    AND (next_run_at IS NULL OR next_run_at <= NOW())
    AND abs(hashtext(document_id)) %% %s = %s
  ORDER BY document_id DESC
  LIMIT %s
  FOR UPDATE SKIP LOCKED
) AS due
WHERE q.document_id = due.document_id
RETURNING q.document_id
"""

_LOAD_INVENTORY = """
SELECT document_id, chamber, docket_no, decision_no, decision_date
FROM bulk_seed_inventory
WHERE document_id = ANY(%s)
"""


def prepare_http_fulltext(
    *,
    document_id: str,
    html: str,
    chamber: str = "",
    docket_no: str = "",
    decision_no: str = "",
    decision_date: date | str | None = None,
) -> dict[str, Any]:
    body = normalize_text(html_to_text(html or ""))
    if len(body) < MIN_TEXT_CHARS:
        raise PortalError(f"Karar metni kısa veya boş: {document_id}")

    parsed_docket = parse_case_no(docket_no) or parse_docket_no(body) or ""
    parsed_decision = parse_case_no(decision_no) or parse_decision_no(body) or ""
    parsed_date = None
    if isinstance(decision_date, date):
        parsed_date = decision_date
    elif decision_date:
        parsed_date = parse_portal_date(str(decision_date))
    parsed_date = parsed_date or parse_decision_date(body)
    parsed_chamber = (chamber or "").strip() or parse_chamber(body) or ""

    if not parsed_docket or not parsed_decision:
        raise PortalError(f"Esas/karar no yok: {document_id}")

    return {
        "document_id": document_id,
        "court_name": "Yargıtay",
        "chamber": parsed_chamber,
        "docket_no": parsed_docket,
        "decision_no": parsed_decision,
        "decision_date": parsed_date,
        "title": build_title(
            "Yargıtay", parsed_chamber or None, parsed_docket, parsed_decision, parsed_date
        ),
        "raw_text": body,
        "external_id": portal_external_id(document_id),
        "content_hash": content_hash(body),
        "source_url": document_url(document_id),
        "oversized": len(body) > OVERSIZED_CHARS,
    }


def claim_due_ids(
    connection: psycopg.Connection,
    *,
    limit: int,
    shard: int = 0,
    shards: int = 1,
) -> list[str]:
    shards = max(1, shards)
    if shards == 1:
        rows = connection.execute(_CLAIM_SQL, (max(1, limit),)).fetchall()
    else:
        rows = connection.execute(
            _CLAIM_SHARDED_SQL, (shards, shard % shards, max(1, limit))
        ).fetchall()
    if rows and isinstance(rows[0], dict):
        return [str(row["document_id"]) for row in rows]
    return [str(row[0]) for row in rows]


def load_inventory_rows(
    connection: psycopg.Connection, document_ids: list[str]
) -> dict[str, dict[str, Any]]:
    if not document_ids:
        return {}
    rows = connection.execute(_LOAD_INVENTORY, (document_ids,)).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = dict(row) if isinstance(row, dict) else {
            "document_id": row[0],
            "chamber": row[1],
            "docket_no": row[2],
            "decision_no": row[3],
            "decision_date": row[4],
        }
        out[str(payload["document_id"])] = payload
    return out


def mark_queue(
    connection: psycopg.Connection,
    document_id: str,
    status: str,
    *,
    error: str | None = None,
    delay_seconds: int = 0,
) -> None:
    next_run = None
    if delay_seconds > 0:
        next_run = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
    connection.execute(
        """
        UPDATE bulk_seed_fulltext_queue
        SET status = %s,
            last_error = %s,
            next_run_at = %s,
            updated_at = NOW()
        WHERE document_id = %s
        """,
        (status, error, next_run, document_id),
    )


def insert_http_fulltext(connection: psycopg.Connection, prepared: dict[str, Any]) -> str:
    source_id = uuid4()
    metadata = {
        "provenance": "bulk_seed",
        "official_verified": False,
        "source_adapter": "yargitay_http_queue",
        "source_document_id": prepared["document_id"],
        "import_type": "http_fulltext_queue",
        "oversized_text": prepared["oversized"],
    }
    try:
        with connection.transaction():
            connection.execute(
                """
                INSERT INTO legal_sources (
                  id, source_type, title, source_url, external_id, authority, jurisdiction,
                  raw_text, metadata, published_at, content_hash, ingest_status, last_ingested_at,
                  canonical_source_name, official_source_url, ingestion_method, fetched_at,
                  last_verified_at, source_version, revision, is_current
                )
                VALUES (
                  %s, 'court_decision', %s, %s, %s, %s, 'TR',
                  %s, %s, %s, %s, 'pending', NOW(),
                  %s, %s, %s, NOW(), NOW(), %s, 1, TRUE
                )
                """,
                (
                    source_id,
                    prepared["title"],
                    prepared["source_url"],
                    prepared["external_id"],
                    prepared["court_name"],
                    prepared["raw_text"],
                    Jsonb(metadata),
                    prepared["decision_date"],
                    prepared["content_hash"],
                    CANONICAL_SOURCE_NAME,
                    prepared["source_url"],
                    INGESTION_METHOD,
                    f"httpq:{prepared['document_id']}",
                ),
            )
            connection.execute(
                """
                INSERT INTO court_decision_details (
                  legal_source_id, court_name, chamber, docket_no, decision_no, decision_date
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    source_id,
                    prepared["court_name"],
                    prepared["chamber"] or None,
                    prepared["docket_no"] or None,
                    prepared["decision_no"] or None,
                    prepared["decision_date"],
                ),
            )
    except UniqueViolation:
        return "duplicate"
    return "inserted"


def requeue_stale_in_progress(connection: psycopg.Connection, minutes: int = 15) -> int:
    result = connection.execute(
        """
        UPDATE bulk_seed_fulltext_queue
        SET status = 'pending', updated_at = NOW()
        WHERE status = 'in_progress'
          AND updated_at < NOW() - (%s * interval '1 minute')
        """,
        (minutes,),
    )
    return result.rowcount or 0


def process_claimed_batch(
    connection: psycopg.Connection,
    client: YargitayPortalClient,
    document_ids: list[str],
    *,
    delay_seconds: float,
) -> dict[str, int]:
    from time import sleep

    stats = {
        "seen": 0,
        "inserted": 0,
        "duplicate": 0,
        "failed": 0,
        "captcha": 0,
        "rate_limited": 0,
    }
    inventory = load_inventory_rows(connection, document_ids)
    for document_id in document_ids:
        stats["seen"] += 1
        meta = inventory.get(document_id) or {}
        try:
            html = client.fetch_document_html(document_id)
            prepared = prepare_http_fulltext(
                document_id=document_id,
                html=html,
                chamber=str(meta.get("chamber") or ""),
                docket_no=str(meta.get("docket_no") or ""),
                decision_no=str(meta.get("decision_no") or ""),
                decision_date=meta.get("decision_date"),
            )
            outcome = insert_http_fulltext(connection, prepared)
            if outcome == "inserted":
                mark_queue(connection, document_id, "done")
                stats["inserted"] += 1
            else:
                mark_queue(connection, document_id, "skipped", error="duplicate")
                stats["duplicate"] += 1
            connection.commit()
        except CaptchaRequiredError as exc:
            mark_queue(
                connection,
                document_id,
                "failed",
                error=str(exc),
                delay_seconds=45,
            )
            connection.commit()
            stats["captcha"] += 1
            raise
        except TimeoutError as exc:
            mark_queue(
                connection,
                document_id,
                "failed",
                error=f"timeout: {exc}"[:500],
                delay_seconds=20,
            )
            connection.commit()
            stats["failed"] += 1
        except PortalError as exc:
            message = str(exc)
            rate_limited = "429" in message
            mark_queue(
                connection,
                document_id,
                "failed",
                error=message[:500],
                delay_seconds=30 if rate_limited else 120,
            )
            connection.commit()
            stats["failed"] += 1
            if rate_limited:
                stats["rate_limited"] += 1
                sleep(max(delay_seconds, 8.0))
        if delay_seconds > 0:
            sleep(delay_seconds)
    return stats
