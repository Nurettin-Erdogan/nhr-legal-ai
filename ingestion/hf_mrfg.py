"""mrfg/turkish-court-decisions (11M) satırlarını bulk_seed 'pending' satırına dönüştürür.

Üçüncü taraf derlemedir; resmî doğrulanmış sayılmaz (`official_verified: false`).
Yalnız Yargıtay ve Danıştay alınır: bu kaynakların resmî portal adaptörü var, bu yüzden
sonradan kayıt kayıt doğrulanabilir. Maskeli (TCKN/IBAN vb.) kayıtlar alınmaz.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from ingestion.hf_700k import (
    OVERSIZED_CHARS,
    PROVENANCE,
    PreparedRow,
    _quarantine,
    jsonable_id,
    parse_case_no,
    parse_date_field,
    prepare_row,
    strip_third_party_markup,
)
from ingestion.text import content_hash
from ingestion.yargitay.parser import build_title

HF_DATASET = "mrfg/turkish-court-decisions"
CANONICAL_SOURCE_NAME = f"HuggingFace {HF_DATASET}"
IMPORT_TYPE = "mrfg_seed"
# Resmî portal adaptörü olanlar (kayıt kayıt doğrulanabilir) ve olmayanlar. İstinaf (UYAP Emsal) ve
# AYM norm denetimi kayıtları da alınır ama "doğrulanmadı" kalır: `verify_seeds` yalnız
# Yargıtay/Danıştay kaynaklarını doğrular. AYM bireysel başvuru zaten resmî olarak çekiliyor.
PORTAL_SOURCES = {"yargitay": "ygty", "danistay": "dnsy"}
EXTRA_SOURCES = {"emsal": "emsl", "aym_norm": "aymn"}
SOURCES = {**PORTAL_SOURCES, **EXTRA_SOURCES}
_EXTRA_PREFIX = {"emsl": "emsal", "aymn": "aym-norm"}


def _iso_to_tr(value: object) -> str:
    text = str(value or "").strip()
    parts = text.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return text


def _prepare_extra_row(code: str, raw: dict[str, Any]) -> PreparedRow | None:
    """İstinaf (emsal) ve AYM norm denetimi: Yargıtay/Danıştay'a özgü künye ayrıştırması yok."""
    dataset_id = jsonable_id(raw.get("document_id"))
    if not dataset_id:
        return None
    court = str(raw.get("court") or "").strip()
    court_name = "Anayasa Mahkemesi" if code == "aymn" else (court or "UYAP Emsal")
    docket_no = parse_case_no(raw.get("esas_no")) or ""
    decision_no = parse_case_no(raw.get("karar_no")) or ""
    decision_date = parse_date_field(_iso_to_tr(raw.get("karar_tarihi")))
    raw_text = strip_third_party_markup(str(raw.get("text") or ""))
    flagged = _quarantine(raw_text, decision_date, raw.get("karar_tarihi"))
    title = (
        build_title(court_name, "Norm Denetimi" if code == "aymn" else None, docket_no, decision_no, decision_date)
        if docket_no and decision_no
        else f"{court_name} {dataset_id}"
    )
    return PreparedRow(
        dataset_id=dataset_id,
        source_code=code,
        court_name=court_name,
        chamber="Norm Denetimi" if code == "aymn" else "",
        docket_no=docket_no,
        decision_no=decision_no,
        decision_date=decision_date,
        external_id=f"{_EXTRA_PREFIX[code]}:{dataset_id}",
        title=title,
        raw_text=raw_text,
        content_hash=content_hash(raw_text) if raw_text else "",
        source_url=None,
        oversized=len(raw_text) > OVERSIZED_CHARS,
        quarantine_code=flagged[0] if flagged else None,
        quarantine_reason=flagged[1] if flagged else None,
        metadata={
            "provenance": PROVENANCE,
            "official_verified": False,
            "third_party": True,
            "source_adapter": "hf_mrfg",
            "hf_dataset": HF_DATASET,
            "import_type": IMPORT_TYPE,
            "hf_source": str(raw.get("source") or ""),
            "source_document_id": dataset_id,
            "portal_court": court or None,
            "verifiable": False,
            "raw_sha256": raw.get("raw_sha256"),
        },
    )


def prepare_mrfg_row(raw: dict[str, Any]) -> PreparedRow | None:
    """None: alınmayacak kayıt (desteklenmeyen kaynak veya maskeli)."""
    code = SOURCES.get(str(raw.get("source") or ""))
    if code is None or int(raw.get("masked_count") or 0) > 0:
        return None
    if code in _EXTRA_PREFIX:
        return _prepare_extra_row(code, raw)
    row = prepare_row(
        {
            "source": code,
            "id": raw.get("document_id"),
            "esasNo": raw.get("esas_no"),
            "kararNo": raw.get("karar_no"),
            "kararTarihi": _iso_to_tr(raw.get("karar_tarihi")),
            "text": raw.get("text"),
        }
    )
    if row is None:
        return None
    metadata = {
        **row.metadata,
        "provenance": PROVENANCE,
        "official_verified": False,
        "third_party": True,
        "source_adapter": "hf_mrfg",
        "hf_dataset": HF_DATASET,
        "import_type": IMPORT_TYPE,
        "source_document_id": jsonable_id(raw.get("document_id")),
        "portal_daire": str(raw.get("court") or "") or None,
        "raw_sha256": raw.get("raw_sha256"),
    }
    return dataclasses.replace(row, chamber=row.chamber or str(raw.get("court") or "").strip(), metadata=metadata)
