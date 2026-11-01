"""Doğrulanmamış (bulk_seed, pending) kararlardan rastgele örneklem alır ve dosyaya yazar (veritabanına YAZMAZ).

Örneklem Azure'da `seed_sample_check.py` ile resmî portala karşı denetlenir (Azure'ın veritabanında seed yok; kayıtlar dosyayla taşınır).
Blok örneklemesi (TABLESAMPLE SYSTEM) önce yalnız kimlikleri seçer, sonra Python'da rastgele altküme alınır; böylece
yan yana duran kayıtların oluşturduğu kümelenme azalır.

  python scripts/seed_sample_export.py --n 2500 --out data/eval/seed-sample.jsonl.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

_IDS = """
SELECT ls.id, ls.external_id
FROM legal_sources ls TABLESAMPLE SYSTEM (%(pct)s)
WHERE ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending' AND ls.is_current
  AND ls.deleted_at IS NULL AND ls.source_type = 'court_decision'
  AND ls.metadata->>'verify_status' IS NULL AND ls.external_id ~ '^(yargitay|danistay):'
"""

_ROWS = """
SELECT ls.id, ls.external_id, d.decision_date, ls.raw_text
FROM legal_sources ls LEFT JOIN court_decision_details d ON d.legal_source_id = ls.id
WHERE ls.id = ANY(%s)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=2500)
    parser.add_argument("--pct", type=float, default=0.6, help="blok örnekleme yüzdesi (kimlik havuzu)")
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--out", default=str(ROOT / "data" / "eval" / "seed-sample.jsonl.gz"))
    args = parser.parse_args()
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL tanımlı değil")
    rng = random.Random(args.seed)
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("SET statement_timeout = '10min'")
        pool = connection.execute(_IDS, {"pct": args.pct}).fetchall()
        print(f"kimlik havuzu: {len(pool)}", flush=True)
        if len(pool) < args.n:
            raise SystemExit("havuz küçük; --pct değerini artırın")
        chosen = rng.sample(pool, args.n)
        by_id = {row[0]: row[1] for row in chosen}
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        counts: dict[str, int] = {}
        with gzip.open(out, "wt", encoding="utf-8") as handle:
            ids = list(by_id)
            for start in range(0, len(ids), 200):
                for _id, external_id, decision_date, raw_text in connection.execute(_ROWS, (ids[start:start + 200],)).fetchall():
                    source = external_id.split(":", 1)[0]
                    counts[source] = counts.get(source, 0) + 1
                    handle.write(json.dumps({
                        "id": str(_id), "external_id": external_id,
                        "decision_date": decision_date.isoformat() if decision_date else None,
                        "text": raw_text or "",
                    }, ensure_ascii=False) + "\n")
                    written += 1
    print(f"yazıldı: {written} kayıt → {out} | kaynak dağılımı: {counts}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
