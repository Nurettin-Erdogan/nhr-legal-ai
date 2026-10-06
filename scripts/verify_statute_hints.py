"""Konu → madde ipucu tablosunu (api/statute_hints.py) korpustaki resmî metne karşı doğrular (salt okunur).

Her satır için: madde korpusta resmî doğrulanmış ve güncel mi, metni beklenen sözcükleri içeriyor mu. Sorunlu satır varsa çıkış
kodu 1 olur. Tabloya satır eklendiğinde ya da mevzuat yeniden aktarıldığında çalıştırın:

    .venv\\Scripts\\python.exe scripts\\verify_statute_hints.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api import statute_hints  # noqa: E402


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    sys.stdout.reconfigure(encoding="utf-8")
    bad = 0
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], row_factory=dict_row) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        for topic in statute_hints.TOPICS:
            for hint in topic.hints:
                row = connection.execute(statute_hints._SQL, {"law_no": hint.law_no, "article_no": hint.article_no}).fetchone()
                if row is None:
                    bad += 1
                    print(f"YOK        {topic.name}: {hint.law_no}/{hint.article_no}")
                    continue
                ok = statute_hints.text_matches(hint, row["content"] or "")
                bad += not ok
                head = " ".join((row["content"] or "").split())[:110]
                print(f"{'OK        ' if ok else 'UYUŞMUYOR '} {topic.name}: {row['law_name'][:30]} ({hint.law_no}) m.{hint.article_no} | {head}")
    print(f"sorunlu satır: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
