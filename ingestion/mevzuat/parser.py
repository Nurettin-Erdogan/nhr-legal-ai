"""Bedesten mevzuat JSON yanıtlarını LegislationRecord'a çevirir."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterator, Mapping

from ingestion.mevzuat.models import LegislationRecord
from ingestion.text import content_hash, html_to_text, normalize_text, tr_casefold

# Bedesten tür kodları -> legislation_details.legislation_type CHECK değerleri.
_TYPE_MAP = {
    "KANUN": "law",
    "KHK": "decree",
    "CB_KARARNAME": "decree",
    "YONETMELIK": "regulation",
    "CB_YONETMELIK": "regulation",
    "KKY": "regulation",
    "UY": "regulation",
    "TUZUK": "regulation",
    "TEBLIGLER": "communique",
    "TEBLIG": "communique",
    "CB_KARAR": "other",
    "CB_GENELGE": "other",
    "MULGA": "other",
}

_CONSTITUTION_LAW_NOS = {"2709"}


def map_legislation_type(
    portal_type: str | None,
    *,
    law_no: str | None = None,
    law_name: str | None = None,
) -> str:
    """Portal türünü şema CHECK değerine çevirir; Anayasa özel durumunu korur."""
    if law_no and str(law_no).strip() in _CONSTITUTION_LAW_NOS:
        return "constitution"
    if law_name and "anayasa" in tr_casefold(law_name) and (law_no or "") in {
        "",
        *_CONSTITUTION_LAW_NOS,
    }:
        return "constitution"
    key = (portal_type or "").strip().upper()
    return _TYPE_MAP.get(key, "other")


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def portal_type_name(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _as_text(value.get("name"))
    return _as_text(value)


def parse_portal_date(value: Any) -> date | None:
    text = _as_text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00").split("T", 1)[0]
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(normalized, pattern).date()
        except ValueError:
            continue
    return None


def article_external_id(law_no: str, article_no: str, *, portal_type: str | None) -> str:
    kind = (portal_type or "other").strip().lower() or "other"
    return f"mevzuat:{kind}:{law_no.strip()}:m.{article_no.strip()}"


def article_title_line(law_name: str, article_no: str, article_title: str | None) -> str:
    head = f"{law_name} m. {article_no}"
    if article_title:
        return f"{head} — {article_title}"
    return head


def iter_article_nodes(tree: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    """Bölüm başlıklarını atlayıp madde numarası olan düğümleri belge sırasıyla üretir."""

    def walk(nodes: Any) -> Iterator[Mapping[str, Any]]:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            article_no = _as_text(node.get("maddeNo"))
            madde_id = _as_text(node.get("maddeId"))
            if article_no and madde_id:
                yield node
            yield from walk(node.get("children"))

    if "children" in tree:
        yield from walk(tree.get("children"))
    else:
        yield from walk(tree)


def record_from_article(
    *,
    document: Mapping[str, Any],
    article: Mapping[str, Any],
    article_html: str,
    scraped_at: datetime | None = None,
) -> LegislationRecord:
    law_no = _as_text(document.get("mevzuatNo"))
    law_name = _as_text(document.get("mevzuatAdi"))
    article_no = _as_text(article.get("maddeNo"))
    madde_id = _as_text(article.get("maddeId"))
    mevzuat_id = _as_text(document.get("mevzuatId")) or _as_text(article.get("mevzuatId"))
    portal_type = portal_type_name(document.get("mevzuatTur"))
    if not law_no or not law_name or not article_no or not madde_id or not mevzuat_id:
        raise ValueError("Mevzuat maddesi için kanun no, ad, madde no ve portal kimliği zorunludur")

    body = normalize_text(html_to_text(article_html))
    if not body:
        raise ValueError(f"Madde metni HTML'den ayrıştırılamadı: {madde_id}")

    article_title = _as_text(article.get("title")) or _as_text(article.get("maddeBaslik"))
    source_url = _as_text(document.get("url"))
    gazette_date = parse_portal_date(document.get("resmiGazeteTarihi"))
    version_date = (
        parse_portal_date(article.get("guncellemeTarihi"))
        or parse_portal_date(document.get("guncellemeTarihi"))
        or gazette_date
    )
    return LegislationRecord(
        record_type="legislation",
        legislation_type=map_legislation_type(
            portal_type, law_no=law_no, law_name=law_name
        ),
        law_name=law_name,
        law_no=law_no,
        article_no=article_no,
        article_title=article_title,
        title=article_title_line(law_name, article_no, article_title),
        raw_text=body,
        external_id=article_external_id(law_no, article_no, portal_type=portal_type),
        content_hash=content_hash(body),
        source_url=source_url,
        official_gazette_no=_as_text(document.get("resmiGazeteSayisi")),
        official_gazette_date=gazette_date,
        version_date=version_date,
        scraped_at=scraped_at,
        metadata={
            "source": "bedesten.adalet.gov.tr/mevzuat",
            "mevzuat_id": mevzuat_id,
            "madde_id": madde_id,
            "mevzuat_tur": portal_type,
            "mevzuat_tertip": document.get("mevzuatTertip"),
        },
    )
