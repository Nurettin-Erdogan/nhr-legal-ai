"""Bekleyen mevzuat kanunları için Resmî Gazete + MBS doğrulama worker'ı.

Bedesten çekiminden ayrı çalışır; `python -m worker.runner run --source mevzuat_verify`.
Daemon ve `backfill --source all` bu kaynağı otomatik açmaz.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from ingestion.mevzuat.official_verify import iter_pending_verifications
from ingestion.mevzuat_bilgi_sistemi.portal import MbsClient
from ingestion.resmi_gazete.portal import ResmiGazeteClient
from worker.config import get_worker_settings
from worker.models import AdapterHealth, RecordOutcome, SyncRequest


def _retry_at(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


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
        now = datetime.now(UTC)
        gazette_until = _retry_at(cursor.get("gazette_retry_at"))
        mbs_until = _retry_at(cursor.get("mbs_retry_at"))
        skip_gazette = gazette_until is not None and gazette_until > now
        skip_mbs = mbs_until is not None and mbs_until > now
        cooling = skip_gazette or skip_mbs
        last_cursor = {
            "gazette_retry_at": cursor.get("gazette_retry_at"),
            "mbs_retry_at": cursor.get("mbs_retry_at"),
        }
        if skip_gazette and skip_mbs:
            soonest = min(gazette_until, mbs_until)
            last_cursor.update(
                {
                    "complete": False,
                    "processed": 0,
                    "ready": 0,
                    "pending": 0,
                    "reconciled": False,
                    "window_complete": False,
                }
            )
            self.last_cursor = last_cursor
            yield "failed", {
                "external_id": None,
                "reason": f"doğrulama kaynakları soğumada until={soonest.isoformat()}",
                "requests_made": 0,
            }
            return
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
            skip_gazette=skip_gazette,
            skip_mbs=skip_mbs,
        ):
            if should_stop():
                break
            if item.get("cooldown"):
                cooling = True
                until = (
                    datetime.now(UTC)
                    + timedelta(minutes=settings.rate_limit_retry_minutes)
                ).isoformat()
                if item["cooldown"] == "gazette":
                    last_cursor["gazette_retry_at"] = until
                else:
                    last_cursor["mbs_retry_at"] = until
                yield "failed", {
                    "external_id": f"mevzuat:{item.get('law_no')}:verify",
                    "law_no": item.get("law_no"),
                    "reason": str(item.get("reason") or "doğrulama kaynağı soğumada"),
                    "requests_made": int(item.get("requests_made") or 0),
                }
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
        last_cursor.update(
            {
                "complete": False if cooling else processed < limit,
                "processed": processed,
                "ready": ready,
                "pending": pending,
                "reconciled": False if cooling else processed < limit,
                "window_complete": False if cooling else processed < limit,
            }
        )
        self.last_cursor = last_cursor
