"""Sayıştay karar detay sayfasını (HTML) OfficialDoc'a çevirir."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import lxml.html

from ingestion.official_docs import OfficialDoc
from ingestion.sayistay.portal import KINDS, SayistayClient, SayistayError
from ingestion.text import content_hash, normalize_text

# Gerçek kısa kararlar var (ör. "temyiz konusu dosya işlemden kaldırılmıştır", 156 karakter); yalnız boş sayfa elenir.
MIN_TEXT_CHARS = 40
# Portal bazen karar metni yerine kendi hata sayfasını (ör. SQL Server bağlantı hatası) döndürür;
# bu, karar metni olarak kaydedilmemelidir.
_ERROR_PAGE = re.compile(
    r"Microsoft OLE DB|ODBC|SQL Server|Cannot open database|Server Error|Runtime Error|Unhandled Exception|"
    r"Stack Trace|Service Unavailable|An error occurred while processing",
    re.I,
)


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    for pattern in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except ValueError:
            continue
    return None


def _fields(document: lxml.html.HtmlElement) -> dict[str, str]:
    fields: dict[str, str] = {}
    rows = document.xpath('//div[contains(@class,"row")][div[contains(@class,"col-3")]/b][div[contains(@class,"col-9")]]')
    for row in rows:
        label = " ".join(row.xpath('string(./div[contains(@class,"col-3")]/b)').split())
        value = " ".join(row.xpath('string(./div[contains(@class,"col-9")])').split())
        if label:
            fields[label] = value
    return fields


def _body_text(document: lxml.html.HtmlElement) -> str:
    nodes = document.xpath('//div[@id="metin"]')
    if not nodes:
        raise SayistayError("Sayıştay karar metni (#metin) bulunamadı")
    node = nodes[0]
    for br in node.xpath(".//br"):
        br.tail = "\n" + (br.tail or "")
    for block in node.xpath(".//p | .//div | .//li"):
        block.tail = "\n" + (block.tail or "")
    return normalize_text(node.text_content())


def build_doc(kind_key: str, row: dict[str, Any], html: str, *, fetched_at: datetime | None = None) -> OfficialDoc:
    kind = KINDS[kind_key]
    record_id = int(row["Id"])
    document = lxml.html.fromstring(html)
    fields = _fields(document)
    text = _body_text(document)
    if _ERROR_PAGE.search(text[:600]):
        raise SayistayError(f"Sayıştay {kind.label} #{record_id}: karar metni yerine portal hata sayfası döndü")
    if len(text) < MIN_TEXT_CHARS:
        raise SayistayError(f"Sayıştay {kind.label} #{record_id}: karar metni çok kısa ({len(text)} karakter)")
    decision_date = parse_date(row.get(kind.date_field))
    if decision_date is None:
        raise SayistayError(f"Sayıştay {kind.label} #{record_id}: karar tarihi okunamadı")
    date_text = decision_date.strftime("%d.%m.%Y")
    karar_no = fields.get("Karar No") or str(row.get("KARARNO", "")).strip() or "-"
    if kind_key == "temyiz":
        title = (
            f"Sayıştay Temyiz Kurulu, {fields.get('Daire', row.get('ILAMDAIRESI', ''))}. Daire ilamı, "
            f"Dosya No {fields.get('Dosya No', '-')}, Tutanak No {fields.get('Tutanak No', '-')} ({date_text})"
        )
    elif kind_key == "daire":
        title = (
            f"Sayıştay {fields.get('Daire', row.get('YARGILAMADAIRESI', ''))}. Daire, İlam No "
            f"{fields.get('İlam No', '-')}, Karar No {karar_no} ({date_text})"
        )
    else:
        title = f"Sayıştay Genel Kurulu, Karar No {karar_no} ({date_text})"
    metadata = {
        "source": "sayistay",
        "kind": kind_key,
        "kind_label": kind.label,
        "sayistay_id": record_id,
        "fields": fields,
        "provenance": "official_portal",
        "official_verified": True,
        "third_party": False,
        "decision_date": decision_date.isoformat(),
    }
    return OfficialDoc(
        external_id=f"sayistay:{kind_key}:{record_id}",
        title=title,
        raw_text=text,
        content_hash=content_hash(text),
        source_url=SayistayClient.detail_url(kind, record_id),
        decision_date=decision_date,
        fetched_at=fetched_at or datetime.now().astimezone(),
        metadata=metadata,
    )
