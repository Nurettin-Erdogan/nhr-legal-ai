"""Bir kaynağın (yargitay/danistay) bizde olan kararlarını "tarih<TAB>id" olarak .gz dosyaya yazar.

Çıktı, başka bir makinedeki `collect_bedesten.py --known-file` için kullanılır: o makinenin
veritabanında tohum yoksa toplayıcı portalın tamamını yeniden indirirdi.
"""
import argparse
import gzip
import os
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, ".env"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="yargitay")
    parser.add_argument("--from-year", type=int, default=2000)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        sys.exit("DATABASE_ADMIN_URL tanımlı değil")
    prefix = f"{args.source}:"
    sql = (
        "COPY (SELECT d.decision_date, substr(ls.external_id, %d) FROM court_decision_details d "
        "JOIN legal_sources ls ON ls.id = d.legal_source_id "
        "WHERE ls.external_id LIKE '%s%%' AND ls.is_current AND ls.deleted_at IS NULL "
        "AND d.decision_date >= '%d-01-01') TO STDOUT"
    ) % (len(prefix) + 1, prefix, args.from_year)
    rows = 0
    with psycopg.connect(url) as connection, connection.cursor() as cursor, gzip.open(args.out, "wb") as out:
        with cursor.copy(sql) as copy:
            for chunk in copy:
                out.write(bytes(chunk))
                rows += bytes(chunk).count(b"\n")
    print(f"yazıldı: {args.out} satır={rows}")


if __name__ == "__main__":
    main()
