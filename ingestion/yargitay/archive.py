"""Çekilen kararların diskteki JSON arşivi.

Arşiv, veritabanına aktarımdan bağımsızdır; portal yeniden taranmadan
aktarım tekrar çalıştırılabilir.
"""

from __future__ import annotations

import json
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
        return f"{external_id.replace('/', '__')}.json"

    def __contains__(self, external_id: str) -> bool:
        return external_id in self._external_ids

    def __len__(self) -> int:
        return len(self._external_ids)

    def save(self, decision: CourtDecision) -> bool:
        """Kararı diske yazar; aynı karar daha önce kaydedilmişse `False` döner."""
        if decision.external_id in self._external_ids:
            return False

        path = self.root / self._file_name(decision.external_id)
        path.write_text(
            json.dumps(decision.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._external_ids.add(decision.external_id)
        self._write_index()
        return True

    def iter_decisions(self) -> Iterator[CourtDecision]:
        for path in sorted(self.root.glob("*.json")):
            if path.name == _INDEX_FILE_NAME:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            yield CourtDecision.from_json(payload)
