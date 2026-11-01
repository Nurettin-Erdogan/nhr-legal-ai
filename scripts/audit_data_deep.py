"""Derin veri denetimi (yalnız okur): mevzuat, kararlar, diğer kaynaklar ve parçalar. Hiçbir şey yazmaz.

Her denetim ayrı bağlantıda, zaman sınırıyla çalışır; biri patlarsa diğerleri sürer. Büyük tablolarda (karar: 11 milyon) örnekleme
kullanılır (oranlar güvenilir, mutlak sayılar değil). Çıktı: denetim başına bir JSON satırı (+ örnekler).

  python scripts/audit_data_deep.py                      # hepsi
  python scripts/audit_data_deep.py --only leg_identity leg_gaps
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from api.config import get_settings  # noqa: E402
from ingestion.mevzuat.identity import canonical_article, primary_article  # noqa: E402

CHECKS: dict = {}
LEG = "s.source_type='legislation' AND s.deleted_at IS NULL AND s.is_current AND s.ingest_status='ready'"
DEC = "s.source_type='court_decision' AND s.deleted_at IS NULL AND s.is_current AND s.ingest_status='ready'"

PATTERNS = {
    "yerine_koyma_karakteri(\\ufffd)": re.compile("�"),
    "bozuk_utf8(Ã/Ä/Å)": re.compile(r"[ÃÄÅ][\u0080-¿¡-¿]"),
    "html_etiketi": re.compile(r"</?(?:p|br|div|span|b|i|u|table|tr|td|font|a|li|ul|strong|em|h\d)\b[^>]*>", re.I),
    "html_varlığı(&nbsp; vb.)": re.compile(r"&(?:nbsp|amp|lt|gt|quot|#\d+|[a-z]{2,6});", re.I),
    "kontrol_karakteri": re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"),
    "sıfır_genişlik/NBSP": re.compile("[​‌‍﻿ ]"),
    "çok_boşluk(5+)": re.compile(r" {5,}"),
    "ardışık_boş_satır(4+)": re.compile(r"\n{5,}"),
}


def check(name):
    def wrap(fn):
        CHECKS[name] = fn
        return fn
    return wrap


def one(connection, sql, params=()):
    return connection.execute(sql, params).fetchone()


def scan_text(rows, key="raw_text"):
    counts: collections.Counter = collections.Counter()
    examples: dict[str, list] = collections.defaultdict(list)
    total = doubled = empty = very_long = 0
    for row in rows:
        text = row[key] or ""
        total += 1
        if not text.strip():
            empty += 1
            continue
        if len(text) > 400_000:
            very_long += 1
        half = len(text) // 2
        if len(text) > 400 and text[:half].strip() == text[half:].strip():
            doubled += 1
        for name, pattern in PATTERNS.items():
            match = pattern.search(text)
            if match:
                counts[name] += 1
                if len(examples[name]) < 3:
                    start = max(match.start() - 30, 0)
                    examples[name].append(f"{row.get('id')}: …{text[start:match.end() + 30]!r}")
    return {"kayıt": total, "boş": empty, "çok_uzun(>400k)": very_long, "metin_ikilenmiş": doubled,
            **{name: counts[name] for name in PATTERNS}, "örnekler": {k: v for k, v in examples.items()}}


@check("leg_dup_identity")
def leg_dup_identity(c):
    return {
        "aynı_kimlikte_çok_güncel": one(c, f"SELECT count(*) n FROM (SELECT d.legislation_identity_id FROM legislation_details d JOIN legal_sources s ON s.id=d.legal_source_id WHERE {LEG} GROUP BY 1 HAVING count(*)>1) x")["n"],
        "aynı_kanun_ve_madde_birden_çok_kayıt": one(c, f"SELECT count(*) n FROM (SELECT d.law_no, d.article_no, d.legislation_type FROM legislation_details d JOIN legal_sources s ON s.id=d.legal_source_id WHERE {LEG} GROUP BY 1,2,3 HAVING count(*)>1) x")["n"],
        "aynı_external_id_çok_güncel": one(c, f"SELECT count(*) n FROM (SELECT s.external_id FROM legal_sources s WHERE {LEG} AND s.external_id IS NOT NULL GROUP BY 1 HAVING count(*)>1) x")["n"],
        "aynı_metin_özeti_farklı_maddeler": one(c, f"SELECT count(*) n FROM (SELECT s.content_hash FROM legal_sources s WHERE {LEG} AND s.content_hash IS NOT NULL GROUP BY 1 HAVING count(DISTINCT s.external_id)>1) x")["n"],
    }


@check("leg_identity")
def leg_identity(c):
    """Madde numarası ile metnin kendi başlığı ("Madde 18 -") uyuşuyor mu; başlık ("... m. N") ayrıntıyla uyuşuyor mu."""
    mismatch = no_heading = title_bad = total = 0
    examples = []
    with c.transaction():
        with c.cursor(name="ident_scan") as scan:
            scan.itersize = 500
            scan.execute(f"SELECT s.id, s.title, s.raw_text, d.article_no, d.law_no FROM legal_sources s JOIN legislation_details d ON d.legal_source_id=s.id WHERE {LEG}")
            for row in scan:
                total += 1
                primary = primary_article(row["raw_text"] or "")
                wanted = canonical_article(row["article_no"] or "")
                if not primary:
                    no_heading += 1
                elif primary != wanted:
                    mismatch += 1
                    if len(examples) < 8:
                        examples.append({"id": str(row["id"]), "title": row["title"][-60:], "madde_no": row["article_no"], "metin_başlığı": primary})
                title_match = re.search(r"\bm\.\s*([0-9A-Za-z/]+)", row["title"] or "")
                if title_match and canonical_article(title_match.group(1)) != wanted:
                    title_bad += 1
    return {"kayıt": total, "metin_başlığı_yok": no_heading, "madde_no_ile_metin_başlığı_uyuşmuyor": mismatch, "başlık_ile_madde_no_uyuşmuyor": title_bad, "örnekler": examples}


@check("leg_gaps")
def leg_gaps(c):
    """Kanun içinde 1..en yüksek madde numarası arasında eksik numara (yalnız sayısal ana maddeler; ek/geçici maddeler hariç)."""
    rows = c.execute(f"SELECT d.law_no, max(d.law_name) AS name, d.legislation_type, array_agg(d.article_no) AS arts FROM legislation_details d JOIN legal_sources s ON s.id=d.legal_source_id WHERE {LEG} GROUP BY d.law_no, d.legislation_type").fetchall()
    laws_with_gaps = 0
    missing_total = 0
    worst = []
    for row in rows:
        numbers = set()
        for article in row["arts"]:
            if article and re.fullmatch(r"\d{1,4}", article.strip()):
                numbers.add(int(article))
        if len(numbers) < 5:
            continue
        top = max(numbers)
        if top > 3000:
            continue
        missing = [i for i in range(1, top + 1) if i not in numbers]
        if missing:
            laws_with_gaps += 1
            missing_total += len(missing)
            worst.append((len(missing), row["law_no"], row["name"][:50], missing[:6], top))
    worst.sort(reverse=True)
    return {"incelenen_kanun": len(rows), "eksik_numaralı_kanun": laws_with_gaps, "toplam_eksik_numara": missing_total,
            "en_çok_eksik": [{"eksik": w[0], "kanun": w[1], "ad": w[2], "ilk_eksikler": w[3], "en_yüksek": w[4]} for w in worst[:12]]}


@check("leg_text_quality")
def leg_text_quality(c):
    with c.transaction():
        with c.cursor(name="text_scan") as scan:
            scan.itersize = 400
            scan.execute(f"SELECT s.id, s.raw_text FROM legal_sources s WHERE {LEG} AND s.raw_text IS NOT NULL")
            return scan_text(scan)


@check("leg_names_types")
def leg_names_types(c):
    names = c.execute(f"SELECT d.law_no, count(DISTINCT regexp_replace(lower(d.law_name), '\\s+', ' ', 'g')) AS n FROM legislation_details d JOIN legal_sources s ON s.id=d.legal_source_id WHERE {LEG} GROUP BY d.law_no HAVING count(DISTINCT regexp_replace(lower(d.law_name), '\\s+', ' ', 'g')) > 1 LIMIT 40").fetchall()
    types = c.execute(f"SELECT d.law_no, count(DISTINCT d.legislation_type) AS n FROM legislation_details d JOIN legal_sources s ON s.id=d.legal_source_id WHERE {LEG} GROUP BY d.law_no HAVING count(DISTINCT d.legislation_type) > 1 LIMIT 40").fetchall()
    empty_name = one(c, f"SELECT count(*) n FROM legislation_details d JOIN legal_sources s ON s.id=d.legal_source_id WHERE {LEG} AND coalesce(btrim(d.law_name),'')=''")["n"]
    return {"kanun_numarası_başına_birden_çok_ad": len(names), "örnek_ad": [r["law_no"] for r in names[:8]],
            "birden_çok_tür": len(types), "örnek_tür": [r["law_no"] for r in types[:8]], "adı_boş": empty_name}


@check("leg_dates_flags")
def leg_dates_flags(c):
    today = date.today()
    return {
        "resmî_gazete_tarihi_gelecekte": one(c, f"SELECT count(*) n FROM legislation_details d JOIN legal_sources s ON s.id=d.legal_source_id WHERE {LEG} AND d.official_gazette_date > %s", (today,))["n"],
        "resmî_gazete_tarihi_1800_öncesi": one(c, f"SELECT count(*) n FROM legislation_details d JOIN legal_sources s ON s.id=d.legal_source_id WHERE {LEG} AND d.official_gazette_date < '1800-01-01'")["n"],
        "yürürlük_bitişi_başlangıçtan_önce": one(c, f"SELECT count(*) n FROM legal_sources s WHERE {LEG} AND s.effective_from IS NOT NULL AND s.effective_to IS NOT NULL AND s.effective_to < s.effective_from")["n"],
        "doğrulama_bayrağı_hiç_yok": one(c, f"SELECT count(*) n FROM legal_sources s WHERE {LEG} AND coalesce(s.metadata->>'verified_against_mbs','')<>'true' AND coalesce(s.metadata->>'verified_against_gazette','')<>'true'")["n"],
        "kaynak_adresi_resmî_değil": one(c, f"SELECT count(*) n FROM legal_sources s WHERE {LEG} AND coalesce(s.source_url,'') NOT LIKE 'https://www.mevzuat.gov.tr/%%'")["n"],
        "çöpe_giden_güncel_olmayan_ama_hazır_görünen": one(c, "SELECT count(*) n FROM legal_sources s WHERE s.source_type='legislation' AND s.deleted_at IS NOT NULL AND s.ingest_status='ready' AND s.is_current")["n"],
    }


@check("chunk_integrity")
def chunk_integrity(c):
    """Parça bütünlüğü (%0,05 örnek + mevzuat tam): boş içerik, özet eksik, yinelenen sıra, boyut."""
    sample = one(c, """SELECT count(*) AS n, count(*) FILTER (WHERE coalesce(btrim(content),'')='') AS bos,
        count(*) FILTER (WHERE content_hash IS NULL) AS ozetsiz, count(*) FILTER (WHERE embedding IS NOT NULL AND vector_dims(embedding)<>768) AS boyut,
        count(*) FILTER (WHERE length(content) > 60000) AS cok_uzun FROM legal_chunks TABLESAMPLE SYSTEM (0.05)""")
    dup = one(c, "SELECT count(*) n FROM (SELECT legal_source_id, chunk_index FROM legal_chunks TABLESAMPLE SYSTEM (0.2) GROUP BY 1,2 HAVING count(*)>1) x")["n"]
    leg_dup = one(c, f"SELECT count(*) n FROM (SELECT k.legal_source_id, k.chunk_index FROM legal_chunks k JOIN legal_sources s ON s.id=k.legal_source_id WHERE {LEG} GROUP BY 1,2 HAVING count(*)>1) x")["n"]
    return {"örnek_parça": sample["n"], "boş_içerik": sample["bos"], "özeti_yok": sample["ozetsiz"], "vektör_boyutu_hatalı": sample["boyut"],
            "aşırı_uzun(>60k)": sample["cok_uzun"], "örnekte_yinelenen_sıra": dup, "mevzuatta_yinelenen_sıra": leg_dup}


@check("dec_sample_quality")
def dec_sample_quality(c):
    with c.transaction():
        with c.cursor(name="dec_scan") as scan:
            scan.itersize = 200
            scan.execute(f"SELECT s.id, s.raw_text FROM legal_sources s TABLESAMPLE SYSTEM (0.08) WHERE {DEC} AND s.raw_text IS NOT NULL")
            result = scan_text(scan)
    result["not"] = "karar örneklemesi (~%0,08)"
    return result


@check("dec_sample_meta")
def dec_sample_meta(c):
    row = one(c, f"""SELECT count(*) n,
        count(*) FILTER (WHERE d.decision_date IS NULL) tarihsiz,
        count(*) FILTER (WHERE d.decision_date > current_date) gelecek,
        count(*) FILTER (WHERE d.decision_date < '1900-01-01') eski,
        count(*) FILTER (WHERE coalesce(btrim(d.court_name),'')='') mahkemesiz,
        count(*) FILTER (WHERE coalesce(btrim(d.docket_no),'')='') esassiz,
        count(*) FILTER (WHERE coalesce(btrim(d.decision_no),'')='') kararsiz,
        count(*) FILTER (WHERE d.decision_no !~ '^\\s*\\d{{4}}\\s*/\\s*\\d+') bozuk_karar_no,
        count(*) FILTER (WHERE d.docket_no !~ '^\\s*\\d{{4}}\\s*/\\s*\\d+') bozuk_esas_no,
        count(*) FILTER (WHERE s.source_url IS NULL OR s.source_url NOT LIKE 'https://%%') adressiz,
        count(*) FILTER (WHERE s.ingestion_method = 'bulk_seed') seed
        FROM legal_sources s TABLESAMPLE SYSTEM (0.15) JOIN court_decision_details d ON d.legal_source_id=s.id WHERE {DEC}""")
    return {"örnek": row["n"], **{k: v for k, v in row.items() if k != "n"}}


@check("dec_court_names")
def dec_court_names(c):
    rows = c.execute("SELECT court_name, count(*) n FROM court_decision_details TABLESAMPLE SYSTEM (0.3) WHERE is_current GROUP BY 1 ORDER BY 2 DESC").fetchall()
    folded = collections.defaultdict(set)
    for row in rows:
        folded[re.sub(r"\W+", "", (row["court_name"] or "").lower().replace("ı", "i"))].add(row["court_name"])
    variants = [sorted(v) for v in folded.values() if len(v) > 1]
    return {"farklı_mahkeme_adı(örnek)": len(rows), "yalnız_biçimce_ayrışan_ad_grupları": len(variants), "örnekler": variants[:8], "en_sık": [(r["court_name"], r["n"]) for r in rows[:8]]}


@check("dec_duplicates")
def dec_duplicates(c):
    c.execute("SET statement_timeout = '1500s'")
    rows = c.execute("SELECT court_name, chamber, docket_no, decision_no, count(*) n FROM court_decision_details WHERE is_current AND decision_no IS NOT NULL AND docket_no IS NOT NULL GROUP BY 1,2,3,4 HAVING count(*)>1 ORDER BY n DESC LIMIT 25").fetchall()
    return {"aynı_künyeli_çoklu_güncel_karar(ilk 25)": len(rows), "örnekler": [dict(r) for r in rows[:6]]}


@check("other_sample_quality")
def other_sample_quality(c):
    with c.transaction():
        with c.cursor(name="oth_scan") as scan:
            scan.itersize = 300
            scan.execute("SELECT s.id, s.raw_text FROM legal_sources s WHERE s.source_type='other' AND s.deleted_at IS NULL AND s.is_current AND s.ingest_status='ready' AND s.raw_text IS NOT NULL")
            return scan_text(scan)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*")
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
            result = {"HATA": str(exc)[:240]}
        print(json.dumps({"denetim": name, "sn": round(time.time() - started), **result}, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
