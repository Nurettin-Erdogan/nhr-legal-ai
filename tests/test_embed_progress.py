from datetime import date
import time

from api import legal
from api.legal import _with_live_chunks
from api.schemas import ChunkEmbeddingBreakdown, CorpusStats


def _stats(*, ready: int = 10, pending: int = 90, chunk_count: int = 100) -> CorpusStats:
    return CorpusStats(
        source_count=1,
        chunk_count=chunk_count,
        decision_count=0,
        legislation_count=0,
        latest_decision_date=date(2026, 1, 1),
        embeddings=ChunkEmbeddingBreakdown(ready=ready, pending=pending),
    )


def test_embed_progress_overlay_updates_ready_without_waiting_for_count(monkeypatch):
    monkeypatch.setattr(legal, "_live_chunk_estimate", lambda: 21_566_584)
    monkeypatch.setattr(legal, "_read_embed_progress_ready", lambda: 33_674)
    out = _with_live_chunks(_stats(ready=22_922, pending=21_543_662, chunk_count=6_800_000))
    assert out.embeddings.ready == 33_674
    assert out.chunk_count == 21_566_584
    assert out.embeddings.pending == 21_566_584 - 33_674


def test_slow_count_refresh_uses_progress_instead_of_full_chunk_scan(monkeypatch):
    monkeypatch.setattr(legal, "_live_chunk_estimate", lambda: 28_000_000)
    monkeypatch.setattr(legal, "_live_embedded_count", lambda: 4_750_000)
    monkeypatch.setattr(legal, "_seed_count_at", time.monotonic())
    monkeypatch.setattr(legal, "_official_pending_at", time.monotonic())

    def unexpected_database_connection():
        raise AssertionError("chunk counters must not open a database connection")

    monkeypatch.setattr(legal, "database_connection", unexpected_database_connection)

    counts = legal._load_slow_counts({"seed_count": 10_000_000, "official_pending": 23_250_000})

    assert counts["chunk_count"] == 28_000_000
    assert counts["chunk_embedded_count"] == 4_750_000
    assert counts["chunk_embedding_pending_count"] == 23_250_000
