from ingestion.bulk_chunk import chunk_rows_for_source
from api.legal import _CURRENT_SEARCH_SQL, _VERIFIED_SOURCE_FILTER
from api.ai.retrieval import LEXICAL_RETRIEVAL_SQL, _VERIFIED_SOURCE_FILTER as RAG_FILTER


def test_chunk_rows_skip_empty_text():
    assert chunk_rows_for_source("src", "  \n\n  ", "yargitay:1") == []


def test_chunk_rows_use_bulk_seed_metadata():
    rows = chunk_rows_for_source("src", "Kısa karar metni.", "yargitay:9")
    assert len(rows) == 1
    assert rows[0][0] == "src"
    assert rows[0][1] == 0
    assert "Kısa karar" in rows[0][2]
    metadata = rows[0][6].obj
    assert metadata["source"] == "bulk_seed"
    assert metadata["external_id"] == "yargitay:9"


def test_search_and_rag_use_only_verified_records():
    """Doğrulanmamış toplu kayıt ve doğrulanmamış mevzuat aranmaz (kullanıcı kararı 2026-10-18)."""
    assert _VERIFIED_SOURCE_FILTER in _CURRENT_SEARCH_SQL  # arama aynı süzgeci uygular (sıralama sütunu ayrıca bakar)
    for fragment in (_VERIFIED_SOURCE_FILTER, RAG_FILTER):
        assert "ls.ingest_status = 'ready'" in fragment
        assert "ingest_status = 'pending'" not in fragment and "ingestion_method = 'bulk_seed'" not in fragment
        assert "verified_against_gazette" in fragment
        assert "verified_against_mbs" in fragment
    assert "legal_rag_current_lexical_hits" in LEXICAL_RETRIEVAL_SQL
