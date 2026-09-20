"""altaidevorg Yargıtay ham HTML kayıtlarını bulk_seed satırına çevirir."""

from __future__ import annotations

from ingestion.hf_700k import (
    OVERSIZED_CHARS,
    PROVENANCE,
    PreparedRow,
    jsonable_id,
    parse_case_no,
    parse_chamber,
    parse_date_field,
    strip_third_party_markup,
)
from ingestion.text import content_hash, html_to_text
from ingestion.yargitay.parser import build_title, parse_chamber as parse_yargitay_chamber
from ingestion.yargitay.portal import document_url, portal_external_id

ALTAI_DATASET = "altaidevorg/yargitay-karar-data-raw"
CANONICAL_SOURCE_NAME = "HuggingFace altaidevorg/yargitay-karar-data-raw"


def html_content_to_text(content: str) -> str:
    text = html_to_text(content or "")
    for marker in (
        '"İçtihat Metni"',
        "“İçtihat Metni”",
        "'İçtihat Metni'",
        "İçtihat Metni",
        '"Ictihat Metni"',
    ):
        text = text.replace(marker, "")
    return strip_third_party_markup(text)


def prepare_altai_row(raw: dict[str, object]) -> PreparedRow:
    dataset_id = jsonable_id(raw.get("id"))
    docket_no = parse_case_no(raw.get("esasNo")) or ""
    decision_no = parse_case_no(raw.get("kararNo")) or ""
    decision_date = parse_date_field(raw.get("kararTarihi"))
    html = str(raw.get("content") or "")
    text = html_content_to_text(html) if html.strip() else ""
    daire = str(raw.get("daire") or "").strip()
    chamber = parse_yargitay_chamber(daire) or parse_chamber("Yargıtay", text)

    flagged = None
    if not dataset_id:
        flagged = ("invalid_identity", "id eksik")
    elif not html.strip() or not text.strip():
        flagged = ("empty_text", "HTML gövde boş veya parse edilemedi")
    elif decision_date is None:
        flagged = ("missing_date", f"kararTarihi geçersiz: {raw.get('kararTarihi')!r}")
    elif not docket_no or not decision_no:
        flagged = ("invalid_case_no", "esasNo veya kararNo YEAR/NO değil")

    external_id = portal_external_id(dataset_id) if dataset_id else ""
    title = (
        build_title("Yargıtay", chamber or None, docket_no, decision_no, decision_date)
        if docket_no and decision_no
        else f"Yargıtay {dataset_id}"
    )
    return PreparedRow(
        dataset_id=dataset_id,
        source_code="altai_ygty",
        court_name="Yargıtay",
        chamber=chamber or daire,
        docket_no=docket_no,
        decision_no=decision_no,
        decision_date=decision_date,
        external_id=external_id,
        title=title,
        raw_text=text,
        content_hash=content_hash(text) if text else "",
        source_url=document_url(dataset_id) if dataset_id else None,
        oversized=len(text) > OVERSIZED_CHARS,
        quarantine_code=flagged[0] if flagged else None,
        quarantine_reason=flagged[1] if flagged else None,
        metadata={
            "provenance": PROVENANCE,
            "official_verified": False,
            "third_party": True,
            "source_adapter": "hf_altai_yargitay",
            "hf_dataset": ALTAI_DATASET,
            "source_document_id": dataset_id,
            "html_parsed": True,
            "portal_daire": daire,
            "siraNo": raw.get("siraNo"),
            "cluster_ids_omitted": True,
        },
    )
