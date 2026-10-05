"""Dava belgelerinin karşılaştırması: belirleyici (yapay zekâsız) cümle ve sözcük farkı.

Bir sözleşmenin iki sürümü ya da iki dilekçe arasında "ne değişti?" sorusunu yanıtlar. Sonuç bir hukuki yorum
değildir ve model çıktısı değildir: yalnız iki metnin farkıdır. Bu yüzden kaynak/atıf kuralına takılmaz, ama
şunlara dikkat edilir:

* Eşitlik **rakam ve noktalamayı korur** (yalnız büyük/küçük harf ve boşluk yok sayılır): "1.000 TL" ile
  "10.000 TL" her zaman fark olarak görünür.
* Metin belgenin indekslenmiş parçalarından kurulur; OCR ile okunan belgede farkların bir kısmı okuma
  hatası olabilir, çağıran bunu kullanıcıya bildirir.
* Çok uzun belgeler sessizce kırpılmaz: sınır aşılırsa `CompareTooLarge` atılır.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

MAX_COMPARE_CHARS = 400_000  # belge başına
MAX_UNITS = 6_000  # belge başına cümle/paragraf sayısı
_PAIR_THRESHOLD = 0.5  # iki cümle bu sözcük benzerliğinin üstündeyse "değişti" sayılır, değilse silindi + eklendi
_PAIR_BUDGET = 40_000  # bir farklı blokta denenecek en çok (sol x sağ) çift: çok farklı iki belge sunucuyu kilitlemesin

_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+(?=[A-ZÇĞİÖŞÜ0-9(\"“'‘-])")
_LOWER_TR = str.maketrans({"İ": "i", "I": "ı"})
# Nokta ile biten bu belirteçlerden sonra cümle bitmez ("ABC Ltd. Şti. arasında", "Av. Ali", "m. 14", "1. Taraflar").
_ABBREVIATIONS = frozenset(
    "ltd şti no md av dr sn sy bkz vb vs vd örn ör mah cad sok apt bk m s fıkra bent prof doç yrd uzm hak tic san".split()
)
_INITIALS = re.compile(r"^(?:[A-Za-zÇĞİÖŞÜçğıöşü]\.)+$")  # "A." (baş harf), "A.Ş." (kısaltma)
_NUMBERING = re.compile(r"^\d+\.$")  # yalnız parçanın tamamı "1." ise numaralandırmadır; "... 2025." cümle sonu olabilir


class CompareTooLarge(ValueError):
    pass


def normalize_key(text: str) -> str:
    """Eşitlik anahtarı: boşluklar tek boşluk, Türkçe küçük harf. Rakam ve noktalama korunur."""
    return " ".join(text.translate(_LOWER_TR).lower().split())


def _ends_with_abbreviation(text: str) -> bool:
    words = text.split()
    if not words or not words[-1].endswith("."):
        return False
    last = words[-1]
    if _INITIALS.match(last) or (len(words) == 1 and _NUMBERING.match(last)):
        return True
    return last[:-1].translate(_LOWER_TR).lower() in _ABBREVIATIONS


def split_units(text: str) -> list[str]:
    """Paragraf sınırı çift satır sonudur (tek satır sonu PDF satır kaydırmasıdır, boşluk sayılır); paragraf cümlelere bölünür.

    Kısaltma ya da numaralandırmadan sonraki nokta cümleyi bitirmez ("Ltd. Şti.", "m. 14", "1. Taraflar"): bölünseydi aynı cümle iki
    parçaya ayrılırdı. Yanlış birleştirme yalnız ayrıntıyı azaltır (iki cümle tek parça görünür), farkı gizlemez.
    """
    units: list[str] = []
    for paragraph in _PARAGRAPH.split(text):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        merged: list[str] = []
        for part in _SENTENCE_END.split(paragraph):
            part = part.strip()
            if not part:
                continue
            if merged and _ends_with_abbreviation(merged[-1]):
                merged[-1] += " " + part
            else:
                merged.append(part)
        units.extend(merged)
    return units


def _word_diff(left: str, right: str) -> list[dict[str, str]]:
    left_words, right_words = left.split(), right.split()
    matcher = SequenceMatcher(None, [normalize_key(word) for word in left_words], [normalize_key(word) for word in right_words], autojunk=False)
    pieces: list[dict[str, str]] = []

    def add(op: str, words: list[str]) -> None:
        if not words:
            return
        text = " ".join(words)
        if pieces and pieces[-1]["op"] == op:
            pieces[-1]["text"] += " " + text
        else:
            pieces.append({"op": op, "text": text})

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            add("equal", right_words[j1:j2])
        else:
            add("delete", left_words[i1:i2])
            add("insert", right_words[j1:j2])
    return pieces


def _pair_block(left: list[str], right: list[str]) -> list[dict]:
    """Bir "değişen" bloktaki cümleleri sırayı bozmadan eşler: benzer çift `changed`, eşsiz kalanlar `removed`/`added`."""
    out: list[dict] = []
    if len(left) * len(right) > _PAIR_BUDGET:
        return [{"kind": "removed", "text": unit} for unit in left] + [{"kind": "added", "text": unit} for unit in right]
    right_words = [[normalize_key(word) for word in unit.split()] for unit in right]
    cursor = 0
    for unit in left:
        words = [normalize_key(word) for word in unit.split()]
        best, best_ratio = None, _PAIR_THRESHOLD
        for position in range(cursor, len(right)):
            matcher = SequenceMatcher(None, words, right_words[position], autojunk=False)
            if matcher.real_quick_ratio() < best_ratio or matcher.quick_ratio() < best_ratio:
                continue
            ratio = matcher.ratio()
            if ratio >= best_ratio:
                best, best_ratio = position, ratio
        if best is None:
            out.append({"kind": "removed", "text": unit})
            continue
        out.extend({"kind": "added", "text": added} for added in right[cursor:best])
        out.append({"kind": "changed", "left": unit, "right": right[best], "words": _word_diff(unit, right[best])})
        cursor = best + 1
    out.extend({"kind": "added", "text": added} for added in right[cursor:])
    return out


def compare_texts(left_text: str, right_text: str) -> dict:
    """İki metnin cümle düzeyinde farkı; değişen cümlelerde sözcük düzeyinde ayrıntı."""
    if len(left_text) > MAX_COMPARE_CHARS or len(right_text) > MAX_COMPARE_CHARS:
        raise CompareTooLarge("Belgeler karşılaştırma için çok uzun.")
    left, right = split_units(left_text), split_units(right_text)
    if len(left) > MAX_UNITS or len(right) > MAX_UNITS:
        raise CompareTooLarge("Belgeler karşılaştırma için çok uzun.")

    matcher = SequenceMatcher(None, [normalize_key(unit) for unit in left], [normalize_key(unit) for unit in right], autojunk=False)
    blocks: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            blocks.append({"kind": "equal", "units": right[j1:j2]})
        elif tag == "delete":
            blocks.extend({"kind": "removed", "text": unit} for unit in left[i1:i2])
        elif tag == "insert":
            blocks.extend({"kind": "added", "text": unit} for unit in right[j1:j2])
        else:
            blocks.extend(_pair_block(left[i1:i2], right[j1:j2]))

    counts = {
        "equal": sum(len(block["units"]) for block in blocks if block["kind"] == "equal"),
        "changed": sum(1 for block in blocks if block["kind"] == "changed"),
        "removed": sum(1 for block in blocks if block["kind"] == "removed"),
        "added": sum(1 for block in blocks if block["kind"] == "added"),
    }
    total = len(left) + len(right)
    return {
        "similarity": round(2 * counts["equal"] / total, 4) if total else 1.0,
        "left_units": len(left),
        "right_units": len(right),
        "counts": counts,
        "blocks": blocks,
    }
