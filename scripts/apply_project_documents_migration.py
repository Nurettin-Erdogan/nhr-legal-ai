"""Eklemeli proje-belge migrationı; dosya/sohbet verisi taşımaz veya silmez."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import admin_database_connection

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.argv[1:] != ["--apply"]:
        raise SystemExit(
            "Kullanım: python scripts/apply_project_documents_migration.py --apply"
        )
    migration = (
        ROOT / "database/migrations/054_office_project_documents.sql"
    ).read_text(encoding="utf-8")
    with admin_database_connection() as connection:
        connection.autocommit = True
        connection.execute("SET lock_timeout='5s'")
        connection.execute("SET statement_timeout='30s'")
        connection.execute(
            "\n".join(
                line for line in migration.splitlines() if not line.startswith("\\")
            )
        )
        row = connection.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='office_project_documents'::regclass"
        ).fetchone()
        assert row and row["relrowsecurity"] and row["relforcerowsecurity"]
    print(
        "Proje-belge migrationı uygulandı; RLS/FORCE RLS doğrulandı, mevcut dosyalar korunuyor."
    )


if __name__ == "__main__":
    main()
