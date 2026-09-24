"""Read-only, year-level corpus coverage check against a saved portal snapshot.

This is a prioritisation aid, not an exact ID-level set difference. It never
contacts a court portal or modifies the database.

    python scripts/gap_inventory.py --years 2025 2026
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
PORTAL_SNAPSHOT = ROOT / "data" / "campaign" / "coverage-portal.json"


def compare_counts(
    portal: dict[str, dict[str, int | str]],
    database: dict[tuple[str, int], int],
    years: list[int],
) -> list[dict[str, int | str | None]]:
    rows: list[dict[str, int | str | None]] = []
    for source in ("yargitay", "danistay"):
        for year in years:
            portal_count = portal.get(source, {}).get(str(year))
            db_count = database.get((source, year), 0)
            rows.append(
                {
                    "source": source,
                    "year": year,
                    "portal_snapshot": portal_count if isinstance(portal_count, int) else None,
                    "database_now": db_count,
                    "count_difference": max(portal_count - db_count, 0)
                    if isinstance(portal_count, int)
                    else None,
                }
            )
    return sorted(rows, key=lambda row: row["count_difference"] or 0, reverse=True)


def database_counts(database_url: str, years: list[int]) -> dict[tuple[str, int], int]:
    result: dict[tuple[str, int], int] = {}
    with psycopg.connect(database_url) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute("SET LOCAL statement_timeout = '30s'")
        rows = connection.execute(
            """
            SELECT CASE
                     WHEN d.court_name ILIKE 'Yargıtay%%' OR d.court_name ILIKE 'Yargitay%%' THEN 'yargitay'
                     WHEN d.court_name ILIKE 'Danıştay%%' OR d.court_name ILIKE 'Danistay%%' THEN 'danistay'
                   END AS source,
                   EXTRACT(YEAR FROM d.decision_date)::int AS year,
                   count(*) AS records
            FROM court_decision_details d
            JOIN legal_sources s ON s.id = d.legal_source_id
            WHERE d.decision_date >= make_date(%s, 1, 1)
              AND d.decision_date < make_date(%s, 1, 1)
              AND s.is_current AND s.deleted_at IS NULL
              AND s.source_type = 'court_decision'
            GROUP BY 1, 2
            """,
            (min(years), max(years) + 1),
        ).fetchall()
        for source, year, count in rows:
            if source is not None and year in years:
                result[(source, year)] = count
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="+", type=int, default=[2025, 2026])
    args = parser.parse_args()
    years = sorted(set(args.years))
    if not years or min(years) < 1900 or max(years) > datetime.now(timezone.utc).year:
        parser.error("years must be between 1900 and the current year")
    load_dotenv(ROOT / ".env")
    database_url = os.getenv("DATABASE_ADMIN_URL")
    if not database_url:
        parser.error("DATABASE_ADMIN_URL is required")
    portal = json.loads(PORTAL_SNAPSHOT.read_text(encoding="utf-8"))
    counts = database_counts(database_url, years)
    print(f"Portal snapshot: {datetime.fromtimestamp(PORTAL_SNAPSHOT.stat().st_mtime, timezone.utc).isoformat()}")
    print("SOURCE    YEAR  PORTAL(SNAPSHOT)  DB(NOW)  COUNT DIFFERENCE")
    for row in compare_counts(portal, counts, years):
        print(
            f"{row['source']:<10}{row['year']:<6}"
            f"{str(row['portal_snapshot']):>16}"
            f"{row['database_now']:>9}"
            f"{str(row['count_difference']):>18}"
        )
    print("Count differences are NOT exact missing IDs; portal totals may be stale or differently scoped.")


if __name__ == "__main__":
    main()
