"""mrfg/turkish-court-decisions (11M) satırlarını bulk_seed 'pending' satırına dönüştürür.

Üçüncü taraf derlemedir; resmî doğrulanmış sayılmaz (`official_verified: false`).
Yalnız Yargıtay ve Danıştay alınır: bu kaynakların resmî portal adaptörü var, bu yüzden
sonradan kayıt kayıt doğrulanabilir. Maskeli (TCKN/IBAN vb.) kayıtlar alınmaz.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from ingestion.hf_700k import PROVENANCE, PreparedRow, jsonable_id, prepare_row

HF_DATASET = "mrfg/turkish-court-decisions"
CANONICAL_SOURCE_NAME = f"HuggingFace {HF_DATASET}"
IMPORT_TYPE = "mrfg_seed"
SOURCES = {"yargitay": "ygty", "danistay": "dnsy"}


def _iso_to_tr(value: object) -> str:
    text = str(value or "").strip()
    parts = text.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return text


def prepare_mrfg_row(raw: dict[str, Any]) -> PreparedRow | None:
    """None: alınmayacak kayıt (desteklenmeyen kaynak veya maskeli)."""
    code = SOURCES.get(str(raw.get("source") or ""))
    if code is None or int(raw.get("masked_count") or 0) > 0:
        return None
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
