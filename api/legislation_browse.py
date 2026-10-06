"""Mevzuat gezgini: kanun/yönetmelik listesi ve bir mevzuatın madde dizini (yalnız resmî doğrulanmış, güncel kayıtlar).

Kaynak, `legal_sources` + `legislation_details` içindeki aynı doğrulama süzgecidir (Resmî Gazete + MBS çift doğrulaması ya da MBS metin
doğrulaması): doğrulanmamış mevzuat burada listelenmez ve "resmî" diye sunulmaz. Madde metni mevcut `/api/legal/sources/{id}` ile okunur.

Mevzuat listesi küçüktür (~4 bin) ama çıkarımı soğukta birkaç saniye sürer; bellekte tutulur ve arka planda tazelenir. Arama Türkçe
karakter katlamalıdır ("is kanunu" ile "İŞ KANUNU" eşleşir).
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import psycopg

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
    connection.execute("SET LOCAL statement_timeout = '30s'")
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


def _refresh_in_background(loader) -> None:
    """Süresi dolan listeyi arka planda yeniler; kullanıcı beklemez, yenileme başarısızsa eski liste kalır."""
    global _cache, _refreshing
    try:
        laws = loader()
        with _lock:
            _cache = (time.monotonic(), laws)
    except Exception:  # noqa: BLE001 - yenileme en iyi çabadır; eski liste kullanılmaya devam eder
        pass
    finally:
        _refreshing = False


def cached_laws(loader) -> list[Law]:
    """Bellekteki liste. Süresi dolmuşsa eski liste hemen döner ve liste arka planda yenilenir.

    Çıkarım soğukta ~20 saniye sürüyor ve Mevzuat sayfası her saat başı (ve sunucu açılışından sonraki ilk girişte) bu kadar
    bekletiyordu (ölçüldü: 2026-10-05). Yalnız hiç liste yokken (ilk çağrı) beklenir; açılışta `warm_laws` bunu da önceden yapar.
    """
    global _cache, _refreshing
    with _lock:
        cached = _cache
        if cached is not None:
            if time.monotonic() - cached[0] >= LAWS_TTL_SECONDS and not _refreshing:
                _refreshing = True
                threading.Thread(target=_refresh_in_background, args=(loader,), name="laws-refresh", daemon=True).start()
            return cached[1]
        laws = loader()
        _cache = (time.monotonic(), laws)
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


def search_laws(laws: list[Law], query: str, kind: str | None) -> list[Law]:
    """Numara tam eşleşmesi > ad başlangıcı > ad içinde geçme; eşitlikte madde sayısı çok olan önde."""
    wanted = [law for law in laws if not kind or law.legislation_type == kind]
    cleaned = fold(query)
    if not cleaned:
        return sorted(wanted, key=lambda law: (-law.articles, law.law_name))
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
    scored.sort(key=lambda item: (item[0], -item[1].articles, item[1].law_name))
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
