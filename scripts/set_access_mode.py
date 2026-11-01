"""Uygulamaya kimlerin girebileceğini ayarlar: herkes (open) ya da yalnız erişim listesi (allowlist); listeye e-posta ekler.

  python scripts/set_access_mode.py --mode allowlist
  python scripts/set_access_mode.py --add avukat@ornek.com --add diger@ornek.com

Panel açılamıyorsa ya da yeni kurulumda doğrudan "yalnız liste" ile başlamak için (sonraki değişiklikler panelden yapılır).
Yalnız nhr_app (DATABASE_ADMIN_URL) ile çalışır. Değişiklik denetim kaydına `admin.access_mode` / `admin.access_add` olarak
yazılır (yapan: betik); e-posta günlüğe yazılmaz. "allowlist"e geçince erişimi kalmayan hesapların açık oturumları kapatılır;
yöneticiler listede olmasa da girer.
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
_AUDIT = ("INSERT INTO activity_logs (id, actor_user_id, action, entity_type, entity_id, metadata) "
          "VALUES (%s, NULL, %s, %s, %s, %s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("open", "allowlist"))
    parser.add_argument("--add", action="append", default=[], metavar="EPOSTA", help="erişim listesine ekle (tekrarlanabilir)")
    args = parser.parse_args()
    if not args.mode and not args.add:
        parser.error("--mode ya da --add verin")
    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL tanımlı değil")
    with psycopg.connect(url) as connection, connection.transaction():
        for raw in args.add:
            email = raw.strip().lower()
            if "@" not in email:
                print(f"Geçersiz e-posta atlandı: {raw}", file=sys.stderr)
                continue
            entry_id = uuid4()
            added = connection.execute(
                "INSERT INTO access_allowlist (id, email) VALUES (%s, %s) ON CONFLICT (email) DO NOTHING",
                (entry_id, email)).rowcount
            if added:
                connection.execute(_AUDIT, (uuid4(), "admin.access_add", "access_entry", entry_id,
                                            Jsonb({"method": "script"})))
            print(("Listeye eklendi: " if added else "Zaten listede: ") + email)
        if args.mode:
            connection.execute(
                "INSERT INTO platform_settings (key, value, updated_by, updated_at) VALUES ('access_mode', %s, NULL, now()) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = NULL, updated_at = now()",
                (args.mode,))
            connection.execute(_AUDIT, (uuid4(), "admin.access_mode", None, None,
                                        Jsonb({"mode": args.mode, "method": "script"})))
            closed = 0
            if args.mode == "allowlist":
                closed = connection.execute(
                    "UPDATE users SET sessions_valid_after = now() "
                    "WHERE deleted_at IS NULL AND NOT public.app_user_access_allowed(id)").rowcount
            print(f"Erişim modu: {args.mode}" + (f" ({closed} hesap artık giremez; açık oturumları kapatıldı)"
                                                 if args.mode == "allowlist" else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
