"""Türkçe karakter geri getirme: "davaci kac yil calismis" -> "davacı kaç yıl çalışmış".

Avukatlar sorularını sık sık Türkçe karakter olmadan yazar. Arama dizini (`turkish` tsvector) ve
cümle puanlaması aksanları katlamaz; "kidem tazminati" ile "kıdem tazminatı" farklı sözcüklerdir ve
28 milyon parçalık dizini yeniden kurmak mümkün değildir. Bu yüzden **sorgu tarafında** aksanlar geri
getirilir.

Yöntem: resmî hukuk metinlerinden (scripts/build_tr_vocabulary.py) çıkarılmış, her ASCII biçim için en
sık Türkçe biçimi veren bir sözlük. "ise/işe", "sık/sik" gibi gerçekten belirsiz sözcükler komşu
sözcüklere bakılarak seçilir. Kural tabanlıdır, yereldir, ağ ve model gerektirmez.

Güvenlik ilkeleri:
- Soruda zaten bir Türkçe harf (ç ğ ı ö ş ü) varsa metne **dokunulmaz** (kullanıcı Türkçe yazıyor).
- Yalnız arama metni değişir; kullanıcının yazdığı soru olduğu gibi saklanır.
- Sözlükte olmayan sözcük, kısaltma (TBK, HMK), sayı ve kesme işaretinden sonraki ekler değişmez.
"""

from __future__ import annotations

import gzip
import json
import re
from functools import lru_cache
from pathlib import Path

RESOURCE = Path(__file__).resolve().parent / "resources" / "tr_diacritics.json.gz"

_TURKISH_LETTERS = re.compile("[çğıöşüÇĞİÖŞÜâîûÂÎÛ]")
_TOKEN = re.compile(r"[A-Za-z]+")
_FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")
_LOWER_TR = str.maketrans({"İ": "i", "I": "ı"})
_UPPER_TR = str.maketrans({"i": "İ", "ı": "I"})
_MIN_ACRONYM = 4  # tamamen büyük harfli ve daha kısa belirteçler kısaltma sayılır (TBK, HMK, SGK)
_SUFFIX_MARKERS = "'’‘`´ʼ′"  # kesme işareti çeşitleri: "Yargıtay'ın", "30'uncu"


def follows_suffix_marker(text: str, start: int) -> bool:
    """Belirteç kesme işaretinden ya da rakamdan hemen sonra mı geliyor? ("30'uncu", "1.nci"): ek, sözcük değil."""
    return start > 0 and (text[start - 1] in _SUFFIX_MARKERS or text[start - 1].isdigit())


def fold(word: str) -> str:
    """Küçük harfli Türkçe sözcüğün ASCII karşılığı."""
    return word.translate(_FOLD)


def lower_tr(text: str) -> str:
    return text.translate(_LOWER_TR).lower()


def upper_tr(text: str) -> str:
    return text.translate(_UPPER_TR).upper()


@lru_cache(maxsize=1)
def _vocabulary() -> tuple[dict[str, str], dict[str, dict]]:
    """(katlanmış -> en sık biçim, belirsiz sözcükler için bağlam istatistiği). Yoksa boş sözlük."""
    try:
        with gzip.open(RESOURCE, "rt", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}, {}
    return data.get("map", {}), data.get("ambiguous", {})


def _choose_ambiguous(entry: dict, previous: str | None, following: str | None) -> str:
    """Belirsiz sözcükte komşu sözcüklerin hangi biçimle daha sık geldiğine bakar."""
    best, best_score = entry["default"], -1
    for candidate, stats in entry["candidates"].items():
        score = 0
        if previous:
            score += stats.get("p", {}).get(previous, 0)
        if following:
            score += stats.get("n", {}).get(following, 0)
        if score > best_score or (score == best_score and candidate == entry["default"]):
            best, best_score = candidate, score
    return best


def _match_case(original: str, restored: str) -> str:
    if original.isupper():
        return upper_tr(restored)
    if original[0].isupper() and original[1:].islower():
        return upper_tr(restored[0]) + restored[1:]
    if original.islower():
        return restored
    return restored  # karışık büyük/küçük harf: yeniden yazım biçimi korunamaz


def restore_turkish(text: str) -> str:
    """ASCII yazılmış Türkçe sorudaki sözcüklerin Türkçe karakterli biçimini geri getirir."""
    if not text or _TURKISH_LETTERS.search(text):
        return text
    mapping, ambiguous = _vocabulary()
    if not mapping and not ambiguous:
        return text
    tokens = list(_TOKEN.finditer(text))
    # Anahtar ASCII'dir: yazılan `I` Türkçe `ı` mı `İ` mi belli olmadığından düz küçük harfe çevrilir
    # (sözlük anahtarları zaten katlanmıştır: ı -> i).
    keys = [match.group().lower() for match in tokens]
    pieces: list[str] = []
    cursor = 0
    for index, match in enumerate(tokens):
        token = match.group()
        pieces.append(text[cursor : match.start()])
        cursor = match.end()
        pieces.append(token)
        if len(token) < 2:
            continue
        if token.isupper() and len(token) < _MIN_ACRONYM:
            continue  # TBK, HMK, SGK...
        if follows_suffix_marker(text, match.start()):
            continue  # kesme işareti/rakamdan sonraki ek ("Yargıtay'ın", "30'uncu"): sözcük değil
        key = keys[index]
        if key in ambiguous:
            previous = keys[index - 1] if index > 0 else None
            following = keys[index + 1] if index + 1 < len(tokens) else None
            restored = _choose_ambiguous(ambiguous[key], previous, following)
        else:
            restored = mapping.get(key)
        if restored and restored != key:
            pieces[-1] = _match_case(token, restored)
    pieces.append(text[cursor:])
    return "".join(pieces)
