from pathlib import Path

from api import embed_pause


def test_stale_pause_file_is_ignored(tmp_path: Path, monkeypatch):
    pause = tmp_path / "PAUSE_EMBED"
    pause.write_text("assistant", encoding="utf-8")
    monkeypatch.setattr(embed_pause, "PAUSE_FILE", pause)
    monkeypatch.setattr(embed_pause, "_STALE_SECONDS", 0.0)
    assert embed_pause.embeddings_paused() is False
    assert not pause.exists()


def test_fresh_pause_file_blocks(tmp_path: Path, monkeypatch):
    pause = tmp_path / "PAUSE_EMBED"
    pause.write_text("assistant", encoding="utf-8")
    monkeypatch.setattr(embed_pause, "PAUSE_FILE", pause)
    assert embed_pause.embeddings_paused() is True
