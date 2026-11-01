"""Veri tarafı kapanış denetimi (yalnız okur, hiçbir şey yazmaz): mevzuat + karar korpusu + vektörler.

Her denetim ayrı bağlantıda ve zaman sınırıyla çalışır; biri patlarsa diğerleri sürer. Çıktı tek JSON satırı/denetim.
  python scripts/audit_data_final.py            # hepsi
  python scripts/audit_data_final.py --only legislation_chunks
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from api.config import get_settings  # noqa: E402
from ingestion.mevzuat.text_verify import strip_next_article_caption  # noqa: E402
from ingestion.mevzuat.word_repair import build_vocabulary, rejoin_split_words  # noqa: E402
from ingestion.yargitay.chunking import chunk_text  # noqa: E402

CHECKS: dict = {}


def check(name):
    def wrap(fn):
        CHECKS[name] = fn
        return fn
    return wrap


def scalar(connection, sql, params=()):
    return connection.execute(sql, params).fetchone()["n"]


@check("legislation_basic")
def legislation_basic(c):
    cur = "source_type='legislation' AND deleted_at IS NULL AND is_current AND ingest_status='ready'"
    return {
        "hazır_güncel": scalar(c, f"SELECT count(*) n FROM legal_sources WHERE {cur}"),
        "pending": scalar(c, "SELECT count(*) n FROM legal_sources WHERE source_type='legislation' AND deleted_at IS NULL AND is_current AND ingest_status='pending'"),
        "ayrıntısı_yok": scalar(c, f"SELECT count(*) n FROM legal_sources s WHERE {cur} AND NOT EXISTS (SELECT 1 FROM legislation_details d WHERE d.legal_source_id=s.id)"),
        "parçası_yok": scalar(c, f"SELECT count(*) n FROM legal_sources s WHERE {cur} AND NOT EXISTS (SELECT 1 FROM legal_chunks k WHERE k.legal_source_id=s.id)"),
        "metni_boş_ya_da_kısa(<20)": scalar(c, f"SELECT count(*) n FROM legal_sources WHERE {cur} AND length(coalesce(raw_text,''))<20"),
        "özet_metinle_uyuşmuyor": None,
        "aynı_kimlikte_çok_güncel": scalar(c, "SELECT count(*) n FROM (SELECT d.legislation_identity_id FROM legislation_details d JOIN legal_sources s ON s.id=d.legal_source_id WHERE s.is_current AND s.deleted_at IS NULL AND s.ingest_status='ready' AND s.source_type='legislation' GROUP BY 1 HAVING count(*)>1) x"),
        "kanıtlı_madde(article_hash=hash)": scalar(c, f"SELECT count(*) n FROM legal_sources WHERE {cur} AND metadata->'mbs_text_verification'->>'article_hash' = content_hash"),
        "kanıtlı_ama_özet_farklı": scalar(c, f"SELECT count(*) n FROM legal_sources WHERE {cur} AND metadata->'mbs_text_verification'->>'article_hash' IS NOT NULL AND metadata->'mbs_text_verification'->>'article_hash' <> content_hash"),
    }


@check("legislation_text")
def legislation_text(c):
    from ingestion.text import content_hash
    rows = c.execute("SELECT id, raw_text, content_hash FROM legal_sources WHERE source_type='legislation' AND deleted_at IS NULL AND is_current AND ingest_status='ready' AND raw_text IS NOT NULL").fetchall()
    vocabulary = build_vocabulary(row["raw_text"] for row in rows)
    leak = split = bad_hash = 0
    for row in rows:
        text = row["raw_text"]
        leak += strip_next_article_caption(text) != text
        split += rejoin_split_words(text, vocabulary)[0] != text
        bad_hash += row["content_hash"] != content_hash(text)
    return {"başlık_sızıntısı": leak, "birleştirilebilir_bölünmüş_sözcük": split, "özet_metinle_uyuşmuyor": bad_hash, "kayıt": len(rows)}


@check("legislation_chunks")
def legislation_chunks(c):
    stale = missing = 0
    examples = []
    sources = c.execute("SELECT id, raw_text FROM legal_sources WHERE source_type='legislation' AND deleted_at IS NULL AND is_current AND ingest_status='ready' AND raw_text IS NOT NULL").fetchall()
    for source in sources:
        chunks = [row["content"] for row in c.execute("SELECT content FROM legal_chunks WHERE legal_source_id=%s ORDER BY chunk_index", (source["id"],))]
        if not chunks:
            missing += 1
            continue
        if not any([piece.content for piece in chunk_text(source["raw_text"], max_chars=size)] == chunks for size in (1800, 16000)):
            stale += 1
            if len(examples) < 5:
                examples.append(str(source["id"]))
    return {"parçası_olmayan": missing, "parçaları_metinle_uyuşmayan": stale, "örnek": examples, "kayıt": len(sources)}


@check("legislation_vectors")
def legislation_vectors(c):
    base = "FROM legal_sources s JOIN legal_chunks k ON k.legal_source_id=s.id WHERE s.source_type='legislation' AND s.deleted_at IS NULL AND s.is_current AND s.ingest_status='ready'"
    return {
        "parça": scalar(c, f"SELECT count(*) n {base}"),
        "nomic_vektörsüz": scalar(c, f"SELECT count(*) n {base} AND k.embedding IS NULL"),
        "kopya_tabloda_satırsız": scalar(c, f"SELECT count(*) n {base} AND NOT EXISTS (SELECT 1 FROM legislation_chunk_vectors v WHERE v.chunk_id=k.id)"),
        "m3_vektörsüz": scalar(c, f"SELECT count(*) n {base} AND EXISTS (SELECT 1 FROM legislation_chunk_vectors v WHERE v.chunk_id=k.id AND v.embedding_m3 IS NULL)"),
        "yetim_kopya_satırı": scalar(c, "SELECT count(*) n FROM legislation_chunk_vectors v WHERE NOT EXISTS (SELECT 1 FROM legal_chunks k WHERE k.id=v.chunk_id)"),
    }


@check("decisions_basic")
def decisions_basic(c):
    # 11 milyonluk tablolarda tam sayım zaman aşımına uğrar: %0,1-0,2 örnekleme (oranlar güvenilir, mutlak sayılar değil).
    row = c.execute("""SELECT count(*) AS toplam, count(*) FILTER (WHERE length(coalesce(s.raw_text,''))<200) AS kisa,
        count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM court_decision_details d WHERE d.legal_source_id=s.id)) AS ayrintisiz,
        count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM legal_chunks k WHERE k.legal_source_id=s.id)) AS parcasiz
        FROM legal_sources s TABLESAMPLE SYSTEM (0.1) WHERE s.source_type='court_decision' AND s.deleted_at IS NULL AND s.is_current AND s.ingest_status='ready'""").fetchone()
    detail = c.execute("""SELECT count(*) AS toplam, count(*) FILTER (WHERE coalesce(btrim(court_name),'')='') AS mahkemesiz,
        count(*) FILTER (WHERE coalesce(btrim(docket_no),'')='') AS esassiz, count(*) FILTER (WHERE decision_date IS NULL) AS tarihsiz,
        count(*) FILTER (WHERE decision_date > current_date) AS gelecek FROM court_decision_details TABLESAMPLE SYSTEM (0.2) WHERE is_current""").fetchone()
    return {"örnek_karar": dict(row), "örnek_künye": dict(detail)}


@check("decisions_chunks")
def decisions_chunks(c):
    return {"not": "karar parçası kapsamı decisions_basic örneklemesinde (parcasiz) ölçülür"}


@check("decisions_embedding_backlog")
def decisions_embedding_backlog(c):
    return {"vektörsüz_parça_toplam(yaklaşık)": scalar(c, "SELECT reltuples::bigint n FROM pg_class WHERE relname='legal_chunks'"),
            "not": "gömme kuyruğunun işi; sayım için data/cache/embed_progress.json'a bakın"}


@check("other_sources")
def other_sources(c):
    base = "FROM legal_sources s WHERE s.source_type='other' AND s.deleted_at IS NULL AND s.is_current AND s.ingest_status='ready'"
    return {"hazır": scalar(c, f"SELECT count(*) n {base}"),
            "parçası_olmayan": scalar(c, f"SELECT count(*) n {base} AND NOT EXISTS (SELECT 1 FROM legal_chunks k WHERE k.legal_source_id=s.id)"),
            "metni_kısa(<200)": scalar(c, f"SELECT count(*) n {base} AND length(coalesce(s.raw_text,''))<200")}


@check("orphans")
def orphans(c):
    row = c.execute("SELECT count(*) AS toplam, count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM legal_sources s WHERE s.id=k.legal_source_id)) AS yetim FROM legal_chunks k TABLESAMPLE SYSTEM (0.02)").fetchone()
    return {"örnek_parça": row["toplam"], "kaynağı_olmayan_örnek_parça": row["yetim"]}


@check("caches")
def caches(c):
    out = {}
    for name in ("corpus_stats.json", "embed_progress.json"):
        path = ROOT / "data" / "cache" / name
        out[name] = {"var": path.exists(), "yaş_dk": round((time.time() - path.stat().st_mtime) / 60) if path.exists() else None}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*", help="Yalnız bu denetimler")
    args = parser.parse_args()
    url = get_settings().admin_database_url
    for name, function in CHECKS.items():
        if args.only and name not in args.only:
            continue
        started = time.time()
        try:
            with psycopg.connect(url, row_factory=dict_row, autocommit=True) as connection:
                connection.execute("SET statement_timeout = '900s'")
                result = function(connection)
        except Exception as exc:  # noqa: BLE001
            result = {"HATA": str(exc)[:200]}
        print(json.dumps({"denetim": name, "sn": round(time.time() - started), **result}, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
