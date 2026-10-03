"""Chrome Web Mağazası paketi: üretim adresleri, kapalı kendi kendine güncelleme, localhost'suz içerik."""
from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "web" / "public" / "jurisai-avukat"
spec = importlib.util.spec_from_file_location("build_store_extension", ROOT / "scripts" / "build_store_extension.py")
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

WEB = "https://app.ornek.com"
API = "https://api.ornek.com/api/public/v1/documents/upload"


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    target = store.build(WEB, API, tmp_path_factory.mktemp("store"))
    with zipfile.ZipFile(target) as archive:
        return target, {name: archive.read(name) for name in archive.namelist()}


def test_the_package_name_carries_the_manifest_version(package):
    target, files = package
    version = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))["version"]
    assert target.name == f"jurisai-avukat-store-{version}.zip"
    assert json.loads(files["manifest.json"])["version"] == version


def test_manifest_points_to_production_and_drops_the_update_permission(package):
    manifest = json.loads(package[1]["manifest.json"])
    assert "alarms" not in manifest["permissions"]
    assert set(manifest["permissions"]) == {"activeTab", "scripting", "downloads", "storage", "webRequest"}
    assert manifest["host_permissions"] == ["*://*.adalet.gov.tr/*", "*://*.uyap.gov.tr/*", "https://api.ornek.com/*"]
    bridge = [script for script in manifest["content_scripts"] if script["js"] == ["bridge.js"]]
    assert [script["matches"] for script in bridge] == [[f"{WEB}/*"]]
    assert len(manifest["description"]) <= 132  # mağaza sınırı


def test_background_is_a_store_build_with_production_values(package):
    background = package[1]["background.js"].decode("utf-8")
    assert "store: true," in background and "store: false" not in background
    assert f'apiUrl: "{API}"' in background and f'webOrigins: ["{WEB}"]' in background
    assert 'updateManifestUrl: ""' in background
    assert "if (BUILD.store) return;" in background  # güncelleme yoklaması mağaza paketinde çalışmaz
    assert f'apiUrl: "{API}"' in package[1]["popup.js"].decode("utf-8") or API in package[1]["popup.js"].decode("utf-8")


def test_no_text_file_in_the_package_mentions_localhost(package):
    for name, data in package[1].items():
        if Path(name).suffix in store.TEXT_SUFFIXES:
            assert b"localhost" not in data, name


def test_package_has_exactly_the_dev_files(package):
    dev = {path.relative_to(SOURCE).as_posix() for path in SOURCE.rglob("*") if path.is_file()}
    assert set(package[1]) == dev


def test_the_dev_source_stays_a_dev_build():
    background = (SOURCE / "background.js").read_text(encoding="utf-8")
    assert "store: false," in background and "localhost:3000" in background
    assert "alarms" in json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))["permissions"]


@pytest.mark.parametrize(
    ("web", "api"),
    [
        ("http://app.ornek.com", API),  # https olmalı
        ("https://app.ornek.com/yol", API),  # yalnız kaynak
        ("https://*.ornek.com", API),  # joker yok
        ("https://localhost:3000", API),
        (WEB, "http://api.ornek.com/api/public/v1/documents/upload"),
        (WEB, "https://api.ornek.com/baska/yol"),
        (WEB, "https://localhost/api/public/v1/documents/upload"),
    ],
)
def test_unsafe_origins_are_refused(tmp_path, web, api):
    with pytest.raises(SystemExit):
        store.build(web, api, tmp_path)
