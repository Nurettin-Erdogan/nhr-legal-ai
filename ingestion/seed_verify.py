"""Tohum karar metnini resmî portal metniyle karşılaştırır ve eşleşeni yükseltir."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from psycopg.types.json import Jsonb

from ingestion.hf_700k import strip_third_party_markup
from ingestion.text import content_hash, html_to_text, normalize_text

_INVISIBLE = re.compile(r"[­​-‏‪-‮⁠-⁤⁦-⁩﻿]")

SOURCES = {
    "yargitay": {
        "prefix": "yargitay:",
        "method": "yargitay_public_json_http",
        "canonical": "Yargıtay Karar Arama",
    },
    "danistay": {
        "prefix": "danistay:",
        "method": "danistay_public_json_http",
        "canonical": "Danıştay Karar Arama",
    },
}

_VERIFY_SQL = """
UPDATE legal_sources
SET ingest_status = 'ready',
    ingestion_method = %(method)s,
    canonical_source_name = %(canonical)s,
    official_source_url = %(url)s,
    source_url = COALESCE(%(url)s, source_url),
    raw_text = %(text)s,
    content_hash = %(hash)s,
    source_version = %(version)s,
    metadata = metadata || %(metadata)s,
    last_ingested_at = NOW(),
    fetched_at = NOW(),
    last_verified_at = NOW()
WHERE id = %(id)s AND ingestion_method = 'bulk_seed' AND ingest_status = 'pending'
"""


def _canon(text: str) -> str:
    return re.sub(r"\s+", " ", _INVISIBLE.sub("", text)).strip().casefold()


def _nospace(text: str) -> str:
    return re.sub(r"\s+", "", _INVISIBLE.sub("", text)).casefold()


def seed_matches_official(seed_text: str, official: str) -> bool:
    seed_key = _canon(seed_text or "")
    if seed_key in (_canon(official), _canon(strip_third_party_markup(official))):
        return True
    seed_flat = _nospace(seed_text or "")
    return seed_flat in (_nospace(official), _nospace(strip_third_party_markup(official)))


def source_kind_from_external_id(external_id: str) -> str | None:
    for kind, config in SOURCES.items():
        if external_id.startswith(config["prefix"]):
            return kind
    return None


def document_id_from_external_id(external_id: str) -> str:
    return external_id.split(":", 1)[1]


def fetch_official_text(kind: str, document_id: str) -> str:
    if kind == "yargitay":
        from ingestion.yargitay.portal import YargitayPortalClient

        html = YargitayPortalClient(timeout_seconds=12, max_retries=1).fetch_document_html(
            document_id
        )
        return normalize_text(html_to_text(html))
    if kind == "danistay":
        from ingestion.danistay.portal import DanistayPortalClient
        from ingestion.danistay.scraper import extract_decision_text

        html = DanistayPortalClient(timeout_seconds=12, max_retries=1).fetch_document_html(
            document_id
        )
        return extract_decision_text(html)
    raise ValueError(f"Desteklenmeyen kaynak: {kind}")


def official_document_url(kind: str, document_id: str) -> str:
    if kind == "yargitay":
        from ingestion.yargitay.portal import document_url

        return document_url(document_id)
    from ingestion.danistay.portal import document_url

    return document_url(document_id)


def promote_verified_seed(
    connection,
    *,
    source_id: UUID,
    kind: str,
    document_id: str,
    official_text: str,
) -> None:
    from ingestion.yargitay.store import _SNAPSHOT_SOURCE

    config = SOURCES[kind]
    digest = content_hash(official_text)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(_SNAPSHOT_SOURCE, (source_id,))
        cursor.execute(
            _VERIFY_SQL,
            {
                "id": source_id,
                "method": config["method"],
                "canonical": config["canonical"],
                "url": official_document_url(kind, document_id),
                "text": official_text,
                "hash": digest,
                "version": f"sha256:{digest[:16]}",
                "metadata": Jsonb(
                    {
                        "official_verified": True,
                        "third_party": False,
                        "provenance": "official_portal",
                        "verified_via": "live_request",
                        "verified_at": now,
                        "verification": "text_equal_ignoring_whitespace",
                    }
                ),
            },
        )
