"""Bir hesaba platform yöneticisi rolü verir (ilk yöneticiyi atamak için; sonrakiler panelden verilir).

  python scripts/grant_admin.py --email kisi@ornek.com

Yalnız nhr_app (DATABASE_ADMIN_URL) ile çalışır. Hesap yoksa ya da silinmişse hiçbir şey yapmaz. İşlem denetim kaydına
`admin.role_grant` olarak yazılır (yapan: betik); e-posta günlüğe yazılmaz.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL tanımlı değil")
    email = args.email.strip().lower()
    with psycopg.connect(url) as connection, connection.transaction():
        row = connection.execute(
            "SELECT id, status FROM users WHERE lower(email) = %s AND deleted_at IS NULL", (email,)).fetchone()
        if not row:
            print("Bu e-posta ile etkin bir hesap yok", file=sys.stderr)
            return 1
        user_id, status = row
        inserted = connection.execute(
            "INSERT INTO user_roles (user_id, role_id) SELECT %s, id FROM roles WHERE code = 'admin' "
            "ON CONFLICT (user_id, role_id) DO NOTHING", (user_id,)).rowcount
        if inserted:
            connection.execute(
                "INSERT INTO activity_logs (id, actor_user_id, action, entity_type, entity_id, metadata) "
                "VALUES (%s, NULL, 'admin.role_grant', 'user', %s, %s)",
                (uuid4(), user_id, Jsonb({"role": "admin", "method": "script"})))
    print(("Yönetici rolü verildi" if inserted else "Hesap zaten yönetici") + (
        "" if status == "active" else f" (dikkat: hesap durumu '{status}', yönetici yetkisi yalnız aktif hesapta geçerli)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
