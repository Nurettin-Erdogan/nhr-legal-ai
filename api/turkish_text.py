"""Türkçe metni arama ve eşleme için tek biçime indirme ("İ/I/ı" farkı sonucu değiştirmesin)."""

from __future__ import annotations

TR_FOLD = str.maketrans("İIıŞÇĞÖÜ", "iiişçğöü")


def fold(text: str | None) -> str:
    """Türkçe harf çiftlerini tek biçime indirip küçük harfe çevirir."""
    return " ".join((text or "").translate(TR_FOLD).lower().split())


def fold_keep_length(text: str) -> str:
    """Arama için katlar ama uzunluğu korur: bulunan konum özgün metinde aynı yere denk gelir."""
    return "".join(ch if len(ch) == 1 else "i" for ch in (c.lower() for c in text.translate(TR_FOLD)))
