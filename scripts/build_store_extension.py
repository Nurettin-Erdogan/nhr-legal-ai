"""Chrome Web Mağazası için eklenti paketi üretir (geliştirme paketinden farkları aşağıda).

    .\\.venv\\Scripts\\python.exe scripts\\build_store_extension.py ^
        --web-origin https://app.ornek.com ^
        --api-url https://api.ornek.com/api/public/v1/documents/upload

Geliştirme paketinden farklar:
- `localhost` adresleri üretim adresleriyle değişir (JurisAI sayfası = `--web-origin`, yükleme API'si = `--api-url`).
- Kendi kendine güncelleme kapanır (`BUILD.store = true`) ve `alarms` izni kalkar: mağaza kurulumunu Chrome günceller.
- Pakette `localhost` geçen hiçbir metin kalmaz (kalırsa üretim iptal edilir).

Çıktı: dist/jurisai-avukat-store-<sürüm>.zip (git'e girmez).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "web" / "public" / "jurisai-avukat"
DEV_API_URL = "http://localhost:8766/api/public/v1/documents/upload"
TEXT_SUFFIXES = {".js", ".json", ".css", ".html", ".md"}
BUILD_BLOCK = re.compile(r"/\* BUILD-CONFIG-BEGIN.*?\*/\nconst BUILD = \{.*?\n\};\n/\* BUILD-CONFIG-END \*/", re.S)
WEB_ORIGIN = re.compile(r"https://[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:\d{2,5})?")


def _validate(web_origin: str, api_url: str) -> str:
    if not WEB_ORIGIN.fullmatch(web_origin) or "localhost" in web_origin:
        raise SystemExit("--web-origin yalnız 'https://alan.adi' biçiminde olmalı (yol, joker ya da localhost olmaz).")
    parts = urlsplit(api_url)
    if parts.scheme != "https" or not parts.netloc or "localhost" in parts.netloc or parts.path != "/api/public/v1/documents/upload":
        raise SystemExit("--api-url 'https://alan.adi/api/public/v1/documents/upload' biçiminde olmalı.")
    return f"https://{parts.netloc}"


def build(web_origin: str, api_url: str, out_dir: Path) -> Path:
    api_origin = _validate(web_origin, api_url)
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    manifest["permissions"] = [permission for permission in manifest["permissions"] if permission != "alarms"]
    manifest["host_permissions"] = [
        host for host in manifest["host_permissions"] if "localhost" not in host
    ] + [f"{api_origin}/*"]
    for script in manifest["content_scripts"]:
        if script["js"] == ["bridge.js"]:
            script["matches"] = [f"{web_origin}/*"]
    if len(manifest["description"]) > 132:
        raise SystemExit("Manifest açıklaması 132 karakteri aşıyor: mağaza reddeder.")

    store_config = (
        "/* BUILD-CONFIG-BEGIN: mağaza paketi: üretim değerleri */\n"
        "const BUILD = {\n"
        "  store: true,\n"
        f"  apiUrl: {json.dumps(api_url)},\n"
        f"  webOrigins: [{json.dumps(web_origin)}],\n"
        '  updateManifestUrl: "",\n'
        "};\n"
        "/* BUILD-CONFIG-END */"
    )

    files: dict[str, bytes] = {}
    for path in sorted(p for p in SOURCE.rglob("*") if p.is_file()):
        name = path.relative_to(SOURCE).as_posix()
        data = path.read_bytes()
        if path.suffix in TEXT_SUFFIXES:
            data = data.replace(b"\r\n", b"\n")
        if name == "manifest.json":
            data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        elif name == "background.js":
            text, count = BUILD_BLOCK.subn(lambda _match: store_config, data.decode("utf-8"))
            if count != 1:
                raise SystemExit("background.js içinde BUILD-CONFIG bloğu bulunamadı.")
            data = text.encode("utf-8")
        elif name == "popup.js":
            text = data.decode("utf-8")
            if DEV_API_URL not in text:
                raise SystemExit("popup.js içinde varsayılan API adresi bulunamadı.")
            data = text.replace(DEV_API_URL, api_url).encode("utf-8")
        files[name] = data

    leftovers = [name for name, data in files.items() if path_is_text(name) and b"localhost" in data]
    if leftovers:
        raise SystemExit(f"Pakette 'localhost' kalmış: {', '.join(leftovers)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"jurisai-avukat-store-{manifest['version']}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), data, zipfile.ZIP_DEFLATED)
    return target


def path_is_text(name: str) -> bool:
    return Path(name).suffix in TEXT_SUFFIXES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--web-origin", required=True, help="JurisAI web uygulamasının adresi, ör. https://app.ornek.com")
    parser.add_argument("--api-url", required=True, help="Yükleme API adresi, .../api/public/v1/documents/upload")
    parser.add_argument("--out", default=str(ROOT / "dist"), help="Çıktı klasörü (varsayılan: dist/)")
    args = parser.parse_args(argv)
    target = build(args.web_origin, args.api_url, Path(args.out))
    print(f"{target.name} hazır: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
