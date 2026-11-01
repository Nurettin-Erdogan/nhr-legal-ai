"""Retry pending legislation checks against the two observed official portals.

Run sparingly alongside the collector: one law is checked at a time, never
promoted on an HTTP failure, ambiguous match, or a single-source match.

`python -m worker.runner run --source mevzuat_verify` aynı işi worker olarak yapar.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from ingestion.mevzuat.official_verify import iter_pending_verifications
from ingestion.mevzuat_bilgi_sistemi.portal import MbsClient
from ingestion.resmi_gazete.portal import ResmiGazeteClient


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
        remaining = args.max_laws
        for attempt in range(1, args.attempts + 1):
            batch = list(
                iter_pending_verifications(
                    connection,
                    limit=remaining,
                    gazette_client=gazette,
                    mbs_client=mbs,
                )
            )
            if not batch:
                break
            for index, item in enumerate(batch):
                print(f"{item['law_no']}: {'ready' if item['ready'] else 'pending'}")
                if index + 1 < len(batch):
                    time.sleep(args.delay)
            remaining = sum(1 for item in batch if not item["ready"])
            if remaining == 0 or attempt == args.attempts:
                break
            time.sleep(args.delay)


if __name__ == "__main__":
    main()
