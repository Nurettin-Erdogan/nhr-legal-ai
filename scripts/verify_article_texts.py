"""Hazır mevzuat maddelerinin metnini (kaynak adresinden türetilen) resmî PDF ile karşılaştırır; eşleşenlere madde düzeyinde kanıt yazar.

Belge başına resmî PDF (mevzuat.gov.tr/MevzuatMetin/<tür>.<tertip>.<no>.pdf) bir kez indirilir; PDF kalıbı çalışmayan türler (ör. tebliğ) art arda
kalıcı hata alınca atlanır. Her kayıtlı madde, PDF'ten çıkarılan maddeyle
`_comparison_key` (boşluk, noktalama, dipnot işareti ve harf büyüklüğü yok sayılır) üzerinden birebir karşılaştırılır:
  - Eşleşirse `metadata.mbs_text_verification` yazılır (verified, article_hash = content_hash, document_text_hash, yöntem
    `comparison_key_match`). Metne dokunulmaz; `exact_official_article_extraction` kanıtı olan kayıtlar atlanır.
  - Eşleşmezse metin ASLA yeniden yazılmaz; kayıt `.local/article_text_differences.jsonl` incelemesine eklenir.
Başka bir madde başlığı birden fazla geçiyorsa (belirsiz başlık) o madde karşılaştırılmaz.
Resmî siteye kanun başına tek istek atılır, istekler arasında bekleme vardır. Varsayılan kuru çalıştırmadır (`--apply` yazar).

  python scripts/verify_article_texts.py --laws 4857 6098        # kuru çalıştırma
  python scripts/verify_article_texts.py --apply                 # hepsi
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psycopg.types.json import Jsonb  # noqa: E402

from api.db import admin_database_connection  # noqa: E402
from ingestion.mevzuat.identity import article_headings, canonical_article  # noqa: E402
from ingestion.mevzuat.text_verify import (  # noqa: E402
    _comparison_key,
    fetch_official_pdf_text,
    strip_next_article_caption,
)
from ingestion.text import content_hash, normalize_text  # noqa: E402

DIFFERENCES = ROOT / ".local" / "article_text_differences.jsonl"
_DOCS = """
SELECT s.source_url, count(*) AS n
FROM legal_sources s
WHERE s.source_type = 'legislation' AND s.deleted_at IS NULL AND s.is_current AND s.ingest_status = 'ready'
  AND s.source_url LIKE 'https://www.mevzuat.gov.tr/%%'
  AND COALESCE(s.metadata->'mbs_text_verification'->>'article_hash', '') <> s.content_hash
GROUP BY s.source_url ORDER BY n DESC
"""
_DOCS_ALL = """
SELECT s.source_url, count(*) AS n
FROM legal_sources s
WHERE s.source_type = 'legislation' AND s.deleted_at IS NULL AND s.is_current AND s.ingest_status = 'ready'
  AND s.source_url LIKE 'https://www.mevzuat.gov.tr/%%'
GROUP BY s.source_url ORDER BY n DESC
"""
_STORED_ARTICLES = """
SELECT d.article_no FROM legal_sources s JOIN legislation_details d ON d.legal_source_id = s.id
WHERE s.source_type = 'legislation' AND s.deleted_at IS NULL AND s.is_current AND s.ingest_status = 'ready' AND s.source_url = ANY(%s)
"""
COMPLETENESS = ROOT / ".local" / "completeness.jsonl"
_ROWS = """
SELECT s.id, s.raw_text, s.content_hash, s.metadata, d.article_no
FROM legal_sources s JOIN legislation_details d ON d.legal_source_id = s.id
WHERE s.source_type = 'legislation' AND s.deleted_at IS NULL AND s.is_current AND s.ingest_status = 'ready'
  AND s.source_url = %s
  AND COALESCE(s.metadata->'mbs_text_verification'->>'article_hash', '') <> s.content_hash
"""
_PERMANENT = ("beklenen PDF", "resmî değil")
_GIVE_UP_AFTER = 12  # aynı türde art arda bu kadar kalıcı hata ve hiç başarı yoksa o tür atlanır


def pdf_url_for(source_url: str) -> tuple[str, str] | None:
    """Kayıt adresinden (tür, resmî PDF adresi): portal sayfası (MevzuatNo/Tur/Tertip) ya da doğrudan MevzuatMetin PDF adresi."""
    from urllib.parse import parse_qs, urlparse
    parsed = urlparse(source_url)
    if parsed.path.lower().startswith("/mevzuatmetin/") and parsed.path.lower().endswith(".pdf"):
        parts = parsed.path.rsplit("/", 1)[-1].split(".")
        return (parts[0], source_url)
    query = parse_qs(parsed.query)
    try:
        number, kind, tertip = query["MevzuatNo"][0], query["MevzuatTur"][0], query["MevzuatTertip"][0]
    except (KeyError, IndexError):
        return None
    if not (number.isdigit() and kind.isdigit() and tertip.isdigit()):
        return None
    return (kind, f"https://www.mevzuat.gov.tr/MevzuatMetin/{kind}.{tertip}.{number}.pdf")


_LEADING_CAPTION = re.compile(r"^[^\n]{1,160}\n\s*\n(?=(?:GEÇİCİ |EK |MÜKERRER )?MADDE\b)", re.IGNORECASE)


def without_leading_caption(text: str) -> str:
    """Bedesten metninin başındaki madde başlığı satırı ("Amaç", boş satır, "MADDE 1 -") resmî PDF'te "MADDE" satırından önce kalır; atılır."""
    return _LEADING_CAPTION.sub("", text, count=1)


def _shingles(text: str, size: int = 24) -> set[str]:
    return {text[i : i + size] for i in range(0, max(len(text) - size + 1, 1))}


def classify_difference(stored_key: str, official_key: str) -> str:
    """Eşleşmeyen madde metni için fark türü (anahtarlar `_comparison_key` çıktısıdır).

    stored_in_official : kayıtlı metin resmî çıkarımın içinde birebir geçer (PDF'te fazladan dipnot/başlık/sonraki madde artığı var).
    official_in_stored : resmî çıkarım kayıtlı metnin içinde birebir geçer (kayıtta PDF'in kaçırdığı tablo/ek içerik var).
    near_stored / near_official : %97+ örtüşme ama birebir değil (küçük sözcük/rakam farkı olabilir: kanıt YAZILMAZ).
    different : gerçekten farklı metin (sürüm/madde farkı); incelenir.
    """
    if not stored_key or not official_key:
        return "different"
    if stored_key in official_key:
        return "stored_in_official"
    if official_key in stored_key:
        return "official_in_stored"
    stored_set, official_set = _shingles(stored_key), _shingles(official_key)
    if len(stored_set & official_set) / len(stored_set) >= 0.97:
        return "near_stored"
    if len(stored_set & official_set) / len(official_set) >= 0.97:
        return "near_official"
    return "different"


def first_difference(stored_key: str, official_key: str) -> dict:
    prefix = 0
    while prefix < min(len(stored_key), len(official_key)) and stored_key[prefix] == official_key[prefix]:
        prefix += 1
    return {"at": prefix, "stored": stored_key[max(prefix - 30, 0) : prefix + 70], "official": official_key[max(prefix - 30, 0) : prefix + 70]}


def official_bodies(full: str) -> tuple[dict[str, str], dict[str, int]]:
    headings = article_headings(full)
    occurrences = Counter(h.identity for h in headings)
    bodies: dict[str, str] = {}
    for position, heading in enumerate(headings):
        last = position + 1 >= len(headings)
        end = len(full) if last else headings[position + 1].start
        body = normalize_text(full[heading.start:end])
        bodies.setdefault(heading.identity, body if last else strip_next_article_caption(body))
    return bodies, occurrences


def fetch_with_retry(url: str, attempts: int = 3) -> str:
    for attempt in range(attempts):
        try:
            return fetch_official_pdf_text(url, timeout_seconds=60)
        except Exception as exc:  # noqa: BLE001
            if attempt + 1 == attempts or any(marker in str(exc) for marker in _PERMANENT):
                raise
            time.sleep(10 * (attempt + 1))
    raise RuntimeError("ulaşılamaz")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Eşleşenlere kanıt yazar (varsayılan kuru çalıştırma)")
    parser.add_argument("--laws", nargs="*", help="Yalnız bu kanun numaraları")
    parser.add_argument("--delay", type=float, default=4.0, help="Kanunlar arası bekleme (sn)")
    parser.add_argument("--completeness", action="store_true", help="Yalnız TAMLIK: resmî PDF'teki madde başlıklarını kayıtlı maddelerle karşılaştırır (eksik/fazla madde); veri yazmaz")
    parser.add_argument("--shard", default="0/1", help="i/N: belge sırasının N'ye bölümünden kalanı i olanlar (paralel çalıştırma)")
    args = parser.parse_args()
    totals: Counter = Counter()
    failed_laws: list[str] = []
    started = time.time()
    with admin_database_connection() as connection:
        connection.execute("SET statement_timeout = 0")
        connection.commit()
        connection.autocommit = True
        documents = [row["source_url"] for row in connection.execute(_DOCS_ALL if args.completeness else _DOCS).fetchall()]
        if args.completeness:  # aynı resmî PDF'e giden adresler (portal sayfası ve doğrudan PDF) tek belge sayılır
            unique: dict[str, str] = {}
            for document_url in documents:
                target_for = pdf_url_for(document_url)
                if target_for is not None:
                    unique.setdefault(target_for[1], document_url)
            documents = list(unique.values())
        if args.laws:
            wanted = set(args.laws)
            documents = [url for url in documents if any(f".{no}." in url or f"MevzuatNo={no}&" in url for no in wanted)]
        shard_index, shard_count = (int(part) for part in args.shard.split("/"))
        documents = [url for position, url in enumerate(documents) if position % shard_count == shard_index]
        print(f"{len(documents)} belge karşılaştırılacak (parça {args.shard})", flush=True)
        DIFFERENCES.parent.mkdir(parents=True, exist_ok=True)
        permanent_failures: Counter = Counter()
        successes: Counter = Counter()
        skipped_kinds: Counter = Counter()
        with DIFFERENCES.open("a", encoding="utf-8") as differences:
            for number, source_url in enumerate(documents, 1):
                target = pdf_url_for(source_url)
                if target is None:
                    totals["adres_çözülemedi"] += 1
                    continue
                kind, url = target
                law = url.rsplit("/", 1)[-1]
                if permanent_failures[kind] >= _GIVE_UP_AFTER and not successes[kind]:
                    skipped_kinds[kind] += 1
                    continue
                try:
                    full = fetch_with_retry(url)
                except Exception as exc:  # noqa: BLE001
                    failed_laws.append(law)
                    if any(marker in str(exc) for marker in _PERMANENT):
                        permanent_failures[kind] += 1
                    print(f"  [{number}/{len(documents)}] {law}: PDF alınamadı ({str(exc)[:80]})", flush=True)
                    time.sleep(args.delay)
                    continue
                successes[kind] += 1
                bodies, occurrences = official_bodies(full)
                if args.completeness:
                    name_parts = url.rsplit("/", 1)[-1].removesuffix(".pdf").split(".")
                    forms = [url, source_url]
                    if len(name_parts) == 3:
                        forms.append(f"https://www.mevzuat.gov.tr/mevzuat?MevzuatNo={name_parts[2]}&MevzuatTur={name_parts[0]}&MevzuatTertip={name_parts[1]}")
                    stored_ids = {canonical_article(row["article_no"] or "") for row in connection.execute(_STORED_ARTICLES, (forms,)).fetchall()}
                    repealed = {key for key, body in bodies.items() if re.search(r"m[uü]lga", body[:160], re.IGNORECASE)}
                    missing = sorted(set(bodies) - stored_ids - repealed)
                    missing_repealed = sorted((set(bodies) & repealed) - stored_ids)
                    extra = sorted(stored_ids - set(bodies))
                    totals["belge"] += 1
                    totals["eksik_madde"] += len(missing)
                    totals["eksik_mülga_madde"] += len(missing_repealed)
                    totals["resmîde_olmayan_kayıtlı_madde"] += len(extra)
                    if missing or extra:
                        totals["sorunlu_belge"] += 1
                        with COMPLETENESS.open("a", encoding="utf-8") as report:
                            report.write(json.dumps({"url": url, "resmi_madde": len(bodies), "kayitli_madde": len(stored_ids), "eksik": missing[:80], "eksik_n": len(missing),
                                                     "eksik_mulga_n": len(missing_repealed), "fazla": extra[:80], "fazla_n": len(extra)}, ensure_ascii=False) + chr(10))
                    print(f"  [{number}/{len(documents)}] {law}: resmî={len(bodies)} kayıtlı={len(stored_ids)} eksik={len(missing)} (mülga {len(missing_repealed)}) fazla={len(extra)}", flush=True)
                    time.sleep(args.delay)
                    continue
                document_hash = content_hash(full)
                counts: Counter = Counter()
                for row in connection.execute(_ROWS, (source_url,)).fetchall():
                    article = canonical_article(row["article_no"] or "")
                    if occurrences[article] != 1:
                        counts["belirsiz_başlık"] += 1
                        continue
                    official = bodies.get(article)
                    stored = row["raw_text"] or ""
                    if not official:
                        counts["resmî_metinde_yok"] += 1
                        continue
                    if row["content_hash"] != content_hash(stored):
                        counts["kayıtlı_özet_uyuşmuyor"] += 1
                        continue
                    if _comparison_key(without_leading_caption(stored)) == _comparison_key(official):
                        counts["eşleşti"] += 1
                        if args.apply:
                            proof = {"verified": True, "url": url, "article_no": article, "checked_at": datetime.now(timezone.utc).isoformat(),
                                     "article_hash": row["content_hash"], "document_text_hash": document_hash, "method": "comparison_key_match"}
                            connection.execute(
                                "UPDATE legal_sources SET metadata = metadata || %s WHERE id = %s",
                                (Jsonb({"mbs_text_verification": proof}), row["id"]))
                    else:
                        stored_key = _comparison_key(without_leading_caption(stored))
                        official_key = _comparison_key(official)
                        category = classify_difference(stored_key, official_key)
                        counts["fark_" + category] += 1
                        if category == "stored_in_official" and args.apply:
                            proof = {"verified": True, "url": url, "article_no": article, "checked_at": datetime.now(timezone.utc).isoformat(),
                                     "article_hash": row["content_hash"], "document_text_hash": document_hash, "method": "official_contains_stored",
                                     "note": "Kayıtlı metin resmî PDF çıkarımında birebir geçer; çıkarımdaki fazlalık dipnot/başlık gürültüsüdür."}
                            connection.execute(
                                "UPDATE legal_sources SET metadata = metadata || %s WHERE id = %s",
                                (Jsonb({"mbs_text_verification": proof}), row["id"]))
                        elif category != "stored_in_official":
                            differences.write(json.dumps({"id": str(row["id"]), "law_no": law, "article": article, "category": category,
                                                          "stored_len": len(stored), "official_len": len(official),
                                                          "first_difference": first_difference(stored_key, official_key)}, ensure_ascii=False) + chr(10))
                totals.update(counts)
                print(f"  [{number}/{len(documents)}] {law}: {dict(counts)}  ({time.time() - started:.0f} sn)", flush=True)
                time.sleep(args.delay)
    print(("UYGULANDI" if args.apply else "KURU ÇALIŞTIRMA"), dict(totals), "PDF alınamayan belge:", len(failed_laws),
          "| atlanan türler (PDF kalıbı çalışmıyor):", dict(skipped_kinds), "| başarılı:", dict(successes), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
