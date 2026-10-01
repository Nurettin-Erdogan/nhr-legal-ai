"""Asistan cevap üretirken embedding işçisini GPU'dan indirir.

RTX 3050 6GB hem nomic hem deepseek-r1:8b tutamaz; ikisi aynı anda Ollama'ya
gidince asistan zaman aşımına düşer.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

PAUSE_FILE = Path(__file__).resolve().parents[1] / "data" / "campaign" / "PAUSE_EMBED"
_STALE_SECONDS = 600.0


def embeddings_paused() -> bool:
    if not PAUSE_FILE.exists():
        return False
    try:
        age = time.time() - PAUSE_FILE.stat().st_mtime
    except OSError:
        return False
    if age > _STALE_SECONDS:
        resume_embeddings()
        return False
    return True


def pause_embeddings(reason: str = "assistant") -> None:
    if "pytest" in sys.modules:
        return
    try:
        PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PAUSE_FILE.write_text(reason, encoding="utf-8")
    except OSError:
        logger.warning("Embedding duraklatma dosyası yazılamadı", exc_info=True)


def resume_embeddings() -> None:
    try:
        PAUSE_FILE.unlink(missing_ok=True)
    except OSError:
        logger.warning("Embedding duraklatma dosyası silinemedi", exc_info=True)


def wait_if_embeddings_paused(*, sleeper=time.sleep, interval: float = 0.4) -> None:
    while embeddings_paused():
        sleeper(interval)


def unload_ollama_model(base_url: str, model: str, timeout_seconds: float = 15.0) -> None:
    """VRAM'i boşaltmak için modeli hemen bellekten çıkarır."""
    if "pytest" in sys.modules:
        return
    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_seconds, trust_env=False) as client:
            client.post("/api/generate", json={"model": model, "keep_alive": 0})
    except httpx.HTTPError:
        logger.info("Ollama modeli boşaltılamadı: %s", model)
