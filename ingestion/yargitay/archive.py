"""Çekilen kararların diskteki JSON arşivi.

Arşiv, veritabanına aktarımdan bağımsızdır; portal yeniden taranmadan
aktarım tekrar çalıştırılabilir.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

from ingestion.yargitay.models import CourtDecision

_INDEX_FILE_NAME = "index.json"


class DecisionArchive:
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
        # ':' is not a valid Windows file-name character. The DB identifier is
        # kept intact inside JSON; only its on-disk representation is sanitized.
        return f"{re.sub(r'[^A-Za-z0-9._-]+', '__', external_id)}.json"

    def contains(self, external_id: str) -> bool:
        return external_id in self._external_ids

    def __contains__(self, external_id: str) -> bool:
        return external_id in self._external_ids

    def __len__(self) -> int:
        return len(self._external_ids)

    def save(self, decision: CourtDecision) -> bool:
        """Yeni veya değişmiş kararı yazar; aynı içerikteyse `False` döner."""
        path = self.root / self._file_name(decision.external_id)
        if decision.external_id in self._external_ids:
            if path.exists():
                current = json.loads(path.read_text(encoding="utf-8"))
                if current.get("content_hash") == decision.content_hash:
                    return False

        path.write_text(
            json.dumps(decision.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if decision.external_id not in self._external_ids:
            self._external_ids.add(decision.external_id)
            self._write_index()
        return True

    def iter_decisions(self) -> Iterator[CourtDecision]:
        for path in sorted(self.root.glob("*.json")):
            if path.name == _INDEX_FILE_NAME:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            yield CourtDecision.from_json(payload)
