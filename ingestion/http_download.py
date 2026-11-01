"""Resumable HTTP indirme; Range destekler."""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "nhr-legal-ai-eval/0.1 (bulk-seed; no embed)"


def download_http(url: str, dest: Path, *, label: str | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.stat().st_size if dest.exists() else 0
    name = label or dest.name
    if existing:
        head = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(head, timeout=30) as response:
                length = int(response.headers.get("Content-Length") or 0)
            if length and existing >= length:
                print(f"skip {name} complete {existing / (1024 * 1024):.1f} MB")
                return dest
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, OSError):
            pass
    headers = {"User-Agent": USER_AGENT}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    request = urllib.request.Request(url, headers=headers)
    name = label or dest.name
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            mode = "ab" if existing and response.status == 206 else "wb"
            if response.status == 200:
                mode = "wb"
            print(f"download {name} status={response.status} resume={existing}")
            with dest.open(mode) as handle:
                written = dest.stat().st_size if mode == "ab" else 0
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    handle.write(chunk)
                    written += len(chunk)
                    if written % (50 * 1024 * 1024) < 256 * 1024:
                        print(f"  {name} {written / (1024 * 1024):.1f} MB")
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and dest.exists() and dest.stat().st_size > 0:
            return dest
        raise
    print(f"saved {dest} {dest.stat().st_size / (1024 * 1024):.1f} MB")
    return dest
