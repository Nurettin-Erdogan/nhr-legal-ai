"""Dosyalar arası soru: "hangi dosyalarımda araç sorgusu VAR yazıyor?", "açık dosyalarım hangileri?", "en uzun süredir işlem
görmeyen dosya hangisi?".

Soru bir dil modeline SORULMAZ. Bilinen kalıplar bir süzgece çevrilir, süzgeç UYAP'tan çekilmiş dosya bilgilerine uygulanır ve
eşleşen dosyalar, eşleşmeyi sağlayan kaydın kendisiyle birlikte listelenir. Böylece cevap her zaman tamdır (model "en fazla
dört cümle" seçmez, dosya atlamaz) ve uydurma içeremez: her satır bir UYAP kaydıdır.

Soru nasıl anlaşıldıysa kullanıcıya aynen gösterilir ("UYAP durumu: Açık · Araç sorgusu: VAR"); anlaşılmayan soru tahminle
cevaplanmaz, "anlaşılmadı" denir ve örnekler verilir. "VAR"ın ne anlama geldiği burada da yorumlanmaz (bkz.
`api/execution_overview.py`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from api.execution_overview import _role_rank, plain

File = dict[str, Any]
MAX_ROWS = 200
MAX_QUESTION = 300

EXAMPLES = (
    "Açık dosyalarım hangileri?",
    "Hangi dosyalarımda araç sorgusu VAR yazıyor?",
    "Tapu sorgusu YOK çıkan dosyalar",
    "En uzun süredir işlem yapılmayan dosyalar",
    "6 aydır işlem görmeyen açık dosyalar",
    "Kesinleşme bilgisi girilmemiş dosyalar",
)

# Sorgu türü sözcükleri → `asset_queries` anahtar öneki ve gösterilecek ad.
_QUERY_WORDS: tuple[tuple[str, str, str], ...] = (
    ("arac", r"\barac\w*", "Araç"),
    ("tapu", r"\btapu\w*|\btasinmaz\w*|\btakbis\w*|\bgayrimenkul\w*", "Tapu (TAKBİS)"),
    ("sgk", r"\bsgk\w*", "SGK"),
    ("posta", r"posta ceki\w*|\bptt\b", "Posta çeki"),
    ("adres", r"\badres\w*", "Adres"),
)
# İşlem sözcükleri → `milestones` anahtarı ve gösterilecek ad.
_MILESTONE_WORDS: tuple[tuple[str, str, str], ...] = (
    ("kesinlesme", r"kesinles\w*", "Kesinleşme bilgisi"),
    ("haciz_talebi", r"haciz taleb\w*", "Haciz talebi"),
    ("banka_haciz", r"haciz ihbarname\w*|89/1", "Banka haciz ihbarnamesi"),
    ("odeme_emri", r"odeme emri\w*|icra emri\w*", "Ödeme / icra emri"),
    ("tebligat", r"\bteblig\w*", "Tebligat"),
    ("tahsilat", r"\btahsilat\w*", "Tahsilat"),
    ("reddiyat", r"\breddiyat\w*", "Reddiyat"),
)
_STATUS_WORDS: tuple[tuple[str, str], ...] = (
    (r"takipsizlik", "Takipsizlik"), (r"haricen tahsil", "Haricen Tahsil"), (r"\binfaz\w*", "İnfaz"),
    (r"takibin iptali", "Takibin İptali"),
)
_NEGATION = re.compile(
    r"\byok\b|\bolmayan\b|\bbulunmayan\b|\bcikmayan\b|\byapilmamis\b|\bgirilmemis\b|\bgonderilmemis\b|\bcikarilmamis\b|"
    r"\bhazirlanmamis\b|\bedilmemis\b|\byapilmayan\b|\bgirilmeyen\b"
)
_IDLE_FOR = re.compile(r"(\d{1,4})\s*(gun|hafta|ay|yil)\w*\s+(?:\w+\s+)?(?:islem|hareket)\w*(?:\s+(?:yapilmayan|gormeyen|olmayan|yapilmamis|gormemis))?")
_IDLE_SORT = re.compile(r"en uzun sure\w*\s+(?:islem|hareket)\w*(?:\s+(?:yapilmayan|gormeyen|olmayan))?|islem\w*\s+(?:yapilmayan|gormeyen)|hareketsiz")
_ACTIVE_SORT = re.compile(r"en son islem\w*(?:\s+yapilan)?|son islem yapilan|en yeni islem\w*")
_DAYS = {"gun": 1, "hafta": 7, "ay": 30, "yil": 365}
# Soru kalıbı ve süzgeç sözcükleri: ad araması için geriye kalan sözcüklerden atılır.
_STOP = frozenset("""
dosya dosyalar dosyalari dosyalarim dosyalarimda dosyalarimdan dosyada dosyasi dosyam hangi hangileri hangisi hangisinde hangilerinde
kac tane listele goster getir bul olan olanlar var yok mi mu mudur nedir neler kimin kim ile ve veya ya da icin benim bana bir bu su
sorgu sorgusu sorgulari sorgusunda sonuc sonucu sonuclari yaziyor yazan yazanlar cikan cikanlar bulunan gorunen borclu borclusu
borclular borclunun alacakli alacaklisi icra takip takibi takipler takiplerim daire dairesi mahkeme mahkemesi uyap durumu durum
kaydi kayit bilgisi bilgi islem islemi yapilan yapilmis girilmis girilen gonderilmis hazirlanmis edilmis sure suredir en uzun son
tum butun hepsi olarak gore kadar sirala siralama dosyalarin adet toplam dosyam durumundaki durumunda durumda olanlar
turu turundeki yolu yoluyla nelerdir hangileridir listesi liste
""".split())


# Ek almış soru sözcükleri ("takipleri", "dosyalarımdaki", "sorgularında") da ad sayılmaz.
_STOP_STEMS = ("dosya", "takip", "sorgu", "borclu", "alacakli", "durum", "islem", "kayit", "bilgi", "hangi", "liste", "sonuc")


@dataclass
class Parsed:
    filters: list[tuple[str, Callable[[File], list[str] | None]]] = field(default_factory=list)
    sort: tuple[str, str] | None = None  # (anahtar, etiket)
    names: list[str] = field(default_factory=list)
    everything: bool = False  # "kaç dosyam var", "bütün dosyalar": süzgeçsiz liste

    @property
    def understood(self) -> bool:
        return bool(self.filters or self.sort or self.names or self.everything)


def _status(file: File) -> str | None:
    overview = file.get("overview")
    value = next((pair["value"] for pair in (overview or {}).get("identity", []) if plain(pair["label"]) == "dosya durumu"), None)
    return value or (file.get("uyap_status") or "").split("(")[0].strip() or None


def _queries(file: File, prefix: str, wanted: str) -> list[str] | None:
    """Borçlu (ya da rolü bilinmeyen kişi) hakkındaki sorgulardan sonucu `wanted` olanların kayıt satırları; yoksa None."""
    facts = []
    for person in ((file.get("overview") or {}).get("asset_queries") or {}).get("people", []):
        if person["role"] is not None and _role_rank(person["role"]) == 0:
            continue
        for query in person["queries"]:
            if not query["key"].startswith(prefix):
                continue
            results = (query["result"] or "").split("/")
            if wanted in results:
                when = query["result_date"].strftime("%d.%m.%Y") if query["result_date"] else "tarihi yok"
                who = person["name"] or "adı kayıtta okunamayan kişi"
                facts.append(f"{query['label']} sorgusu: {query['result']} · {when} ({who})")
    return facts or None


def _milestone(file: File, key: str, label: str, present: bool) -> list[str] | None:
    found = next((item for item in (file.get("overview") or {}).get("milestones", []) if item["key"] == key), None)
    if present:
        if not found:
            return None
        when = found["last_date"].strftime("%d.%m.%Y") if found["last_date"] else "tarihi yok"
        return [f"{label}: {found['count']} kayıt, son {when}"]
    return None if found else [f"{label}: safahatta kayıt yok"]


def parse(question: str) -> tuple[Parsed, list[str]]:
    """Soruyu süzgece çevirir. (süzgeç, kullanıcıya gösterilecek 'şöyle anladım' etiketleri)."""
    text = f" {plain(question)[:MAX_QUESTION]} "
    parsed, labels = Parsed(), []

    def take(pattern: str | re.Pattern[str]) -> re.Match[str] | None:
        nonlocal text
        match = (pattern if isinstance(pattern, re.Pattern) else re.compile(pattern)).search(text)
        if match:
            text = text[: match.start()] + " " + text[match.end():]
        return match

    idle = take(_IDLE_FOR)
    if idle:
        days = int(idle.group(1)) * _DAYS[idle.group(2)]
        parsed.filters.append(("idle", lambda file, days=days: (
            [f"Son işlem {file['overview']['activity']['last_date'].strftime('%d.%m.%Y')} · {file['overview']['activity']['days_since_last']} gün önce"]
            if file.get("overview") and (file["overview"]["activity"]["days_since_last"] or -1) >= days else None)))
        labels.append(f"En az {days} gündür işlem yok")
        parsed.sort = ("idle", "en uzun süredir işlem görmeyen önce")
    elif take(_IDLE_SORT):
        parsed.sort = ("idle", "en uzun süredir işlem görmeyen önce")
        labels.append("Sıra: en uzun süredir işlem görmeyen önce")
    elif take(_ACTIVE_SORT):
        parsed.sort = ("active", "son işlemi en yeni olan önce")
        labels.append("Sıra: son işlemi en yeni olan önce")

    if take(r"\bacik olmayan\w*|\bkapali\w*|\bkapanan\w*|\bkapanmis\w*|\bkapatilan\w*"):
        parsed.filters.append(("status", lambda file: (
            [f"UYAP durumu: {_status(file)}"] if _status(file) and plain(_status(file)) != "acik" else None)))
        labels.append("UYAP durumu: Açık olmayan")
    elif take(r"\bacik\b|\bacik olan\w*|\bderdest\w*"):
        parsed.filters.append(("status", lambda file: ([f"UYAP durumu: {_status(file)}"] if plain(_status(file)) == "acik" else None)))
        labels.append("UYAP durumu: Açık")
    for pattern, name in _STATUS_WORDS:
        if take(pattern):
            parsed.filters.append(("status", lambda file, name=name: (
                [f"UYAP durumu: {_status(file)}"] if plain(_status(file)) == plain(name) else None)))
            labels.append(f"UYAP durumu: {name}")

    if take(r"\bilamsiz\w*"):
        parsed.filters.append(("type", lambda file: _type_fact(file, "ilamsiz")))
        labels.append("Takip türü: İlamsız")
    elif take(r"\bilamli\w*"):
        parsed.filters.append(("type", lambda file: _type_fact(file, "ilamli")))
        labels.append("Takip türü: İlamlı")
    if take(r"\bkambiyo\w*"):
        parsed.filters.append(("type", lambda file: _type_fact(file, "kambiyo")))
        labels.append("Takip yolu: Kambiyo")

    negated = bool(_NEGATION.search(text))
    for prefix, pattern, name in _QUERY_WORDS:
        if take(pattern):
            wanted = "YOK" if negated else "VAR"
            parsed.filters.append(("query", lambda file, prefix=prefix, wanted=wanted: _queries(file, prefix, wanted)))
            labels.append(f"{name} sorgusu: {wanted}")
    for key, pattern, name in _MILESTONE_WORDS:
        if take(pattern):
            parsed.filters.append(("milestone", lambda file, key=key, name=name, present=not negated: _milestone(file, key, name, present)))
            labels.append(f"{name}: {'kayıt yok' if negated else 'kayıt var'}")

    if re.search(r"\bkac\b|\btum\b|\bbutun\b|\bhepsi\b|\btoplam\b", text):
        parsed.everything = True
        if not labels:
            labels.append("Bütün icra dosyaları")
    parsed.names = [
        word for word in re.findall(r"[a-z0-9/]{3,}", _NEGATION.sub(" ", text))
        if word not in _STOP and not word.startswith(_STOP_STEMS)
    ][:6]
    if parsed.names:
        labels.append("Ad / birim / dosya no içinde: " + " ".join(parsed.names))
    return parsed, labels


def _type_fact(file: File, needle: str) -> list[str] | None:
    pairs = (file.get("overview") or {}).get("identity", [])
    hit = next((pair for pair in pairs if plain(pair["label"]) in ("turu", "yolu") and needle in plain(pair["value"])), None)
    return [f"{hit['label']}: {hit['value']}"] if hit else None


def _names(file: File) -> str:
    parties = " ".join(party["name"] for party in (file.get("overview") or {}).get("parties", []))
    return plain(f"{file.get('file_no') or ''} {file.get('court') or ''} {parties}")


def answer(files: list[File], question: str) -> dict[str, Any]:
    """Dosyalara süzgeci uygular. `files`: {case_id, file_no, court, kind, uyap_status, overview (yoksa None)}."""
    parsed, labels = parse(question)
    base = {"question": question[:MAX_QUESTION], "understood": labels, "total_files": len(files), "examples": list(EXAMPLES)}
    if not parsed.understood:
        return {**base, "ok": False, "rows": [], "matched": 0, "not_evaluated": 0,
                "note": "Bu soruyu bir dosya süzgecine çeviremedim; tahminle cevap vermiyorum. Aşağıdaki örneklere benzer bir soru yazın."}
    needs_detail = any(kind != "status" for kind, _ in parsed.filters) or parsed.sort is not None
    rows, skipped = [], 0
    for file in files:
        if needs_detail and file.get("overview") is None:
            skipped += 1
            continue
        haystack = _names(file)
        if not all(name in haystack for name in parsed.names):
            continue
        facts: list[str] = []
        for _kind, test in parsed.filters:
            found = test(file)
            if found is None:
                break
            facts.extend(found)
        else:
            overview = file.get("overview") or {}
            activity = overview.get("activity") or {}
            parties = overview.get("parties") or []
            if parsed.sort and activity.get("last_date") and not any(fact.startswith("Son işlem") for fact in facts):
                facts.append(f"Son işlem {activity['last_date'].strftime('%d.%m.%Y')} · {activity.get('days_since_last')} gün önce")
            rows.append({
                "case_id": file["case_id"], "file_no": file.get("file_no"), "court": file.get("court"), "kind": file.get("kind"),
                "status": _status(file),
                "creditors": [p["name"] for p in parties if _role_rank(p["role"]) == 0][:4],
                "debtors": [p["name"] for p in parties if _role_rank(p["role"]) == 1][:4],
                "last_activity": activity.get("last_date"), "days_since_last": activity.get("days_since_last"),
                "facts": facts[:8],
            })
    if parsed.sort:
        known = [row for row in rows if row["days_since_last"] is not None]
        unknown = [row for row in rows if row["days_since_last"] is None]
        known.sort(key=lambda row: row["days_since_last"], reverse=parsed.sort[0] == "idle")
        rows = known + unknown  # son işlem tarihi bilinmeyen dosya öne alınmaz
    note = None
    if skipped:
        note = f"{skipped} dosyanın UYAP bilgisi çekilmediği için bu soruda değerlendirilemedi; listede yoklar ama 'eşleşmedi' de sayılmazlar."
    return {**base, "ok": True, "matched": len(rows), "rows": rows[:MAX_ROWS], "not_evaluated": skipped, "note": note}
