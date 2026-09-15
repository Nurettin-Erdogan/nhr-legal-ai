"""Doğrulanmamış resmi kaynaklar için iskelet adapter'lar.

Sahte fetch uygulanmaz. health_check blocked döner.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from worker.models import AdapterHealth, RecordOutcome, SyncRequest


class PlannedSourceAdapter:
    active = False

    def validate(self, record: Any) -> list[str]:
        return ["adapter_not_implemented"]

    def dedup_identity(self, record: Any) -> str:
        return ""

    def version_identity(self, record: Any) -> str:
        return ""

    def provenance(self, record: Any) -> dict[str, Any]:
        return {
            "canonical_legal_source": self.authority,
            "ingestion_method": "unverified",
        }

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(
            source_name=self.source_name,
            state="blocked",
            detail=(
                "Resmi portal uç sözleşmesi doğrulanmadan çalışan çekim yazılmadı. "
                f"Kaynak: {self.official_source_url}"
            ),
            active=False,
        )

    def sync(
        self,
        request: SyncRequest,
        *,
        cursor: dict[str, Any],
        connection: Any,
        dry_run: bool,
        should_stop: Any,
    ) -> Iterator[tuple[RecordOutcome, dict[str, Any]]]:
        raise RuntimeError(
            f"{self.source_name} henüz ACTIVE değil; tahminî scraper üretilmedi"
        )


class DanistaySourceAdapter(PlannedSourceAdapter):
    source_name = "danistay"
    authority = "Danıştay"
    official_source_url = "https://karararama.danistay.gov.tr"


class AymSourceAdapter(PlannedSourceAdapter):
    source_name = "aym"
    authority = "Anayasa Mahkemesi"
    official_source_url = "https://kararlarbilgibankasi.anayasa.gov.tr"


class ResmiGazeteSourceAdapter(PlannedSourceAdapter):
    source_name = "resmi_gazete"
    authority = "Resmî Gazete"
    official_source_url = "https://www.resmigazete.gov.tr"
