"""Bekleyen mevzuat kanunları için Resmî Gazete + MBS doğrulama worker'ı.

Bedesten çekiminden ayrı çalışır; `python -m worker.runner run --source mevzuat_verify`.
Daemon ve `backfill --source all` bu kaynağı otomatik açmaz.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Callable

from ingestion.mevzuat.official_verify import iter_pending_verifications
from ingestion.mevzuat_bilgi_sistemi.portal import MbsClient
from ingestion.resmi_gazete.portal import ResmiGazeteClient
from worker.config import get_worker_settings
from worker.models import AdapterHealth, RecordOutcome, SyncRequest


class MevzuatVerifyAdapter:
    source_name = "mevzuat_verify"
    authority = "Resmî Gazete / Mevzuat Bilgi Sistemi"
    active = True
    official_source_url = "https://www.resmigazete.gov.tr"

    def __init__(
        self,
        *,
        gazette_client: ResmiGazeteClient | None = None,
        mbs_client: MbsClient | None = None,
    ) -> None:
        self.gazette_client = gazette_client
        self.mbs_client = mbs_client
        self.last_cursor: dict[str, Any] = {}

    def _settings(self):
        return get_worker_settings()

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(
            self.source_name,
            "healthy",
            "RG+MBS doğrulaması kanun bazlı ayrı worker olarak çalışır",
        )

    def validate(self, record: Any) -> list[str]:
        return []

    def dedup_identity(self, record: Any) -> str:
        return str(getattr(record, "external_id", "") or "")

    def version_identity(self, record: Any) -> str:
        return ""

    def provenance(self, record: Any) -> dict[str, Any]:
        return {
            "source_type": "legislation",
            "authority": self.authority,
            "ingestion_method": "mevzuat_official_verify",
        }

    def sync(
        self,
        request: SyncRequest,
        *,
        cursor: dict[str, Any],
        connection: Any,
        dry_run: bool,
        should_stop: Callable[[], bool],
    ) -> Iterator[tuple[RecordOutcome, dict[str, Any]]]:
        settings = self._settings()
        limit = request.max_records or settings.mevzuat_max_articles
        gazette = self.gazette_client or ResmiGazeteClient(
            max_retries=settings.max_retries,
            retry_backoff_seconds=max(1.0, settings.mevzuat_delay_seconds),
        )
        mbs = self.mbs_client or MbsClient(
            max_retries=settings.max_retries,
            retry_backoff_seconds=max(1.0, settings.mevzuat_delay_seconds),
        )
        processed = 0
        ready = 0
        pending = 0
        for item in iter_pending_verifications(
            connection,
            limit=limit,
            gazette_client=gazette,
            mbs_client=mbs,
            dry_run=dry_run,
        ):
            if should_stop():
                break
            processed += 1
            extra = {
                "external_id": f"mevzuat:{item['law_no']}:verify",
                "law_no": item["law_no"],
                "requests_made": item["requests_made"],
                "verified": item["ready"],
            }
            if item["ready"]:
                ready += 1
                yield "updated", extra
            else:
                pending += 1
                yield "unchanged", extra
        self.last_cursor = {
            "complete": processed < limit,
            "processed": processed,
            "ready": ready,
            "pending": pending,
            "reconciled": processed < limit,
            "window_complete": processed < limit,
        }
