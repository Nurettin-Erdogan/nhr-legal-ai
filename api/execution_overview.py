"""İcra dosyası incelemesi: UYAP'tan çekilen dosya bilgilerinden künye, taraflar, önemli işlemler, tebligatlar ve kişi başına
malvarlığı sorguları.

Kaynak, `office_uyap_case_detail.tabs` içindeki UYAP sekmeleridir (dosya bilgileri, dosya hesabı, taraflar, safahat,
tahsilat/reddiyat). Her değer UYAP'ın yazdığı metindir. Burada yalnız SEÇİLİR, SAYILIR ve tarihe göre SIRALANIR: tutar
toplanmaz, "takip kesinleşti", "haciz düştü", "borçlunun malı var" gibi bir sonuç söylenmez. Sorgu sonucu, safahat kaydındaki
"Sorgu Sonucu: VAR/YOK" ifadesinin kendisidir; kayıtta sonuç yazmıyorsa "sonuç yazılmamış" denir.

Kalıplar gerçek hesapta ölçüldü (2026-10-10: 17 icra dairesi dosyası, 957 safahat kaydı, 47 ayrı işlem türü). Tanınmayan işlem
türü hiçbir gruba zorla sokulmaz; UYAP'taki adıyla "diğer işlemler" arasında sayılır.

Kimlik numaraları (TC/vergi no) özet metinlerinden çıkarılır: özet onlarsız da okunur, tam kayıt "UYAP Bilgileri" sekmesinde durur.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from typing import Any

from api.turkish_text import fold, fold_keep_length

_ASCII = str.maketrans("çğıöşü", "cgiosu")
_DATE = re.compile(r"(?<!\d)(\d{2})[./](\d{2})[./](\d{4})(?!\d)")
_TC_TAG = re.compile(r"\[\s*TC\s*:\s*\d*\s*\]\s*", re.IGNORECASE)
# TC/vergi no (10-11 hane) ve daha uzun numaralar (IBAN, birleşik kimlik); 13 haneli tebligat barkodu kalır.
_ID_NUMBER = re.compile(r"(?<!\d)(?:\d{10,12}|\d{14,})(?!\d)")
_BARCODE = re.compile(r"(?<!\d)\d{13}(?!\d)")
_TEXT_LIMIT = 240
_NAME_LIMIT = 200
MAX_SERVICES = 300


def plain(text: str | None) -> str:
    """Katlanmış ve aksansız biçim: işlem türü adlarını yazım farkından bağımsız eşlemek için."""
    return fold(text).translate(_ASCII)


def _cell(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def clean_text(text: str | None, limit: int = _TEXT_LIMIT) -> str:
    """Özet metni: kimlik numaraları çıkarılır, boşluklar toplanır, uzun metin kısaltılıp "…" ile işaretlenir."""
    value = _ID_NUMBER.sub("•••", _TC_TAG.sub("", _cell(text)))
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def parse_date(text: str | None) -> date | None:
    """UYAP'ın yazdığı tarih ("12.03.2025", "12/03/2025 14:05"); okunamıyorsa None."""
    match = _DATE.search(text or "")
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


# --- Sekmeleri okuma -------------------------------------------------------------------------------------------------------


def _tab(tabs: Any, key: str) -> dict[str, Any]:
    for tab in tabs if isinstance(tabs, list) else []:
        if isinstance(tab, dict) and tab.get("key") == key:
            return tab
    return {}


def _pairs(tab: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for pair in tab.get("pairs") or []:
        if not isinstance(pair, dict):
            continue
        label, value = _cell(pair.get("label")), _cell(pair.get("value"))
        if label and value:
            out.append({"label": label[:160], "value": value[:300]})
    return out


def _records(tab: dict[str, Any], *required: str) -> list[dict[str, str]]:
    """Sekmenin, istenen başlıkların hepsini taşıyan İLK tablosunun satırları; başlık adları katlanmış anahtar olur."""
    for table in tab.get("tables") or []:
        if not isinstance(table, dict):
            continue
        heads = [plain(head) if isinstance(head, str) else "" for head in table.get("headers") or []]
        if all(name in heads for name in required):
            return [
                {head: _cell(value) for head, value in zip(heads, row) if head}
                for row in table.get("rows") or [] if isinstance(row, list)
            ]
    return []


def identity(tabs: Any) -> list[dict[str, str]]:
    """Dosya bilgileri sekmesindeki alanlar (Türü, Yolu, Şekli, Dosya Durumu…), UYAP'ın yazdığı gibi."""
    return _pairs(_tab(tabs, "bilgiler"))[:12]


def account(tabs: Any) -> list[dict[str, str]]:
    """Dosya hesabı alanları, UYAP'ın yazdığı gibi; "Seç" sütunu hesap alanı değildir."""
    return [pair for pair in _pairs(_tab(tabs, "hesap")) if plain(pair["label"]) != "sec"][:24]


def collections(tabs: Any) -> list[dict[str, str]]:
    """Tahsilat/reddiyat sekmesinin tek satırlık özet tablosu (Tahsilat, Reddiyat, Tahsilat Kalanı…), UYAP'ın yazdığı gibi."""
    for table in _tab(tabs, "tahsilat").get("tables") or []:
        if not isinstance(table, dict):
            continue
        heads = [_cell(head) for head in table.get("headers") or []]
        rows = [row for row in table.get("rows") or [] if isinstance(row, list)]
        folded = [plain(head) for head in heads]
        if "tahsilat" in folded and "reddiyat" in folded and len(rows) == 1:
            return [
                {"label": head[:160], "value": _cell(value)[:300]}
                for head, value in zip(heads, rows[0]) if head and _cell(value)
            ]
    return []


def _role_rank(role: str) -> int:
    value = plain(role)
    return 0 if value.startswith("alacakli") else 1 if value.startswith("borclu") else 2


def parties(tabs: Any) -> list[dict[str, str]]:
    """Taraflar: rol, tip, ad ve vekil, UYAP'ın yazdığı gibi; alacaklılar önce, sonra borçlular."""
    out = [
        {
            "role": row.get("rol", "")[:80],
            "type": row.get("tipi", "")[:40],
            "name": row.get("adi", "")[:_NAME_LIMIT],
            "lawyer": row.get("vekil", "").strip("[] ")[:300],
        }
        for row in _records(_tab(tabs, "taraflar"), "rol", "adi")
        if row.get("adi")
    ]
    return sorted(out, key=lambda item: _role_rank(item["role"]))


def history(tabs: Any) -> list[dict[str, Any]]:
    """Safahat kayıtları, eskiden yeniye; tarihi okunamayan kayıt sona kalır ama atılmaz."""
    entries = [
        {
            "date": parse_date(row.get("tarih")),
            "type": row.get("islem turu", ""),
            "text": row.get("aciklama", ""),
            "unit": row.get("islem yapan birim", ""),
        }
        for row in _records(_tab(tabs, "safahat"), "tarih", "islem turu")
    ]
    return sorted(entries, key=lambda item: (item["date"] is None, item["date"] or date.min))


# --- Sorgular: kişi başına, UYAP'ın yazdığı sonuçla -------------------------------------------------------------------------

_SGK_CALL = re.compile(r"getsgk(aktif|pasif)(4[abc])sorgu")
# (anahtar, başlık, işlem türü kalıbı). Sıra, tablonun sütun sırasıdır.
_QUERY_RULES: tuple[tuple[str, str, str], ...] = (
    ("arac", "Araç", r"arac sahiplikten"),
    ("tapu", "Tapu (TAKBİS)", r"takbis"),
    ("sgk_isyeri", "SGK işyeri tescil", r"getsgkisyeri"),
    ("sgk_haciz", "SGK haciz", r"sgk haciz sorgu"),
    ("sgk_rapor", "SGK raporu", r"sgk bilgileri icin rapor"),
    ("posta", "Posta çeki", r"posta ceki"),
)
_QUERY_ORDER = (
    "arac", "tapu", "sgk_aktif_4a", "sgk_aktif_4b", "sgk_aktif_4c", "sgk_pasif_4a", "sgk_pasif_4b", "sgk_pasif_4c",
    "sgk_isyeri", "sgk_haciz", "sgk_rapor", "posta", "adres",
)
_RESULT = re.compile(r"sorgu sonucu\s*:?\s*(var|yok)\b")
_PERSON = re.compile(r"tarafindan,?\s+(?:\d{10,11}\s+)?(?P<name>\S.*?)\s+adli\s+\S+")


def query_kind(type_text: str, text: str) -> tuple[str, str] | None:
    """Safahat kaydı bir kişi/malvarlığı sorgusuysa (anahtar, başlık); değilse None."""
    kind = plain(type_text)
    if not kind:
        # Adres sorgusunda UYAP işlem türünü boş bırakıyor; yalnız açıklamadan tanınır.
        return ("adres", "Adres") if "adres sorgulamasi" in plain(text) else None
    call = _SGK_CALL.search(kind)
    if call:
        return (f"sgk_{call.group(1)}_{call.group(2)}", f"SGK {call.group(1)} {call.group(2).upper()}")
    for key, label, pattern in _QUERY_RULES:
        if re.search(pattern, kind):
            return (key, label)
    return None


def query_result(text: str) -> str | None:
    """Kayıttaki "Sorgu Sonucu: VAR/YOK" ifadesi; yazmıyorsa None (sonuç tahmin edilmez)."""
    match = _RESULT.search(plain(text))
    return match.group(1).upper() if match else None


def queried_person(text: str) -> str | None:
    """Sorgulanan kişinin adı ("… tarafından, AD SOYAD adlı kişi …"), kayıtta yazıldığı gibi; okunamıyorsa None."""
    match = _PERSON.search(fold_keep_length(text or ""))
    if not match:
        return None
    return " ".join(text[match.start("name"):match.end("name")].split())[:_NAME_LIMIT] or None


def _party_role(name: str, party_list: list[dict[str, str]]) -> str | None:
    """Sorgu kaydındaki adı taraflar tablosuyla eşler; tek ve açık eşleşme yoksa rol yazılmaz."""
    wanted = plain(name)
    exact = {party["role"] for party in party_list if plain(party["name"]) == wanted}
    if len(exact) == 1:
        return exact.pop()
    if exact:
        return None
    partial = {
        party["role"] for party in party_list
        if wanted and (wanted in plain(party["name"]) or plain(party["name"]) in wanted)
    }
    return partial.pop() if len(partial) == 1 else None


def asset_queries(entries: list[dict[str, Any]], party_list: list[dict[str, str]]) -> dict[str, Any]:
    """Kişi başına sorgu türleri: kaç kez, en son ne zaman ve kayıtta yazan son sonuç."""
    people: dict[str, dict[str, Any]] = {}
    labels: dict[str, str] = {}
    for entry in entries:
        kind = query_kind(entry["type"], entry["text"])
        if kind is None:
            continue
        key, label = kind
        labels[key] = label
        name = queried_person(entry["text"])
        person = people.setdefault(plain(name) if name else "", {"name": name, "kinds": {}})
        cell = person["kinds"].setdefault(key, {
            "key": key, "label": label, "count": 0, "last_date": None, "result": None, "result_date": None,
            "results": Counter(),
        })
        cell["count"] += 1
        result = query_result(entry["text"])
        cell["results"][result or "unstated"] += 1
        stamp = entry["date"]
        if stamp is None:
            continue
        # Kayıtlar eskiden yeniye gelir: sonraki kayıt öncekinin yerini alır.
        cell["last_date"] = stamp
        if result is None:
            continue
        if cell["result_date"] == stamp and cell["result"] not in (None, result):
            # Aynı gün iki farklı sonuç: hangisinin sonra yazıldığı bilinemez, ikisi de gösterilir.
            cell["result"] = "VAR/YOK"
        elif cell["result_date"] != stamp or cell["result"] is None:
            cell["result"], cell["result_date"] = result, stamp
    order = [key for key in _QUERY_ORDER if key in labels] + sorted(key for key in labels if key not in _QUERY_ORDER)
    rows = []
    for person in people.values():
        role = _party_role(person["name"], party_list) if person["name"] else None
        rows.append({
            "name": person["name"],
            "role": role,
            "queries": [
                {**person["kinds"][key], "results": dict(person["kinds"][key]["results"])}
                for key in order if key in person["kinds"]
            ],
        })
    # Borçlular önce; adı okunamayan kayıtlar en sonda.
    rows.sort(key=lambda row: (row["name"] is None, _role_rank(row["role"] or "") != 1, plain(row["name"])))
    return {"kinds": [{"key": key, "label": labels[key]} for key in order], "people": rows}


# --- Önemli işlemler --------------------------------------------------------------------------------------------------------

# (anahtar, başlık, işlem türü kalıbı, açıklama kalıbı). İlk eşleşen kazanır; sıra gösterim sırasıdır (takibin olağan akışı).
_MILESTONES: tuple[tuple[str, str, str, str | None], ...] = (
    ("acilis", "Dosyanın açılması", r"^dosyanin acilmasi", None),
    ("alacak", "Alacak kalemi / ilam / senet girişi", r"alacak kalemleri girisi|ilam bilgisinin girilmesi|senet bilgisinin girilmesi", None),
    ("odeme_emri", "Ödeme / icra emri hazırlandı", r"odeme icra emri|odeme emri|icra emri", None),
    ("tebligat", "Tebligat çıkarıldı", r"^tebligat bilgileri kaydedildi", None),
    ("tebligat_sonuc", "Tebligat sonucu kaydedildi", r"^tebligat sonuc", None),
    ("kesinlesme", "Kesinleşme bilgisi girildi", r"kesinlesme", None),
    ("haciz_talebi", "Haciz talebi (tensip kaydı)", r"^tensip zapti", r"haciz talebi"),
    ("talep", "Diğer talep ve tensip kayıtları", r"^tensip zapti", None),
    ("banka_haciz", "Bankalara haciz ihbarnamesi hazırlandı", r"haciz ihbarnamesi", None),
    ("mahrumiyet", "Mahrumiyet / haciz kaydı", r"mahrumiyet bilgisi eklendi|mahrumiyet kaldirildi|tasit bilgisinin girilmesi|dosya alacagina haciz", None),
    ("gelen_evrak", "Gelen evrak kaydedildi", r"^gelen evrak", None),
    ("tahsilat", "Tahsilat", r"^tahsilat yapilmasi|banka havale|^tahsilat guncellen", None),
    ("masraf", "Harç / masraf tahsilatı", r"^harc masraf tahsilati", None),
    ("reddiyat", "Reddiyat", r"^reddiyat", None),
    ("hesap", "Dosya hesabı yapıldı", r"^dosya hesabi yapildi", None),
    ("durdurma", "Dosyanın durdurulması", r"^dosyanin durdurulmasi", None),
    ("gonderme", "Dosya başka birime gönderildi", r"baska bir birime gonderildi", None),
    ("kapanis", "Dosya kapatıldı", r"^dosya kapatildi", None),
    ("yeniden_acilis", "Kapatılan dosyanın açılması", r"kapatilan dosyanin acilmasi", None),
)
_RECENT = 3


def milestone_key(type_text: str, text: str) -> str | None:
    kind, body = plain(type_text), plain(text)
    for key, _label, type_pattern, text_pattern in _MILESTONES:
        if re.search(type_pattern, kind) and (text_pattern is None or re.search(text_pattern, body)):
            return key
    return None


def _span(group: list[dict[str, Any]]) -> tuple[date | None, date | None]:
    dates = [entry["date"] for entry in group if entry["date"] is not None]
    return (min(dates), max(dates)) if dates else (None, None)


def _recent(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dated = [entry for entry in group if entry["date"] is not None]
    return [{"date": entry["date"], "text": clean_text(entry["text"])} for entry in reversed(dated[-_RECENT:]) if entry["text"]]


def milestones(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(önemli işlemler, diğer işlemler). Her grup: kaç kayıt, ilk ve son tarih, UYAP'taki işlem türü adları, son kayıtlar."""
    groups: dict[str, list[dict[str, Any]]] = {}
    other: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if query_kind(entry["type"], entry["text"]) is not None:
            continue
        key = milestone_key(entry["type"], entry["text"])
        if key is not None:
            groups.setdefault(key, []).append(entry)
        else:
            other.setdefault(entry["type"] or "(işlem türü yazılmamış)", []).append(entry)
    main = []
    for key, label, _type_pattern, _text_pattern in _MILESTONES:
        group = groups.get(key)
        if not group:
            continue
        first, last = _span(group)
        main.append({
            "key": key, "label": label, "count": len(group), "first_date": first, "last_date": last,
            "uyap_types": sorted({entry["type"] for entry in group if entry["type"]})[:6],
            "recent": _recent(group),
        })
    rest = []
    for name, group in other.items():
        first, last = _span(group)
        rest.append({"name": name[:160], "count": len(group), "first_date": first, "last_date": last})
    rest.sort(key=lambda item: (-item["count"], item["name"]))
    return main, rest


# --- Tebligatlar ------------------------------------------------------------------------------------------------------------

_RECIPIENT = re.compile(r"\[(.+?)\]")
_METHOD = re.compile(r"\]\s*tarafına\s*-\s*(.+)$")


def service_attempts(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tebligat kayıtları: kime çıkarıldığı, ne zaman ve (kayıtta varsa) sonucu. Çıkış ve sonuç kaydı barkod numarasıyla eşlenir."""
    items: list[dict[str, Any]] = []
    by_barcode: dict[str, dict[str, Any]] = {}
    for entry in entries:
        kind = plain(entry["type"])
        sent, concluded = kind.startswith("tebligat bilgileri kaydedildi"), kind.startswith("tebligat sonuc")
        if not (sent or concluded):
            continue
        text = entry["text"]
        barcode = _BARCODE.search(text)
        code = barcode.group(0) if barcode else None
        recipient = _RECIPIENT.search(text)
        item = by_barcode.get(code) if code else None
        if item is None:
            item = {
                "barcode": code, "recipient": clean_text(recipient.group(1), _NAME_LIMIT) if recipient else None,
                "method": None, "sent_date": None, "result": None, "result_date": None,
            }
            items.append(item)
            if code:
                by_barcode[code] = item
        if sent:
            method = _METHOD.search(text)
            item["sent_date"] = item["sent_date"] or entry["date"]
            item["method"] = item["method"] or (clean_text(method.group(1), 120) if method else None)
        else:
            # Sonuç metni barkoddan sonra yazar ("… - 2700… - Tebliğ Edildi"); yalnız "Barkod No:2700…" ise sonuç metni yoktur.
            tail = text[barcode.end():].strip(" -:") if barcode else ""
            item["result_date"] = entry["date"]
            item["result"] = clean_text(tail, 120) or item["result"]
            if recipient and not item["recipient"]:
                item["recipient"] = clean_text(recipient.group(1), _NAME_LIMIT)
    items.sort(key=lambda item: (item["sent_date"] or item["result_date"] or date.min), reverse=True)
    return items[:MAX_SERVICES]


# --- Bütün özet -------------------------------------------------------------------------------------------------------------


def activity(entries: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """Safahatın uzunluğu, ilk ve son kayıt tarihi ve son kayıttan bugüne geçen gün sayısı (yalnız sayı; sonucu söylenmez)."""
    first, last = _span(entries)
    newest = next((entry for entry in reversed(entries) if entry["date"] is not None), None)
    return {
        "entries": len(entries),
        "undated": sum(1 for entry in entries if entry["date"] is None),
        "first_date": first,
        "last_date": last,
        "days_since_last": (today - last).days if last and last <= today else None,
        "last": {"type": newest["type"][:160], "text": clean_text(newest["text"])} if newest else None,
    }


def build_overview(tabs: Any, *, complete: bool, fetched_at: datetime | None, today: date) -> dict[str, Any]:
    """UYAP dosya bilgilerinden icra dosyası incelemesi. `tabs` boşsa bölümler boş gelir; hiçbir alan uydurulmaz."""
    entries = history(tabs)
    party_list = parties(tabs)
    main, rest = milestones(entries)
    return {
        "fetched_at": fetched_at,
        # UYAP'ın söylediği kayıt sayılarıyla her tablo tam okundu mu; değilse özet eksik olabilir ve arayüz bunu söyler.
        "complete": bool(complete),
        "identity": identity(tabs),
        "parties": party_list,
        "account": account(tabs),
        "collections": collections(tabs),
        "activity": activity(entries, today),
        "milestones": main,
        "other_actions": rest,
        "asset_queries": asset_queries(entries, party_list),
        "services": service_attempts(entries),
    }


def _value(pairs: list[dict[str, str]], label: str) -> str | None:
    wanted = plain(label)
    return next((pair["value"] for pair in pairs if plain(pair["label"]) == wanted), None)


def list_overview(overview: dict[str, Any]) -> dict[str, Any]:
    """Liste satırı için kısa özet: takip türü/yolu/durumu, taraf adları, son işlem ve son sonucu "VAR" yazan sorgular."""
    names: dict[int, list[str]] = {0: [], 1: []}
    for party in overview["parties"]:
        rank = _role_rank(party["role"])
        if rank in names and party["name"] not in names[rank]:
            names[rank].append(party["name"])
    positive: list[str] = []
    for person in overview["asset_queries"]["people"]:
        # Yalnız borçlu diye eşleşen ya da rolü bilinmeyen kişi: alacaklı hakkındaki sorgu listede anılmaz.
        if person["role"] is not None and _role_rank(person["role"]) == 0:
            continue
        for query in person["queries"]:
            if query["key"] != "adres" and query["result"] in ("VAR", "VAR/YOK") and query["label"] not in positive:
                positive.append(query["label"])
    return {
        "type": _value(overview["identity"], "Türü"),
        "path": _value(overview["identity"], "Yolu"),
        "status": _value(overview["identity"], "Dosya Durumu"),
        "creditors": names[0][:6],
        "debtors": names[1][:6],
        "party_count": len(overview["parties"]),
        "last_activity": overview["activity"]["last_date"],
        "days_since_last": overview["activity"]["days_since_last"],
        "history_entries": overview["activity"]["entries"],
        "positive_queries": positive,
    }
