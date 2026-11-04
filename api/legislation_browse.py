"""Mevzuat gezgini: kanun/yönetmelik listesi ve bir mevzuatın madde dizini (yalnız resmî doğrulanmış, güncel kayıtlar).

Kaynak, `legal_sources` + `legislation_details` içindeki aynı doğrulama süzgecidir (Resmî Gazete + MBS çift doğrulaması ya da MBS metin
doğrulaması): doğrulanmamış mevzuat burada listelenmez ve "resmî" diye sunulmaz. Madde metni mevcut `/api/legal/sources/{id}` ile okunur.

Mevzuat listesi küçüktür (~4 bin) ama çıkarımı soğukta birkaç saniye sürer; bellekte tutulur ve arka planda tazelenir. Arama Türkçe
karakter katlamalıdır ("is kanunu" ile "İŞ KANUNU" eşleşir).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path


from api.ai.retrieval import _VERIFIED_SOURCE_FILTER

LAWS_TTL_SECONDS = 3600.0
MAX_ARTICLES = 5000
TYPE_ORDER = ("constitution", "law", "decree", "regulation", "communique", "other")
_FOLD = str.maketrans({"İ": "i", "I": "i", "ı": "i", "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u", "â": "a", "î": "i", "û": "u"})


def fold(text: str) -> str:
    """Arama için: Türkçe harfleri katlar, küçültür, boşlukları sadeleştirir."""
    return " ".join(text.translate(_FOLD).lower().split())


@dataclass(frozen=True)
class Law:
    law_no: str
    law_name: str
    legislation_type: str
    articles: int
    latest_version: str | None
    gazette_date: str | None
    folded: str

    def as_dict(self) -> dict:
        return {
            "law_no": self.law_no,
            "law_name": self.law_name,
            "legislation_type": self.legislation_type,
            "articles": self.articles,
            "latest_version": self.latest_version,
            "gazette_date": self.gazette_date,
        }


_LAWS_SQL = f"""
SELECT d.law_no,
       (array_agg(d.law_name ORDER BY d.version_date DESC NULLS LAST))[1] AS law_name,
       (array_agg(d.legislation_type ORDER BY d.version_date DESC NULLS LAST))[1] AS legislation_type,
       count(*) AS articles,
       max(d.version_date) AS latest_version,
       max(d.official_gazette_date) AS gazette_date
FROM legislation_details d
JOIN legal_sources ls ON ls.id = d.legal_source_id
WHERE ls.source_type = 'legislation' AND ls.deleted_at IS NULL AND ls.is_current
  AND d.law_no IS NOT NULL AND d.law_no <> ''
  AND {_VERIFIED_SOURCE_FILTER}
GROUP BY d.law_no
"""

_ARTICLES_SQL = f"""
SELECT ls.id, d.article_no, d.article_title, d.version_date, d.law_name, d.legislation_type, d.official_gazette_date
FROM legislation_details d
JOIN legal_sources ls ON ls.id = d.legal_source_id
WHERE d.law_no = %s AND ls.source_type = 'legislation' AND ls.deleted_at IS NULL AND ls.is_current
  AND {_VERIFIED_SOURCE_FILTER}
LIMIT %s
"""

_cache: tuple[float, list[Law]] | None = None
_lock = threading.Lock()


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def load_laws(connection) -> list[Law]:
    # Kanun listesi ~90 bin satırı diskten gezer (8 sn boşta; gömme yazımı gibi yoğun disk yükünde 30 sn'yi aşıyor ve soğuk
    # açılışta her istek aynı zaman aşımına uğruyordu: ölçüldü 2026-11-01; Docker yeniden başlayınca soğuk önbellekle 180 sn'yi de aştı).
    # Sonuç bellekte ve diskte tutulur, bu yüzden sınır geniş.
    connection.execute("SET LOCAL statement_timeout = '900s'")
    laws = []
    for row in connection.execute(_LAWS_SQL).fetchall():
        laws.append(
            Law(
                law_no=row["law_no"],
                law_name=" ".join(row["law_name"].split()),
                legislation_type=row["legislation_type"] if row["legislation_type"] in TYPE_ORDER else "other",
                articles=int(row["articles"]),
                latest_version=_iso(row["latest_version"]),
                gazette_date=_iso(row["gazette_date"]),
                folded=fold(f"{row['law_name']} {row['law_no']}"),
            )
        )
    return laws


_refreshing = False


def _save_file(laws: list[Law], path: Path | None) -> None:
    """Listeyi diske yazar (yeniden başlatmada soğuk çıkarımı beklememek için); hata sessizce yutulur."""
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps([law.as_dict() for law in laws], ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass


def _load_file(path: Path | None) -> list[Law] | None:
    if path is None or not path.exists():
        return None
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        return [
            Law(law_no=row["law_no"], law_name=row["law_name"], legislation_type=row["legislation_type"], articles=int(row["articles"]),
                latest_version=row.get("latest_version"), gazette_date=row.get("gazette_date"),
                folded=fold(f"{row['law_name']} {row['law_no']}"))
            for row in rows
        ] or None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _refresh_in_background(loader, path: Path | None = None) -> None:
    """Süresi dolan listeyi arka planda yeniler; kullanıcı beklemez, yenileme başarısızsa eski liste kalır."""
    global _cache, _refreshing
    try:
        laws = loader()
        with _lock:
            _cache = (time.monotonic(), laws)
        _save_file(laws, path)
    except Exception:  # noqa: BLE001 - yenileme en iyi çabadır; eski liste kullanılmaya devam eder
        pass
    finally:
        _refreshing = False


def cached_laws(loader, path: Path | None = None) -> list[Law]:
    """Bellekteki liste. Süresi dolmuşsa eski liste hemen döner ve liste arka planda yenilenir.

    Çıkarım soğukta artık dakikalar sürebilir (mevzuat ~314 bin madde; disk yoğunken ölçüldü 2026-11-01) ve ilk istek tüm
    istekleri kilidin arkasında bekletiyordu. `path` verilirse liste diske de yazılır: sunucu yeniden başlayınca (bellek boşken)
    diskteki liste hemen kullanılır, güncelleme arka planda yapılır. Yalnız ne bellekte ne diskte liste yoksa beklenir.
    """
    global _cache, _refreshing
    with _lock:
        cached = _cache
        if cached is None:
            stored = _load_file(path)
            if stored is not None:
                cached = _cache = (time.monotonic() - LAWS_TTL_SECONDS, stored)  # eski sayılır: arka planda tazelenir
        if cached is not None:
            if time.monotonic() - cached[0] >= LAWS_TTL_SECONDS and not _refreshing:
                _refreshing = True
                threading.Thread(target=_refresh_in_background, args=(loader, path), name="laws-refresh", daemon=True).start()
            return cached[1]
        laws = loader()
        _cache = (time.monotonic(), laws)
        _save_file(laws, path)
        return laws


def reset_cache() -> None:
    global _cache, _refreshing
    _cache = None
    _refreshing = False


_REFERENCE = re.compile(r"(?<!\d)(\d{1,8})\s*(?:sayılı|sayili)?\s*.*?\b(?:m|md|madde)\.?\s*(\d{1,4}(?:\s*/\s*[A-Za-z])?)\b", re.IGNORECASE)


def parse_reference(query: str) -> tuple[str, str] | None:
    """"4857 m. 18", "4857 sayılı kanun madde 18" gibi sorgudan (kanun no, madde no) çıkarır."""
    match = _REFERENCE.search(query)
    if not match:
        return None
    return match.group(1), re.sub(r"\s+", "", match.group(2)).upper()


# Kanun ADIYLA ya da kısaltmasıyla anılan madde atfı: "TBK 344", "anayasa m. 38", "iş kanunu 17", "ceza muhakemesi kanunu madde 100".
# Kısaltma tablosu hukuki içerik değildir; yalnız hangi kanunun açılacağını söyler (numaralar 2026-10-30'da korpustaki resmî kayıt adıyla
# karşılaştırıldı). "TMK" gibi belirsiz kısaltmalar bilerek yoktur (Medeni Kanun da Terörle Mücadele Kanunu da olabilir); ad yazılırsa çalışır.
_ABBREVIATIONS = {
    "tbk": "6098", "tck": "5237", "cmk": "5271", "hmk": "6100", "iik": "2004", "iyuk": "2577", "ttk": "6102",
    "tkhk": "6502", "kvkk": "6698", "kmk": "634", "vuk": "213", "gvk": "193", "kvk": "5520", "kdvk": "3065",
    "anayasa": "2709",
}
_NAMED_REFERENCE = re.compile(
    r"^\s*(?P<name>[^\d]*?[^\d\s.])\s*(?:\b(?:m|md|madde|maddesi)\b\.?)?\s*(?P<no>\d{1,4}(?:\s*/\s*[A-Za-z])?)\s*\.?\s*(?:\b(?:m|md|madde|maddesi)\b\.?)?\s*$",
    re.IGNORECASE,
)


def parse_named_reference(laws: list[Law], query: str) -> tuple[Law, str] | None:
    """"TBK 344", "anayasa 38", "iş kanunu 17" gibi sorgudan (kanun, madde no) çıkarır; kanun adı tek anlamlı değilse None.

    Sıra: kısaltma tablosu > tam ad eşleşmesi > ad başlangıcı > addaki tüm sözcükler (eşitlikte madde sayısı çok olan). Yalnız kanun,
    KHK ve Anayasa aranır; yönetmelik/tebliğ adlarında sondaki sayı çoğunlukla madde değil yıl ya da sıra numarasıdır.
    """
    match = _NAMED_REFERENCE.match(query)
    if not match:
        return None
    name, number = fold(match.group("name")), re.sub(r"\s+", "", match.group("no")).upper()
    if not name or name in {"m", "md", "madde", "sayili", "sayili kanun"}:
        return None
    pool = [law for law in laws if law.legislation_type in {"law", "constitution", "decree"}]
    by_no = {law.law_no: law for law in pool}
    if name in _ABBREVIATIONS:
        law = by_no.get(_ABBREVIATIONS[name])
        return (law, number) if law else None
    words = name.split()
    exact = [law for law in pool if law.folded == name]
    starts = [law for law in pool if law.folded.startswith(name)]
    inside = [law for law in pool if all(word in law.folded for word in words)]
    for group in (exact, starts, inside if len(words) >= 2 else []):  # tek sözcükle "kira 2024" gibi sorgular kanun sayılmaz
        if group:
            best = max(group, key=lambda law: (law.articles, law.law_name))
            return best, number
    return None


_TYPE_ORDER = {"constitution": 0, "law": 1, "decree": 2, "regulation": 3, "communique": 4, "other": 5}


def search_laws(laws: list[Law], query: str, kind: str | None) -> list[Law]:
    """Numara tam eşleşmesi > ad başlangıcı > ad içinde geçme; eşitlikte madde sayısı çok olan önde."""
    wanted = [law for law in laws if not kind or law.legislation_type == kind]
    cleaned = fold(query)
    if not cleaned:
        # Boş sorgu: önce Anayasa, kanunlar, KHK'ler; yönetmelikler ve tebliğler sonra. Grup içinde madde sayısı çok olan önde.
        return sorted(wanted, key=lambda law: (_TYPE_ORDER.get(law.legislation_type, len(_TYPE_ORDER)), -law.articles, law.law_name))
    named = parse_named_reference(laws, query)
    if named and (not kind or named[0].legislation_type == kind):
        return [named[0]]
    if cleaned in _ABBREVIATIONS and cleaned != "anayasa":
        # "TCK", "CMK", "TTK" tek başına yazılınca da o kanun gelir (yalnız madde numarasıyla çalışıyordu).
        by_abbreviation = [law for law in wanted if law.law_no == _ABBREVIATIONS[cleaned] and law.legislation_type in ("law", "constitution")]
        if by_abbreviation:
            return by_abbreviation
    reference = parse_reference(query)
    if reference:
        cleaned_no = reference[0]
        by_no = [law for law in wanted if law.law_no == cleaned_no]
        if by_no:
            return by_no
    if cleaned.isdigit():
        exact = [law for law in wanted if law.law_no == cleaned]
        if exact:
            return exact  # "4857" yalnız 4857 sayılı kanundur; "34857" gibi içinde geçenler karışmaz
    words = cleaned.split()
    scored: list[tuple[int, Law]] = []
    for law in wanted:
        if cleaned == law.law_no:
            score = 0
        elif law.folded.startswith(cleaned):
            score = 1
        elif all(word in law.folded for word in words):
            score = 2
        else:
            continue
        scored.append((score, law))
    # "Anayasa" yazan önce Anayasa'nın kendisini görür; Anayasa Mahkemesi kanunu, yönetmelikleri vb. ardından gelir.
    pinned = _ABBREVIATIONS.get(cleaned)

    def is_pinned(law: Law) -> int:
        return 0 if pinned and law.law_no == pinned and law.legislation_type in ("law", "constitution") else 1

    scored.sort(key=lambda item: (is_pinned(item[1]), item[0], -item[1].articles, item[1].law_name))
    return [law for _, law in scored]


def article_sort_key(article_no: str | None) -> tuple:
    """Madde numarası sırası: 1, 2, 14, 14/A, ... sonra Geçici/Ek maddeler kendi numarasıyla."""
    text = (article_no or "").strip()
    position = next((index for index, char in enumerate(text) if char.isdigit()), None)
    if position is None:
        prefix, number, suffix = text, 10**9, ""
    else:
        end = position
        while end < len(text) and text[end].isdigit():
            end += 1
        prefix, number, suffix = text[:position], int(text[position:end]), text[end:]
    prefix, suffix = fold(prefix), fold(suffix)
    group = 0 if not prefix else 1 if prefix.startswith("gecici") else 2 if prefix.startswith("ek") else 3
    return (group, prefix, number, suffix)


def load_articles(connection, law_no: str) -> dict | None:
    connection.execute("SET LOCAL statement_timeout = '15s'")
    rows = connection.execute(_ARTICLES_SQL, (law_no, MAX_ARTICLES + 1)).fetchall()
    if not rows:
        return None
    truncated = len(rows) > MAX_ARTICLES
    rows = rows[:MAX_ARTICLES]
    newest = max(rows, key=lambda row: row["version_date"] or date.min)
    articles = [
        {
            "id": str(row["id"]),
            "article_no": row["article_no"],
            "article_title": row["article_title"],
            "version_date": _iso(row["version_date"]),
        }
        for row in sorted(rows, key=lambda row: (article_sort_key(row["article_no"]), str(row["id"])))
    ]
    return {
        "law_no": law_no,
        "law_name": newest["law_name"],
        "legislation_type": newest["legislation_type"] if newest["legislation_type"] in TYPE_ORDER else "other",
        "gazette_date": _iso(newest["official_gazette_date"]),
        "articles": articles,
        "truncated": truncated,
    }
