"""Pilot geri bildirimlerini listeler (yönetici bağlantısıyla; kullanıcılar yalnız kendi mesajlarını görür).

    .venv\Scripts\python.exe scripts\list_feedback.py [--category hata] [--since 2026-10-05] [--csv geri-bildirim.csv]

Çıktıda kullanıcının e-postası görünür (kişisel veri): dosyayı paylaşmadan önce gözden geçirin.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]


def admin_url() -> str:
    if os.environ.get("DATABASE_ADMIN_URL"):
        return os.environ["DATABASE_ADMIN_URL"]
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_ADMIN_URL="):
            return line.partition("=")[2].strip().strip('"')
    raise SystemExit("DATABASE_ADMIN_URL bulunamadı")


def fetch(url: str, category: str | None, since: str | None) -> list[dict]:
    with psycopg.connect(url, row_factory=dict_row) as connection:
        return connection.execute(
            "SELECT f.created_at, f.category, f.page, f.message, u.email, u.full_name "
            "FROM office_feedback f JOIN users u ON u.id = f.owner_id "
            "WHERE (%s::text IS NULL OR f.category = %s) AND (%s::date IS NULL OR f.created_at >= %s::date) "
            "ORDER BY f.created_at DESC",
            (category, category, since, since),
        ).fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--category", choices=["hata", "oneri", "begeni"])
    parser.add_argument("--since", help="YYYY-MM-DD")
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args()
    rows = fetch(admin_url(), args.category, args.since)
    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["tarih", "tür", "sayfa", "mesaj", "e-posta", "ad"])
            writer.writerows([row["created_at"].isoformat(), row["category"], row["page"], row["message"], row["email"], row["full_name"]] for row in rows)
        print(f"{len(rows)} kayıt yazıldı: {args.csv}")
        return 0
    for row in rows:
        print(f"[{row['created_at']:%d.%m.%Y %H:%M}] {row['category']:6} {row['page'] or '-':32} {row['full_name']} <{row['email']}>\n    {row['message']}")
    print(f"\n{len(rows)} geri bildirim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
