"""Retry pending legislation checks against the two observed official portals.

Run sparingly alongside the collector: one law is checked at a time, never
promoted on an HTTP failure, ambiguous match, or a single-source match.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ingestion.mevzuat_bilgi_sistemi.portal import MbsClient, MbsError
from ingestion.resmi_gazete.portal import ResmiGazeteClient, ResmiGazeteError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-laws", type=int, default=3)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--delay", type=float, default=8.0)
    args = parser.parse_args()
    if args.max_laws < 1 or args.attempts not in (1, 2, 3) or args.delay < 1:
        parser.error("--max-laws >= 1, --attempts 1..3 ve --delay >= 1 gerekli")

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        parser.error("DATABASE_ADMIN_URL gerekli")
    gazette = ResmiGazeteClient(max_retries=2)
    mbs = MbsClient(max_retries=2)

    with psycopg.connect(url, row_factory=dict_row, autocommit=True) as connection:
        laws = connection.execute(
            """
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
            """,
            (args.max_laws,),
        ).fetchall()
        for index, law in enumerate(laws):
            flags = {
                "verified_against_gazette": law["metadata"].get("verified_against_gazette") is True,
                "verified_against_mbs": law["metadata"].get("verified_against_mbs") is True,
            }
            results = {}
            for attempt in range(1, args.attempts + 1):
                if not flags["verified_against_gazette"]:
                    try:
                        result = gazette.verify_legislation(
                            publication_date=law["official_gazette_date"],
                            issue_no=law["official_gazette_no"],
                            law_no=law["law_no"],
                            law_name=law["law_name"],
                        ).to_json()
                        flags["verified_against_gazette"] = result["verified"] is True
                        results["official_gazette_verification"] = result
                    except ResmiGazeteError as exc:
                        results["official_gazette_verification"] = {"verified": False, "detail": str(exc)}
                if not flags["verified_against_mbs"]:
                    try:
                        result = mbs.verify_legislation(
                            law_no=law["law_no"],
                            law_name=law["law_name"],
                            publication_date=law["official_gazette_date"],
                            issue_no=law["official_gazette_no"],
                        ).to_json()
                        flags["verified_against_mbs"] = result["verified"] is True
                        results["mbs_verification"] = result
                    except MbsError as exc:
                        results["mbs_verification"] = {"verified": False, "detail": str(exc)}
                if all(flags.values()):
                    break
                if attempt < args.attempts:
                    time.sleep(args.delay)
            metadata = {**flags, **results}
            with connection.transaction():
                connection.execute(
                    """
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
                    """,
                    (Jsonb(metadata),) * 5
                    + (law["legislation_type"], law["law_no"],
                       law["official_gazette_date"], law["official_gazette_no"]),
                )
            print(f"{law['law_no']}: {'ready' if all(flags.values()) else 'pending'}")
            if index + 1 < len(laws):
                time.sleep(args.delay)


if __name__ == "__main__":
    main()
