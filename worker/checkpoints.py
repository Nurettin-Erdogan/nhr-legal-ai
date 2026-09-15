from __future__ import annotations

from worker.models import Checkpoint
from worker.repository import SyncRepository


class CheckpointStore:
    def __init__(self, repository: SyncRepository) -> None:
        self.repository = repository

    def load(self, source_name: str) -> Checkpoint:
        return self.repository.get_checkpoint(source_name)

    def save(self, checkpoint: Checkpoint) -> None:
        self.repository.save_checkpoint(checkpoint)
