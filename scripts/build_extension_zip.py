"""Bir tarayıcı eklentisi klasöründen indirilebilir zip üretir (web/public/<ad>.zip).

web/tests/extension-bundles.test.mjs zip'in kaynakla birebir aynı olmasını ister: metin dosyaları
(js, json, css, html, md) satır sonu LF'e çevrilerek, diğerleri olduğu gibi yazılır.

    .\\.venv\\Scripts\\python.exe scripts\\build_extension_zip.py jurisai-avukat
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1] / "web" / "public"
TEXT_SUFFIXES = {".js", ".json", ".css", ".html", ".md"}


def build(name: str) -> Path:
    source = PUBLIC / name
    if not source.is_dir():
        raise SystemExit(f"Eklenti klasörü yok: {source}")
    target = PUBLIC / f"{name}.zip"
    files = sorted(path for path in source.rglob("*") if path.is_file())
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            data = path.read_bytes()
            if path.suffix in TEXT_SUFFIXES:
                data = data.replace(b"\r\n", b"\n")
            archive.writestr(path.relative_to(source).as_posix(), data)
    print(f"{target.name}: {len(files)} dosya")
    return target


if __name__ == "__main__":
    for extension in sys.argv[1:] or ["jurisai-avukat"]:
        build(extension)
