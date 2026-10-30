"""Veri çekimi durum tablosu: kalan eksik, hız, tahmini süre (salt okunur).

    python scripts/status_table.py

Yargıtay/Danıştay eksik sayısı = portal anlık görüntüsü - (resmî + doğrulanmamış tohum).
Hız = son 1 saatte eklenen resmî karar; süre tahmini bu hıza göre hesaplanır.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _stats() -> dict:
    with urllib.request.urlopen("http://127.0.0.1:8766/api/legal/stats", timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _free_ram_gb() -> float:
    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong)
            for name in ("total", "avail", "totpage", "availpage", "totvirt", "availvirt", "ext")
        ]

    status = Status()
    status.length = ctypes.sizeof(Status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.avail / 1024**3


def _last_line(path: Path, pattern: str) -> str:
    try:
        lines = [line for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if re.search(pattern, line)]
        return lines[-1] if lines else ""
    except OSError:
        return ""


def _workers() -> list[str]:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' } | "
             "ForEach-Object { $_.CommandLine }"],
            capture_output=True, text=True, timeout=60, encoding="utf-8", errors="ignore",
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    names = []
    for line in out.splitlines():
        for key, label in (
            ("collect_bedesten", "Bedesten çekim"), ("backfill_campaign", "Portal kampanya"),
            ("collect_emsal", "Emsal çekim"), ("verify_seeds", "Seed doğrulama"),
            ("verify_loop", "Mevzuat doğrulama"), ("embed_chunks", "Embedding"),
        ):
            if key in line and label not in names:
                names.append(label)
    return names


def _fmt(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _eta(remaining: int, per_hour: float) -> str:
    if remaining <= 0:
        return "tamam"
    if per_hour < 1:
        return "hesaplanamadı"
    hours = remaining / per_hour
    return f"~{hours / 24:.1f} gün ({hours:.0f} saat)"


def main() -> None:
    stats = _stats()
    court, third = stats["court_decisions"], stats["third_party"]
    snapshot = json.loads((ROOT / "data" / "campaign" / "coverage-portal.json").read_text(encoding="utf-8"))
    portal = {s: sum(v for k, v in snapshot[s].items() if k.isdigit() and isinstance(v, int)) for s in snapshot}

    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], autocommit=True) as connection:
        connection.execute("SET statement_timeout = '120s'")
        rows = connection.execute(
            "SELECT split_part(external_id, ':', 1), count(*) FROM legal_sources "
            "WHERE source_type = 'court_decision' AND ingest_status = 'ready' "
            "AND created_at > now() - interval '1 hour' AND external_id ~ '^(yargitay|danistay|emsal):' GROUP BY 1"
        ).fetchall()
    hourly = {row[0]: int(row[1]) for row in rows}

    yarg_have = court["yargitay"] + third["yargitay"]
    yarg_gap = max(portal["yargitay"] - yarg_have, 0)
    dan_gap = max(portal["danistay"] - (court["danistay"] + third["danistay"]), 0)
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    bedesten = _last_line(ROOT / "data" / "logs" / "sentinel-bedesten-yargitay.out.log", r"yeni=")
    date_now = re.search(r"tarih=(\d{4}-\d{2}-\d{2})", bedesten)
    speed = re.search(r"hız=(\d+)/sa", bedesten)

    print(f"VERİ ÇEKİMİ DURUM TABLOSU — {now}")
    print("| Kaynak | Resmî şimdi | Eksik (portala göre) | Son 1 saat | Tahmini süre |")
    print("| --- | --- | --- | --- | --- |")
    print(f"| Yargıtay | {_fmt(court['yargitay'])} | {_fmt(yarg_gap)} | +{hourly.get('yargitay', 0)} | "
          f"{_eta(yarg_gap, hourly.get('yargitay', 0))} |")
    dan_rate = hourly.get("danistay", 0) or max(hourly.get("yargitay", 0) // 10, 0)
    print(f"| Danıştay | {_fmt(court['danistay'])} | {_fmt(dan_gap)} | +{hourly.get('danistay', 0)} | "
          f"{_eta(dan_gap, dan_rate)} |")
    print(f"| İstinaf/Emsal | {_fmt(court['istinaf_emsal'])} | sürüyor | +{hourly.get('emsal', 0)} | — |")
    legislation = stats["legislation_verification"]
    print(f"| Mevzuat (çift doğrulanmış madde) | {_fmt(legislation['both_verified'])} / {_fmt(legislation['bedesten'])} | "
          f"tebliğ/yönetmelik doğrulanamıyor | — | sürüyor |")
    print(f"| AYM / KDK / Sayıştay / Uyuşmazlık | {_fmt(court['anayasa_mahkemesi'])} / "
          f"{_fmt(stats['administrative']['kamu_denetciligi_kurumu'])} / "
          f"{_fmt(stats['administrative']['sayistay'])} / {_fmt(stats['administrative']['uyusmazlik_mahkemesi'])} | 0 | — | tamam |")
    print()
    print("| Gösterge | Değer |")
    print("| --- | --- |")
    print(f"| Bedesten toplayıcı | tarih={date_now.group(1) if date_now else '?'}, ortalama {speed.group(1) if speed else '?'} karar/saat |")
    print(f"| Doğrulanmamış arşiv (seed) | {_fmt(sum(third.values()))} (sorgu anında doğrulanır) |")
    print(f"| Embedding | hazır {_fmt(stats['embeddings']['ready'])}, bekleyen {_fmt(stats['embeddings']['pending'])} |")
    print(f"| Çalışan işçiler | {', '.join(_workers()) or 'yok'} |")
    print(f"| Boş RAM | {_free_ram_gb():.1f} GB |")


if __name__ == "__main__":
    main()
