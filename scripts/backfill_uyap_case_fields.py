"""Kayıtlı UYAP dosya bilgilerinden dava listesindeki boş "Tür" ve "Karşı taraf" alanlarını doldurur (dolu alan ezilmez).

  python scripts/backfill_uyap_case_fields.py [--dry-run]

nhr_app (DATABASE_ADMIN_URL) ile çalışır; yalnız mevcut `office_uyap_case_detail` kayıtlarını okur ve `office_cases.case_type/opponent`
alanlarını NULL ise yazar. Kurallar: api/uyap_case_fields.py. Yeni aktarımlar aynı kuralı `api.uyap_detail` içinde uygular.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from api import uyap_case_fields  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], row_factory=dict_row) as connection:
        accounts: dict[str, list[str]] = {}
        for row in connection.execute("SELECT owner_id::text AS owner, display_name FROM office_uyap_accounts"):
            if row["display_name"]:
                accounts.setdefault(row["owner"], []).append(row["display_name"])
        rows = connection.execute(
            "SELECT d.case_id, d.owner_id AS owner, d.tabs FROM office_uyap_case_detail d JOIN office_cases c ON c.id = d.case_id"
        ).fetchall()
        totals = {"type": 0, "opponent": 0, "client": 0, "title": 0, "status": 0, "client_created": 0}
        for row in rows:
            changed = uyap_case_fields.apply_fields(connection, row["owner"], row["case_id"], row["tabs"], accounts.get(str(row["owner"]), []))
            for key, value in changed.items():
                totals[key] += bool(value)
        if args.dry_run:
            connection.rollback()
    print(f"{len(rows)} dava incelendi; doldurulan: {totals}" + (" (deneme, yazılmadı)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
