"""Yalnız kalıcı belge kuyruğunun idempotent şema migrationını uygular; belge verisini silmez."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import admin_database_connection

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.argv[1:] != ["--apply"]:
        raise SystemExit(
            "Kullanım: python scripts/apply_document_jobs_migration.py --apply"
        )
    sql = (ROOT / "database/migrations/052_document_jobs.sql").read_text(
        encoding="utf-8"
    )
    sql = "\n".join(line for line in sql.splitlines() if not line.startswith("\\"))
    with admin_database_connection() as connection:
        connection.autocommit = True
        connection.execute(sql)
        row = connection.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='office_document_jobs'::regclass"
        ).fetchone()
        if not row or not row["relrowsecurity"] or not row["relforcerowsecurity"]:
            raise SystemExit("Migration sonrası RLS doğrulanamadı.")
    print("Belge kuyruğu migrationı uygulandı; RLS ve FORCE RLS doğrulandı.")


if __name__ == "__main__":
    main()
