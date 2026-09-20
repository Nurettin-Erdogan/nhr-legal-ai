"""Danıştay daire ve kurul adlarını portal `daireKurul` biçimine çeker."""

from __future__ import annotations

import re

from ingestion.text import tr_casefold

_IDDK = re.compile(r"idari\s+dava\s+daireleri\s+kurulu")
_VDDK = re.compile(r"vergi\s+dava\s+daireleri\s+kurulu")
_IBBK = re.compile(r"i(?:ç|c)tihat(?:ları|lari|ı|i)?\s+birle(?:ş|s)tirme\s+kurulu")
_NUMBERED = re.compile(
    r"(?:danıştay\s+)?(\d{1,2})\s*\.\s*daire(?:\s+başkanlığı)?"
)
_ORDINAL_WORDS = (
    ("on yedinci", 17),
    ("onyedinci", 17),
    ("on altıncı", 16),
    ("on altinci", 16),
    ("onaltıncı", 16),
    ("onaltinci", 16),
    ("on beşinci", 15),
    ("on besinci", 15),
    ("onbeşinci", 15),
    ("onbesinci", 15),
    ("on dördüncü", 14),
    ("on dorduncu", 14),
    ("ondördüncü", 14),
    ("ondorduncu", 14),
    ("on üçüncü", 13),
    ("on ucuncu", 13),
    ("onüçüncü", 13),
    ("onucuncu", 13),
    ("on ikinci", 12),
    ("onikinci", 12),
    ("on birinci", 11),
    ("onbirinci", 11),
    ("onuncu", 10),
    ("dokuzuncu", 9),
    ("sekizinci", 8),
    ("yedinci", 7),
    ("altıncı", 6),
    ("altinci", 6),
    ("beşinci", 5),
    ("besinci", 5),
    ("dördüncü", 4),
    ("dorduncu", 4),
    ("üçüncü", 3),
    ("ucuncu", 3),
    ("ikinci", 2),
    ("birinci", 1),
)
_ORDINAL_DAIRE = re.compile(
    r"(" + "|".join(re.escape(word) for word, _ in _ORDINAL_WORDS) + r")\s+daire"
)


def parse_chamber(text: str) -> str | None:
    """`6. Daire` veya `İdari Dava Daireleri Kurulu` döndürür."""
    folded = tr_casefold(text)
    if _IDDK.search(folded):
        return "İdari Dava Daireleri Kurulu"
    if _VDDK.search(folded):
        return "Vergi Dava Daireleri Kurulu"
    if _IBBK.search(folded):
        return "İçtihatları Birleştirme Kurulu"

    numbered = _NUMBERED.search(folded)
    if numbered:
        return f"{int(numbered.group(1))}. Daire"

    ordinal = _ORDINAL_DAIRE.search(folded)
    if ordinal:
        word = ordinal.group(1)
        number = next(value for token, value in _ORDINAL_WORDS if token == word)
        return f"{number}. Daire"

    return None
