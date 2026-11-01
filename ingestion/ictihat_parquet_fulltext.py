"""muhammedturan parquet fulltext tohumu. HTTP yok; resmi ready yazılmaz."""

from __future__ import annotations

from datetime import date
from typing import Any

from ingestion.hf_700k import (
    OVERSIZED_CHARS,
    PROVENANCE,
    PreparedRow,
    _ERROR_PAGE,
    _HTML,
    _MOJIBAKE,
    jsonable_id,
    parse_case_no,
    parse_chamber,
    parse_date_field,
    strip_third_party_markup,
)
from ingestion.text import content_hash
from ingestion.yargitay.parser import build_title, parse_chamber as parse_yargitay_chamber
from ingestion.yargitay.portal import document_url, portal_external_id

DATASET = "muhammedturan/turk-ictihat-kararlari-fulltext"
CANONICAL_SOURCE_NAME = "HuggingFace muhammedturan/turk-ictihat-kararlari-fulltext"
IMPORT_TYPE = "parquet_fulltext_seed"
MIN_TEXT_CHARS = 80


def valid_document_id(value: str) -> bool:
    return value.isdigit() and int(value) > 0


def prepare_parquet_fulltext_row(
    raw: dict[str, Any],
    *,
    inventory: dict[str, Any] | None = None,
    shard: int | None = None,
) -> PreparedRow | None:
    inventory = inventory or {}
    dataset_id = jsonable_id(raw.get("document_id"))
    if not valid_document_id(dataset_id):
        return None

    raw_text = strip_third_party_markup(str(raw.get("text") or ""))
    if len(raw_text) <= MIN_TEXT_CHARS:
        return None

    docket_no = parse_case_no(raw.get("esas_no")) or str(inventory.get("docket_no") or "")
    decision_no = parse_case_no(raw.get("karar_no")) or str(inventory.get("decision_no") or "")
    decision_date = parse_date_field(raw.get("karar_tarihi"))
    if decision_date is None:
        inv_date = inventory.get("decision_date")
        if isinstance(inv_date, date):
            decision_date = inv_date
    daire = str(raw.get("daire") or "").strip()
    chamber = (
        parse_yargitay_chamber(daire)
        or parse_chamber("Yargıtay", raw_text)
        or str(inventory.get("chamber") or "")
    )

    flagged = None
    if _MOJIBAKE.search(raw_text):
        flagged = ("broken_encoding", "Bozuk karakter kodlaması")
    elif _ERROR_PAGE.search(raw_text):
        flagged = ("error_page", "Hata veya erişim reddi sayfası")
    elif _HTML.search(raw_text) and raw_text.lstrip().lower().startswith("<html"):
        flagged = ("html_error_page", "HTML belge; beklenen temiz metin değil")

    external_id = portal_external_id(dataset_id)
    title = (
        build_title("Yargıtay", chamber or None, docket_no, decision_no, decision_date)
        if docket_no and decision_no
        else f"Yargıtay {dataset_id}"
    )
    return PreparedRow(
        dataset_id=dataset_id,
        source_code="ictihat_parquet",
        court_name="Yargıtay",
        chamber=chamber,
        docket_no=docket_no,
        decision_no=decision_no,
        decision_date=decision_date,
        external_id=external_id,
        title=title,
        raw_text=raw_text,
        content_hash=content_hash(raw_text),
        source_url=document_url(dataset_id),
        oversized=len(raw_text) > OVERSIZED_CHARS,
        quarantine_code=flagged[0] if flagged else None,
        quarantine_reason=flagged[1] if flagged else None,
        metadata={
            "provenance": PROVENANCE,
            "official_verified": False,
            "third_party": True,
            "source_adapter": "ictihat_parquet_fulltext",
            "dataset": DATASET,
            "hf_dataset": DATASET,
            "import_type": IMPORT_TYPE,
            "source_document_id": dataset_id,
            "portal_daire": daire,
            "shard": shard,
            "karar_turu": str(raw.get("karar_turu") or "") or None,
        },
    )
