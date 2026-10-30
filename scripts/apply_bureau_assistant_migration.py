"""Add only Bureau Assistant decision storage; never modify corpus or user records."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import admin_database_connection

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.argv[1:] != ["--apply"]:
        raise SystemExit("Use --apply to add the decision table with owner RLS.")
    with admin_database_connection() as db:
        db.autocommit = True
        db.execute("SET lock_timeout='5s'")
        db.execute("SET statement_timeout='30s'")
        if not db.execute("SELECT to_regclass('public.office_bureau_decisions') AS existing").fetchone()["existing"]:
            source = (ROOT / "database/migrations/063_bureau_assistant.sql").read_text(encoding="utf-8")
            db.execute("\n".join(line for line in source.splitlines() if not line.startswith("\\")))
        row = db.execute("""SELECT relrowsecurity,relforcerowsecurity FROM pg_class
            WHERE oid='public.office_bureau_decisions'::regclass""").fetchone()
        if not row or not row["relrowsecurity"] or not row["relforcerowsecurity"]:
            raise SystemExit("STOP: decision-table RLS could not be verified.")
    print("Bureau decision table ready; RLS and FORCE RLS verified. No existing data changed.")


if __name__ == "__main__":
    main()
