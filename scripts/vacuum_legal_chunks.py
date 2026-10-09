"""legal_chunks için VACUUM (INDEX_CLEANUP OFF): yalnız görünürlük haritasını (all-visible) onarır, indeksleri taramaz.

Neden: embedding'i yeni yazılan satırların sayfaları all-visible değil (relallvisible 5,80M / relpages 6,09M), bu yüzden
`SELECT count(*) ... WHERE embedding IS NOT NULL` dizin-yalnız taramasında her satır için heap'e iniyor (4-5 dk, işlemci %100)
ve arama/asistan yavaşlıyor. Okuma/yazmayı engellemez (ShareUpdateExclusive); 31 GB GIN + 12 GB HNSW'ye dokunmaz.
"""
import os
import time

import psycopg
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, ".env"))

started = time.time()
with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], autocommit=True) as connection:
    connection.execute("SET statement_timeout = 0")
    connection.execute("SET vacuum_cost_delay = 0")
    print("VACUUM başladı", flush=True)
    connection.execute("VACUUM (INDEX_CLEANUP OFF, TRUNCATE OFF) legal_chunks")
    row = connection.execute(
        "SELECT relallvisible, relpages FROM pg_class WHERE relname = 'legal_chunks'"
    ).fetchone()
    print(f"VACUUM bitti: {(time.time() - started) / 60:.1f} dk | relallvisible {row[0]:,} / relpages {row[1]:,}", flush=True)
