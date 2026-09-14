import pytest

from ingestion.yargitay.chunking import chunk_text


def test_short_text_produces_single_chunk():
    chunks = chunk_text("Tek paragraflık kısa karar metni.")

    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].paragraph_start == 0
    assert chunks[0].paragraph_end == 0


def test_empty_text_produces_no_chunks():
    assert chunk_text("   \n\n  ") == []


def test_paragraphs_are_grouped_up_to_limit():
    text = "\n\n".join(f"{index} numaralı paragraf." for index in range(10))

    chunks = chunk_text(text, max_chars=60)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 60 for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_oversized_paragraph_is_split():
    text = "kelime " * 500

    chunks = chunk_text(text, max_chars=200)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 200 for chunk in chunks)
    assert all(chunk.paragraph_start == 0 for chunk in chunks)


def test_paragraph_ranges_are_ordered_and_non_negative():
    text = "\n\n".join(f"Paragraf {index}" for index in range(6))

    chunks = chunk_text(text, max_chars=30)

    for chunk in chunks:
        assert 0 <= chunk.paragraph_start <= chunk.paragraph_end


def test_chunking_is_deterministic():
    text = "\n\n".join(f"Paragraf {index}" for index in range(20))

    assert chunk_text(text, max_chars=80) == chunk_text(text, max_chars=80)


def test_invalid_max_chars_is_rejected():
    with pytest.raises(ValueError):
        chunk_text("metin", max_chars=0)
