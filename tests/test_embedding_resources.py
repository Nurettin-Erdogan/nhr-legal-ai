from pathlib import Path

import pytest

from api import embed_pause


@pytest.fixture
def pause_flag(tmp_path, monkeypatch):
    path = tmp_path / 'PAUSE_EMBED'
    monkeypatch.setattr(embed_pause, 'PAUSE_FILE', path)
    monkeypatch.setattr(embed_pause, 'pause_embeddings', lambda reason: path.write_text(reason))
    monkeypatch.setattr(embed_pause, 'resume_embeddings', lambda: path.unlink(missing_ok=True))
    return path


def test_nested_local_fallbacks_keep_pause_until_the_last_call_finishes(pause_flag):
    with embed_pause.local_generation_pause():
        assert pause_flag.exists()
        with embed_pause.local_generation_pause():
            assert pause_flag.exists()
        assert pause_flag.exists()
    assert not pause_flag.exists()


def test_fallback_does_not_clear_a_preexisting_operator_pause(pause_flag):
    pause_flag.write_text('operator')
    with embed_pause.local_generation_pause():
        assert pause_flag.read_text() == 'operator'
    assert pause_flag.read_text() == 'operator'


def test_failed_local_generation_releases_only_its_own_pause(pause_flag):
    with pytest.raises(RuntimeError):
        with embed_pause.local_generation_pause():
            raise RuntimeError('failed generation')
    assert not pause_flag.exists()
