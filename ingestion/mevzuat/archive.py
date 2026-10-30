"""Çekilen mevzuat maddelerinin diskteki JSON arşivi."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

from ingestion.mevzuat.models import LegislationRecord

_INDEX_FILE_NAME = "index.json"


class LegislationArchive:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / _INDEX_FILE_NAME
        self._external_ids = self._load_index()

    def _load_index(self) -> set[str]:
        if not self._index_path.exists():
            return set()
        payload = json.loads(self._index_path.read_text(encoding="utf-8"))
        return set(payload.get("external_ids", []))

    def _write_index(self) -> None:
        payload = {
            "total": len(self._external_ids),
            "external_ids": sorted(self._external_ids),
        }
        self._index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _file_name(external_id: str) -> str:
        return f"{re.sub(r'[^A-Za-z0-9._-]+', '__', external_id)}.json"

    def contains(self, external_id: str) -> bool:
        return external_id in self._external_ids

    def contains_portal_article(self, external_id: str, portal_article_id: str) -> bool:
        """A numeric alias cannot hide a different lettered portal node."""
        if not self.contains(external_id):
            return False
        path = self.root / self._file_name(external_id)
        if not path.exists():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        from ingestion.mevzuat.identity import primary_article, canonical_article
        heading = primary_article(payload.get("raw_text") or "")
        return (str((payload.get("metadata") or {}).get("madde_id")) == portal_article_id
                and (not heading or heading == canonical_article(payload["article_no"])))

    def __contains__(self, external_id: str) -> bool:
        return external_id in self._external_ids

    def __len__(self) -> int:
        return len(self._external_ids)

    def save(self, record: LegislationRecord) -> bool:
        path = self.root / self._file_name(record.external_id)
        if record.external_id in self._external_ids and path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
            if current.get("content_hash") == record.content_hash:
                return False
        path.write_text(
            json.dumps(record.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if record.external_id not in self._external_ids:
            self._external_ids.add(record.external_id)
            self._write_index()
        return True

    def iter_records(self) -> Iterator[LegislationRecord]:
        for path in sorted(self.root.glob("*.json")):
            if path.name == _INDEX_FILE_NAME:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            yield LegislationRecord.from_json(payload)
