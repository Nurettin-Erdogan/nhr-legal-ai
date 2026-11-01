"""Panel sayaçları (migration 059): sayılar tabloyu taramadan sayaçlardan gelir ve önbellekteki alanların üstüne yazılır."""
from __future__ import annotations

import json
from datetime import date

import pytest

from api import legal
from api.schemas import ChunkEmbeddingBreakdown, CorpusStats


def _cached() -> CorpusStats:
    return CorpusStats(
        source_count=4_471_507,
        chunk_count=30_000_000,
        decision_count=4_471_507,
        legislation_count=86_378,
        other_count=93_389,
        latest_decision_date=date(2026, 10, 19),
        embeddings=ChunkEmbeddingBreakdown(ready=5_000_000, pending=2_000_000),
    )


COUNTS = {
    "src|court_decision|Yargıtay": 4_223_006,
    "src|court_decision|Danıştay": 285_106,
    "src|court_decision|Anayasa Mahkemesi": 16_021,
    "src|court_decision|İstanbul BAM 1. HD": 300,
    "src|court_decision|": 5,  # authority boş: istinaf/emsal grubuna girer
    "src|other|Kamu Denetçiliği Kurumu": 16_077,
    "src|other|Sayıştay": 51_772,
    "src|other|Uyuşmazlık Mahkemesi": 15_083,
    "src|legislation|Mevzuat": 86_415,
    "chunks|embedded": 5_100_000,
}


def test_counters_override_the_count_fields_and_keep_the_rest(monkeypatch, tmp_path):
    monkeypatch.setattr(legal, "_PENDING_BASE_FILE", tmp_path / "missing.json")
    stats = legal._apply_counters(_cached(), COUNTS)
    assert stats.court_decisions.yargitay == 4_223_006
    assert stats.court_decisions.danistay == 285_106
    assert stats.court_decisions.anayasa_mahkemesi == 16_021
    assert stats.court_decisions.istinaf_emsal == 305  # ana üç mahkeme dışındakiler
    assert stats.decision_count == 4_223_006 + 285_106 + 16_021 + 305
    assert stats.administrative.kamu_denetciligi_kurumu == 16_077
    assert stats.administrative.sayistay == 51_772
    assert stats.administrative.uyusmazlik_mahkemesi == 15_083
    assert stats.other_count == 16_077 + 51_772 + 15_083
    assert stats.legislation_count == 86_415
    assert stats.source_count == stats.decision_count + stats.other_count + stats.legislation_count
    assert stats.latest_decision_date == date(2026, 10, 19)  # sayaçla tutulmayan alan korunur


def test_pending_embeddings_shrink_by_what_was_embedded_since_the_last_slow_count(monkeypatch, tmp_path):
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"pending": 2_000_000, "embedded": 5_000_000}), encoding="utf-8")
    monkeypatch.setattr(legal, "_PENDING_BASE_FILE", base)
    stats = legal._apply_counters(_cached(), COUNTS)  # 5.1M hazır: tabandan 100 bin fazla
    assert stats.embeddings.ready == 5_100_000
    assert stats.embeddings.pending == 1_900_000


def test_pending_never_goes_negative(monkeypatch, tmp_path):
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"pending": 10, "embedded": 0}), encoding="utf-8")
    monkeypatch.setattr(legal, "_PENDING_BASE_FILE", base)
    assert legal._apply_counters(_cached(), COUNTS).embeddings.pending == 0


def test_without_a_slow_count_base_the_cached_pending_is_kept(monkeypatch, tmp_path):
    monkeypatch.setattr(legal, "_PENDING_BASE_FILE", tmp_path / "missing.json")
    assert legal._apply_counters(_cached(), COUNTS).embeddings.pending == 2_000_000


def test_stats_endpoint_uses_counters_when_present(monkeypatch, tmp_path):
    monkeypatch.setattr(legal, "_PENDING_BASE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(legal, "_corpus_stats_cached", _cached)
    monkeypatch.setattr(legal, "_live_counters", lambda: COUNTS)
    monkeypatch.setattr(legal, "_live_chunk_estimate", lambda: 31_000_000)
    stats = legal.corpus_stats()
    assert stats.court_decisions.yargitay == 4_223_006
    assert stats.embeddings.ready == 5_100_000
    assert stats.chunk_count == 31_000_000


def test_stats_endpoint_falls_back_to_the_cached_numbers_without_counters(monkeypatch):
    monkeypatch.setattr(legal, "_corpus_stats_cached", _cached)
    monkeypatch.setattr(legal, "_live_counters", lambda: None)
    monkeypatch.setattr(legal, "_live_chunk_estimate", lambda: None)
    assert legal.corpus_stats().decision_count == 4_471_507


def test_counters_are_skipped_under_pytest():
    # Testler gerçek veritabanına sayaç sorgusu atmamalı.
    assert legal._live_counters() is None


@pytest.mark.parametrize("seconds", [legal._STATS_REFRESH_SECONDS, legal._SLOW_COUNTS_TTL_SECONDS])
def test_heavy_recounts_are_rare(seconds):
    # Ağır sayımlar yalnız tamamlayıcı alanlar içindir; her 10 dakikada bir diski doldurmamalı.
    assert seconds >= 3600
