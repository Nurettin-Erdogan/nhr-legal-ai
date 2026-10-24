"""Korpus panel sayaçları bakımı (migration 059).

  rebuild  taban sayımı baştan kurar (ilk kurulum / kayma düzeltmesi); saatler değil, dakikalar sürer, diske okuma yükler
  compact  tetikleyicilerin biriktirdiği fark satırlarını tabana katlar (fetcher_hub her turdan sonra çağırır)
  status   güncel sayıları ve bekleyen fark satırı sayısını yazar

Sayılar `corpus_counts()` ile okunur (API de aynısını kullanır); tablo taraması yoktur.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def connect() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_ADMIN_URL"], autocommit=True)


def compact() -> int:
    """Katlanan fark satırı sayısı. Hub her turda çağırır; hata asıl işi bozmasın diye çağıran yutar."""
    with connect() as connection:
        connection.execute("SET statement_timeout = '120s'")
        return int(connection.execute("SELECT corpus_counters_compact()").fetchone()[0])


def rebuild(retries: int = 3) -> None:
    for attempt in range(1, retries + 1):
        try:
            # autocommit kapalı + REPEATABLE READ: sayım anındaki anlık görüntü (işlev bunu zorunlu kılar).
            with psycopg.connect(os.environ["DATABASE_ADMIN_URL"]) as connection:
                connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
                connection.execute("SELECT corpus_counters_rebuild()")
                connection.commit()
            return
        except psycopg.errors.SerializationFailure:
            # Aynı anda katlama fark satırlarını sildiyse: yeniden dene.
            print(f"rebuild: serileştirme çakışması, yeniden deneniyor ({attempt}/{retries})", flush=True)
    raise SystemExit("rebuild başarısız")


def status() -> None:
    with connect() as connection:
        rows = connection.execute("SELECT key, n FROM corpus_counts() ORDER BY key").fetchall()
        deltas = connection.execute("SELECT count(*) FROM corpus_counter_deltas").fetchone()[0]
    for key, n in rows:
        print(f"{key:55s} {n:>12,}")
    print(f"bekleyen fark satırı: {deltas:,}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("rebuild", "compact", "status"))
    args = parser.parse_args()
    if args.command == "rebuild":
        rebuild()
        status()
    elif args.command == "compact":
        print(f"katlandı: {compact():,}")
    else:
        status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
