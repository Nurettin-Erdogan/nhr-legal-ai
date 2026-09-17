"""Kanun bazlı Resmî Gazete + MBS doğrulaması.

Bedesten çekimi her madde için tekrar doğrulamaz. Aynı kanun numarası
bellekte ve, her iki bayrak da true ise, veritabanında cache'lenir.
Bekleyen kanunlar ayrı `mevzuat_verify` worker'ı veya
`scripts/reverify_mevzuat.py` ile tamamlanır.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from psycopg.types.json import Jsonb

from ingestion.mevzuat_bilgi_sistemi.portal import MbsClient, MbsError
from ingestion.resmi_gazete.portal import ResmiGazeteClient, ResmiGazeteError

_STORED_VERIFIED_SQL = """
SELECT ls.metadata
FROM legal_sources ls
JOIN legislation_details d ON d.legal_source_id = ls.id
WHERE ls.source_type = 'legislation'
  AND ls.is_current
  AND ls.deleted_at IS NULL
  AND d.law_no = %s
  AND ls.metadata->>'verified_against_gazette' = 'true'
  AND ls.metadata->>'verified_against_mbs' = 'true'
LIMIT 1
"""

_PENDING_LAWS_SQL = """
SELECT DISTINCT ON (d.legislation_type, d.law_no,
                    d.official_gazette_date, d.official_gazette_no)
       d.legislation_type, d.law_no, d.law_name,
       d.official_gazette_date, d.official_gazette_no,
       ls.metadata
FROM legal_sources ls
JOIN legislation_details d ON d.legal_source_id = ls.id
WHERE ls.source_type = 'legislation' AND ls.is_current
  AND ls.deleted_at IS NULL
  AND (ls.metadata->>'verified_against_gazette' IS DISTINCT FROM 'true'
       OR ls.metadata->>'verified_against_mbs' IS DISTINCT FROM 'true')
ORDER BY d.legislation_type, d.law_no,
         d.official_gazette_date, d.official_gazette_no,
         ls.fetched_at DESC
LIMIT %s
"""

_APPLY_SQL = """
UPDATE legal_sources ls
SET metadata = ls.metadata || %s,
    ingest_status = CASE
        WHEN (ls.metadata || %s)->>'verified_against_gazette' = 'true'
         AND (ls.metadata || %s)->>'verified_against_mbs' = 'true'
        THEN 'ready' ELSE 'pending' END,
    last_verified_at = CASE
        WHEN (ls.metadata || %s)->>'verified_against_gazette' = 'true'
         AND (ls.metadata || %s)->>'verified_against_mbs' = 'true'
        THEN NOW() ELSE ls.last_verified_at END
FROM legislation_details d
WHERE d.legal_source_id = ls.id AND ls.is_current
  AND d.legislation_type = %s AND d.law_no = %s
  AND d.official_gazette_date IS NOT DISTINCT FROM %s
  AND d.official_gazette_no IS NOT DISTINCT FROM %s
"""

VerificationTriple = tuple[dict[str, Any], dict[str, Any], int]


def _metadata_from_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        payload = row.get("metadata")
    else:
        payload = row[0]
    return payload if isinstance(payload, dict) else None


def stored_law_verification(connection: Any, law_no: str) -> VerificationTriple | None:
    if connection is None or not str(law_no or "").strip():
        return None
    try:
        result = connection.execute(_STORED_VERIFIED_SQL, (law_no,))
        row = result.fetchone()
    except Exception:  # noqa: BLE001
        return None
    metadata = _metadata_from_row(row)
    if metadata is None:
        return None
    if (
        metadata.get("verified_against_gazette") is not True
        or metadata.get("verified_against_mbs") is not True
    ):
        return None
    gazette = metadata.get("official_gazette_verification")
    mbs = metadata.get("mbs_verification")
    if not isinstance(gazette, dict):
        gazette = {"verified": True, "law_no": law_no, "detail": "kanun cache"}
    if not isinstance(mbs, dict):
        mbs = {"verified": True, "law_no": law_no, "detail": "kanun cache"}
    return gazette, mbs, 0


def pending_laws(connection: Any, *, limit: int) -> list[dict[str, Any]]:
    result = connection.execute(_PENDING_LAWS_SQL, (max(1, limit),))
    rows = result.fetchall()
    pending: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            pending.append(row)
            continue
        pending.append(
            {
                "legislation_type": row[0],
                "law_no": row[1],
                "law_name": row[2],
                "official_gazette_date": row[3],
                "official_gazette_no": row[4],
                "metadata": row[5] if len(row) > 5 else {},
            }
        )
    return pending


def apply_law_verification(
    connection: Any,
    law: dict[str, Any],
    *,
    flags: dict[str, bool],
    results: dict[str, Any],
) -> None:
    metadata = {**flags, **results}
    connection.execute(
        _APPLY_SQL,
        (Jsonb(metadata),) * 5
        + (
            law["legislation_type"],
            law["law_no"],
            law["official_gazette_date"],
            law["official_gazette_no"],
        ),
    )


def verify_law_against_portals(
    law: dict[str, Any],
    *,
    gazette_client: ResmiGazeteClient,
    mbs_client: MbsClient,
) -> tuple[dict[str, bool], dict[str, Any], int]:
    metadata = law.get("metadata") if isinstance(law.get("metadata"), dict) else {}
    flags = {
        "verified_against_gazette": metadata.get("verified_against_gazette") is True,
        "verified_against_mbs": metadata.get("verified_against_mbs") is True,
    }
    results: dict[str, Any] = {}
    requests_made = 0
    if not flags["verified_against_gazette"]:
        requests_made += 3
        try:
            result = gazette_client.verify_legislation(
                publication_date=law.get("official_gazette_date"),
                issue_no=law.get("official_gazette_no"),
                law_no=law["law_no"],
                law_name=law.get("law_name"),
            ).to_json()
            flags["verified_against_gazette"] = result.get("verified") is True
            results["official_gazette_verification"] = result
        except ResmiGazeteError as exc:
            results["official_gazette_verification"] = {"verified": False, "detail": str(exc)}
    if not flags["verified_against_mbs"]:
        requests_made += 2
        try:
            result = mbs_client.verify_legislation(
                law_no=law["law_no"],
                law_name=law.get("law_name"),
                publication_date=law.get("official_gazette_date"),
                issue_no=law.get("official_gazette_no"),
            ).to_json()
            flags["verified_against_mbs"] = result.get("verified") is True
            results["mbs_verification"] = result
        except MbsError as exc:
            results["mbs_verification"] = {"verified": False, "detail": str(exc)}
    return flags, results, requests_made


def iter_pending_verifications(
    connection: Any,
    *,
    limit: int,
    gazette_client: ResmiGazeteClient,
    mbs_client: MbsClient,
    dry_run: bool = False,
) -> Iterator[dict[str, Any]]:
    laws = pending_laws(connection, limit=limit)
    for law in laws:
        flags, results, requests_made = verify_law_against_portals(
            law,
            gazette_client=gazette_client,
            mbs_client=mbs_client,
        )
        if not dry_run:
            apply_law_verification(connection, law, flags=flags, results=results)
        yield {
            "law_no": law["law_no"],
            "ready": all(flags.values()),
            "flags": flags,
            "results": results,
            "requests_made": requests_made,
        }
