from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

HealthState = Literal["healthy", "degraded", "blocked", "failed"]
RunStatus = Literal[
    "queued",
    "running",
    "success",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "captcha_required",
]
RecordOutcome = Literal[
    "created",
    "unchanged",
    "updated",
    "new_version",
    "duplicate",
    "invalid",
    "quarantined",
    "failed",
]


@dataclass(slots=True)
class Checkpoint:
    source_name: str
    last_successful_sync_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_cursor: dict[str, Any] = field(default_factory=dict)
    last_page: int | None = None
    last_date_from: date | None = None
    last_date_to: date | None = None
    last_external_id: str | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    next_run_at: datetime | None = None
    health_state: HealthState = "healthy"
    health_detail: str | None = None
    updated_at: datetime | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "last_successful_sync_at": (
                self.last_successful_sync_at.isoformat() if self.last_successful_sync_at else None
            ),
            "last_page": self.last_page,
            "last_date_from": self.last_date_from.isoformat() if self.last_date_from else None,
            "last_date_to": self.last_date_to.isoformat() if self.last_date_to else None,
            "last_external_id": self.last_external_id,
            "last_cursor": self.last_cursor,
            "consecutive_failures": self.consecutive_failures,
            "health_state": self.health_state,
        }


@dataclass(slots=True)
class RunCounters:
    records_seen: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_unchanged: int = 0
    records_duplicate: int = 0
    records_failed: int = 0
    records_quarantined: int = 0
    requests_made: int = 0
    retry_count: int = 0

    def add(self, outcome: RecordOutcome) -> None:
        self.records_seen += 1
        if outcome == "created":
            self.records_created += 1
        elif outcome in {"updated", "new_version"}:
            self.records_updated += 1
        elif outcome == "unchanged":
            self.records_unchanged += 1
        elif outcome == "duplicate":
            self.records_duplicate += 1
        elif outcome == "quarantined":
            self.records_quarantined += 1
        elif outcome in {"failed", "invalid"}:
            self.records_failed += 1

    def as_json(self) -> dict[str, int]:
        return {
            "records_seen": self.records_seen,
            "records_created": self.records_created,
            "records_updated": self.records_updated,
            "records_unchanged": self.records_unchanged,
            "records_duplicate": self.records_duplicate,
            "records_failed": self.records_failed,
            "records_quarantined": self.records_quarantined,
            "requests_made": self.requests_made,
            "retry_count": self.retry_count,
        }


@dataclass(slots=True)
class SyncRequest:
    source: str
    date_from: date | None = None
    date_to: date | None = None
    dry_run: bool = False
    resume: bool = True
    max_records: int | None = None
    keyword: str = ""
    chamber: str = ""
    law_no: str = ""
    lane: Literal["backfill", "current"] = "backfill"


@dataclass(frozen=True, slots=True)
class AdapterHealth:
    source_name: str
    state: HealthState
    detail: str
    active: bool = True


@dataclass(slots=True)
class IngestionRun:
    id: UUID
    source_name: str
    status: RunStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    counters: RunCounters = field(default_factory=RunCounters)
    last_error: str | None = None
    checkpoint_before: dict[str, Any] = field(default_factory=dict)
    checkpoint_after: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
