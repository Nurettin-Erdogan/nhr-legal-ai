"""Doğrulanmamış resmi kaynaklar için iskelet adapter'lar.

Sahte fetch uygulanmaz. health_check blocked döner.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from worker.models import AdapterHealth, RecordOutcome, SyncRequest


class PlannedSourceAdapter:
    active = False
    verification_detail = "Resmi portal uç sözleşmesi doğrulanmadı"

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
                f"{self.verification_detail}. Çalışan çekim yazılmadı. "
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


class AymSourceAdapter(PlannedSourceAdapter):
    source_name = "aym"
    authority = "Anayasa Mahkemesi"
    official_source_url = "https://kararlarbilgibankasi.anayasa.gov.tr"
    verification_detail = (
        "Public arama JSON sözleşmesi doğrulandı; tam karar indirme akışı "
        "güvenlik doğrulaması istediği için otomatikleştirilmedi"
    )


class ResmiGazeteSourceAdapter(PlannedSourceAdapter):
    source_name = "resmi_gazete"
    authority = "Resmî Gazete"
    official_source_url = "https://www.resmigazete.gov.tr"
    verification_detail = (
        "Mevzuat tarih/sayı/numara doğrulaması mevzuat adapter'ına gömülü; "
        "bağımsız korpus adapter'ı değil"
    )

    def health_check(self) -> AdapterHealth:
        from ingestion.resmi_gazete.portal import ResmiGazeteClient

        try:
            result = ResmiGazeteClient(max_retries=1).verify_legislation(
                publication_date=None,
                issue_no="25134",
                law_no="4857",
                law_name="İş Kanunu",
            )
            state = "healthy" if result.verified else "degraded"
            return AdapterHealth(
                self.source_name,
                state,
                "Resmî Gazete künye doğrulama sözleşmesi çalışıyor; "
                "mevzuat sync içinde kullanılıyor",
                active=False,
            )
        except Exception as exc:  # noqa: BLE001
            return AdapterHealth(self.source_name, "failed", str(exc), active=False)


class KdkSourceAdapter(PlannedSourceAdapter):
    source_name = "kdk"
    authority = "Kamu Denetçiliği Kurumu"
    official_source_url = "https://kararlar.ombudsman.gov.tr"
    verification_detail = (
        "KDK resmî karar portalı doğrulandı; arama ve tam metin sözleşmesi "
        "henüz fixture ile sabitlenmedi"
    )
