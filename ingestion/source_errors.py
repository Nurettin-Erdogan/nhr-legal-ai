"""Portal hatalarını kayıt atlama ile kaynak durdurma olarak ayırır.

CAPTCHA ayrı exception'dır ve burada çözülmez. 429 ve kopan bağlantı aynı
kayıtta kalır; tek belgeye özgü bozuk yanıt bir sonraki kayda geçmeyi
engellemez.
"""

from __future__ import annotations

_RATE_LIMIT_MARKERS = ("429", "hız sınırı", "hiz siniri")
_TRANSIENT_MARKERS = (
    "10054",
    "10060",
    "10061",
    "bağlantı",
    "baglanti",
    "connection reset",
    "connection aborted",
    "timeout",
    "timed out",
    "zaman aşımı",
    "zaman asimi",
)


def error_text(exc: BaseException | str) -> str:
    return str(exc).casefold()


def is_rate_limited(exc: BaseException | str) -> bool:
    text = error_text(exc)
    return any(marker in text for marker in _RATE_LIMIT_MARKERS)


def is_transient_transport(exc: BaseException | str) -> bool:
    text = error_text(exc)
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def should_retry_same_record(exc: BaseException | str) -> bool:
    """True ise offset ilerletilmez; False ise kayıt atlanır."""
    return is_rate_limited(exc) or is_transient_transport(exc)


def is_verification_cooldown_error(exc: BaseException | str) -> bool:
    """RG/MBS geçici kesinti: turu durdur, kaynağı soğut, worker'ı öldürme."""
    text = error_text(exc)
    if "bulunamadı" in text or "bulunamadi" in text:
        return False
    if should_retry_same_record(exc):
        return True
    return (
        "json olmayan" in text
        or "http hatası: 5" in text
        or "http hatasi: 5" in text
        or "http hatası: 429" in text
        or "http hatasi: 429" in text
    )

