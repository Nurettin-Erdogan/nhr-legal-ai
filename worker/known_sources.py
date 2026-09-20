"""Historical backfill'de hazır kayıtlar için belge indirmeyi atlamak.

Yalnız `lane=backfill` iken çalışır. Current/incremental şerit mevcut kaydı
yeniden indirir; silinmiş, başarısız veya parçası olmayan kayıtlar atlanmaz.
Doğrulanmayı bekleyen mevzuat maddeleri içerik olarak hazırdır; HTML tekrar
çekilmez.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# source_type filtresi (CHECK kısıtının üç değeri) tekil indeksin (source_type, external_id)
# kullanılmasını sağlar; olmadan 7M+ satırda her sorgu seq scan olur.
SKIPPABLE_SQL = """
SELECT ls.external_id
FROM legal_sources ls
WHERE ls.deleted_at IS NULL
  AND ls.is_current
  AND ls.source_type IN ('legislation', 'court_decision', 'other')
  AND (
        ls.ingest_status = 'ready'
        OR (
            ls.source_type = 'legislation'
            AND ls.ingest_status = 'pending'
        )
    )
  AND ls.external_id = ANY(%s)
  AND EXISTS (
      SELECT 1
      FROM legal_chunks lc
      WHERE lc.legal_source_id = ls.id
  )
"""

# Üçüncü taraf `bulk_seed` kayıtlar "zaten var" sayılmaz: resmî portaldan yeniden çekilip
# doğrulanmaları (ready'ye yükselmeleri) gerekir; atlanırsa hiç doğrulanmazlar.
HAS_FULLTEXT_SQL = """
SELECT ls.external_id
FROM legal_sources ls
WHERE ls.deleted_at IS NULL
  AND ls.is_current
  AND ls.source_type IN ('legislation', 'court_decision', 'other')
  AND ls.ingestion_method IS DISTINCT FROM 'bulk_seed'
  AND length(coalesce(ls.raw_text, '')) > 80
  AND ls.external_id = ANY(%s)
"""


def skippable_external_ids(
    connection: Any,
    external_ids: Sequence[str],
    *,
    lane: str = "backfill",
) -> set[str]:
    if str(lane or "backfill") != "backfill":
        return set()
    ids = [value for value in external_ids if value]
    if connection is None or not ids:
        return set()
    found = _ids_from(connection, SKIPPABLE_SQL, ids)
    found |= _ids_from(connection, HAS_FULLTEXT_SQL, ids)
    return found


def _ids_from(connection: Any, sql: str, ids: list[str]) -> set[str]:
    rows = _fetchall(connection, sql, (list(ids),))
    found: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            value = row.get("external_id")
        else:
            value = row[0]
        if value:
            found.add(str(value))
    return found


def skipped_existing(extra: dict[str, Any], external_id: str) -> dict[str, Any]:
    return {**extra, "external_id": external_id, "skipped_existing": True}


def _fetchall(connection: Any, sql: str, params: tuple[Any, ...]) -> list[Any]:
    execute = getattr(connection, "execute", None)
    if callable(execute):
        result = execute(sql, params)
        fetchall = getattr(result, "fetchall", None) if result is not None else None
        if callable(fetchall):
            return list(fetchall())
        return []
    cursor_factory = getattr(connection, "cursor", None)
    if not callable(cursor_factory):
        return []
    cursor = cursor_factory()
    try:
        cursor.execute(sql, params)
        return list(cursor.fetchall())
    finally:
        close = getattr(cursor, "close", None)
        if callable(close):
            close()
