"""Gerçek Chromium: kişiye özel pakette gömülü anahtarı eklenti kendisi saklar; genel pakette anahtar oluşmaz."""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

import pytest

from api import uyap_extension_package as package

pytestmark = pytest.mark.skipif(
    os.getenv("NHR_BROWSER_TESTS") != "1", reason="Tarayıcı testleri için NHR_BROWSER_TESTS=1 gerekir"
)


def _launch(playwright, extension_dir: Path, profile: Path):
    return playwright.chromium.launch_persistent_context(
        str(profile),
        headless=False,
        args=[
            "--headless=new",
            f"--disable-extensions-except={extension_dir}",
            f"--load-extension={extension_dir}",
            "--proxy-server=http://127.0.0.1:9",  # dış ağ yok
            "--proxy-bypass-list=127.0.0.1;localhost",
            "--disable-background-networking",
        ],
    )


def _stored(context, wait: float = 8.0) -> dict:
    worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
    deadline = time.time() + wait
    state: dict = {}
    while time.time() < deadline:
        state = worker.evaluate("() => chrome.storage.local.get(['apiKey', 'bundledKeyApplied'])")
        if state.get("apiKey"):
            break
        time.sleep(0.3)
    return state


def _run(extension_bytes: bytes):
    sync_api = pytest.importorskip("playwright.sync_api")
    workdir = Path(tempfile.mkdtemp(prefix="nhr-bundled-key-"))
    try:
        extension_dir = workdir / "eklenti"
        zipfile.ZipFile(io.BytesIO(extension_bytes)).extractall(extension_dir)
        playwright = sync_api.sync_playwright().start()
        context = None
        try:
            context = _launch(playwright, extension_dir, workdir / "profile")
            return _stored(context)
        finally:
            if context is not None:
                context.close()
            playwright.stop()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_the_personal_package_connects_itself_without_any_key_entry():
    key = package.new_key()
    state = _run(package.personalise(package.PACKAGE.read_bytes(), key))
    assert state.get("apiKey") == key
    assert state.get("bundledKeyApplied") == key


def test_the_general_package_stores_no_key():
    state = _run(package.PACKAGE.read_bytes())
    assert not state.get("apiKey")
