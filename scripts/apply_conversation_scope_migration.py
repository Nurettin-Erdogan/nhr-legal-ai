"""Sohbet kapsamını ekler; eski sohbetleri tahminle bir davaya bağlamaz, veri silmez."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from api.db import admin_database_connection


def main():
    if sys.argv[1:] != ['--apply']:
        raise SystemExit('Kullanım: python scripts/apply_conversation_scope_migration.py --apply')
    migration = (ROOT / 'database/migrations/053_conversation_workspace_scope.sql').read_text(encoding='utf-8')
    with admin_database_connection() as connection:
        connection.autocommit = True
        connection.execute("SET lock_timeout='5s'")
        connection.execute("SET statement_timeout='30s'")
        connection.execute('\n'.join(line for line in migration.splitlines() if not line.startswith('\\')))
        row = connection.execute("SELECT relrowsecurity FROM pg_class WHERE oid='conversations'::regclass").fetchone()
        if not row or not row['relrowsecurity']:
            raise SystemExit('Conversation RLS doğrulanamadı.')
    print('Sohbet kapsamı migrationı uygulandı; mevcut RLS ve eski sohbetler korundu.')


if __name__ == '__main__':
    main()
