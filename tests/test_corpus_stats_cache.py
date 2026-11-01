"""İstatistik ucu: kalıcı önbellek (yeniden başlatma sonrası 503'e düşmemeli) ve aramadaki doğrulama etiketi."""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from datetime import date
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException

from api import legal
from api.schemas import ChunkEmbeddingBreakdown, CorpusStats


def _stats(count: int = 11_000_000) -> CorpusStats:
    return CorpusStats(
        source_count=count,
        chunk_count=28_000_000,
        decision_count=count,
        legislation_count=31_600,
        latest_decision_date=date(2026, 9, 30),
        embeddings=ChunkEmbeddingBreakdown(ready=2_400_000, pending=1),
    )


@pytest.fixture
def background(monkeypatch, tmp_path):
    """Üretim davranışı: sayım istek yolunda değil, dosya + arka plan yenileme."""
    monkeypatch.setattr(legal, "_stats_in_background", lambda: True)
    monkeypatch.setattr(legal, "_STATS_FILE", tmp_path / "corpus_stats.json")
    monkeypatch.setattr(legal, "_stats_cache", None)
    monkeypatch.setattr(legal, "_stats_refreshing", False)
    refreshes = []
    monkeypatch.setattr(legal, "_refresh_stats_in_background", lambda: refreshes.append(time.monotonic()))

    def no_inline_count(*args, **kwargs):
        raise AssertionError("istek yolunda ağır sayım çalışmamalı")

    monkeypatch.setattr(legal, "_load_corpus_stats", no_inline_count)
    return refreshes


def test_a_restarted_api_serves_the_stats_saved_on_disk(background):
    legal._write_stats_file(_stats())
    stats = legal._corpus_stats_cached()  # önbellek boş (yeni süreç): dosyadan gelir, sayım yok
    assert stats.source_count == 11_000_000 and stats.legislation_count == 31_600
    assert str(stats.latest_decision_date) == "2026-09-30"
    assert background == []  # dosya taze: arka plan yenilemesi de gerekmedi


def test_a_stale_file_is_served_and_refreshed_in_the_background(background, monkeypatch):
    legal._write_stats_file(_stats())
    path = legal._STATS_FILE
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["saved_at"] = time.time() - legal._STATS_REFRESH_SECONDS - 60
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert legal._corpus_stats_cached().source_count == 11_000_000  # eski değer hemen sunulur
    assert len(background) == 1  # yenileme tetiklendi


def test_without_any_saved_stats_the_endpoint_says_preparing_and_starts_the_count(background):
    with pytest.raises(HTTPException) as error:
        legal._corpus_stats_cached()
    assert error.value.status_code == 503
    assert "hazırlanıyor" in error.value.detail and error.value.headers == {"Retry-After": "60"}
    assert len(background) == 1


def test_a_corrupt_stats_file_is_ignored(background):
    legal._STATS_FILE.write_text("{bozuk", encoding="utf-8")
    assert legal._read_stats_file() is None
    legal._STATS_FILE.write_text(json.dumps({"saved_at": 1, "stats": {"source_count": "x"}}), encoding="utf-8")
    assert legal._read_stats_file() is None


def _wait_for_refresh():
    for thread in threading.enumerate():
        if thread.name == "corpus-stats":
            thread.join(timeout=10)


def test_the_background_refresh_updates_memory_and_disk_and_survives_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(legal, "_STATS_FILE", tmp_path / "corpus_stats.json")
    monkeypatch.setattr(legal, "_stats_cache", None)
    monkeypatch.setattr(legal, "_stats_refreshing", False)
    seen_timeouts = []

    def load(timeout="8s"):
        seen_timeouts.append(timeout)
        return _stats(12_345_678)

    monkeypatch.setattr(legal, "_load_corpus_stats", load)
    legal._refresh_stats_in_background()
    _wait_for_refresh()
    assert seen_timeouts == [legal._STATS_REFRESH_TIMEOUT]  # arka planda uzun süre, istek yolundaki 8 sn değil
    assert legal._stats_cache[1].source_count == 12_345_678
    assert legal._read_stats_file()[1].source_count == 12_345_678

    def failing(timeout="8s"):
        raise psycopg.errors.QueryCanceled("zaman aşımı")

    monkeypatch.setattr(legal, "_load_corpus_stats", failing)
    legal._refresh_stats_in_background()
    _wait_for_refresh()
    assert legal._stats_cache[1].source_count == 12_345_678  # başarısız yenileme eski değeri bozmaz
    assert legal._stats_refreshing is False  # bir sonraki yenileme tetiklenebilir


def test_warming_at_startup_loads_the_file_or_starts_the_count(monkeypatch, tmp_path):
    monkeypatch.setattr(legal, "_stats_in_background", lambda: True)
    monkeypatch.setattr(legal, "_STATS_FILE", tmp_path / "corpus_stats.json")
    monkeypatch.setattr(legal, "_stats_cache", None)
    monkeypatch.setattr(legal, "_slow_counts_snapshot", lambda: {})
    started = []
    monkeypatch.setattr(legal, "_refresh_stats_in_background", lambda: started.append(1))
    legal.warm_slow_counts()
    assert started == [1]  # dosya yok: hesap başlar
    legal._write_stats_file(_stats())
    started.clear()
    legal.warm_slow_counts()
    assert started == [] and legal._stats_cache[1].source_count == 11_000_000  # dosya taze: yalnız belleğe alınır


def _connection_returning(rows=None, error=None):
    class Result:
        def fetchall(self):
            return rows

    class Connection:
        def execute(self, sql, params=None):
            if error is not None:
                raise error
            return Result()

    @contextmanager
    def connection():
        yield Connection()

    return connection


def test_search_hits_are_labelled_official_or_third_party(monkeypatch):
    official, third, missing = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(
        legal,
        "database_connection",
        _connection_returning([{"id": official, "third_party": False}, {"id": third, "third_party": True}]),
    )
    labels = legal._verification_labels([official, third, missing])
    assert labels == {official: "official", third: "third_party"}
    assert labels.get(missing, "unknown") == "unknown"  # durumu okunamayan resmî sayılmaz
    assert legal._verification_labels([]) == {}


def test_a_failed_label_lookup_is_an_error_not_a_silent_official(monkeypatch):
    monkeypatch.setattr(legal, "database_connection", _connection_returning(error=psycopg.OperationalError("down")))
    with pytest.raises(HTTPException) as error:
        legal._verification_labels([uuid4()])
    assert error.value.status_code == 503
