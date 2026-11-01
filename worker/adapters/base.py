from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol

from worker.models import AdapterHealth, RecordOutcome, SyncRequest


class SourceAdapter(Protocol):
    source_name: str
    authority: str
    active: bool

    def health_check(self) -> AdapterHealth: ...

    def validate(self, record: Any) -> list[str]: ...

    def dedup_identity(self, record: Any) -> str: ...

    def version_identity(self, record: Any) -> str: ...

    def provenance(self, record: Any) -> dict[str, Any]: ...

    def sync(
        self,
        request: SyncRequest,
        *,
        cursor: dict[str, Any],
        connection: Any,
        dry_run: bool,
        should_stop: Any,
    ) -> Iterator[tuple[RecordOutcome, dict[str, Any]]]: ...
