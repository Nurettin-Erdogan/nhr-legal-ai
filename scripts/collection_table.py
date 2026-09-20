"""Dış veri çekme ilerleme tablosu: 7 kaynak, son turdan bu yana artış ve kalan.

  python scripts/collection_table.py [--interval 300]   # sürekli; her turda bir tablo yazar
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# 2026-09-20 18:33 (doğrulayıcılar durdurulduğunda) resmî sayılar; bundan sonraki artış = yeni çekilen.
BASE = {"yargitay": 9489, "danistay": 10027}
# Kapsam raporunun (portal toplamı - bizde) sonucu: çekilmesi gereken eksik karar sayısı.
MISSING0 = {"yargitay": 9_984_824 - 9_814_158, "danistay": 412_162 - 383_016}
PORTAL = {"kdk": 16_065, "aym": 15_794}
MEVZUAT_PORTAL_DOCS = 917 + 63 + 56 + 110 + 172 + 186 + 5011 + 4361 + 29
STATE = ROOT / "data" / "campaign" / "table-prev.json"


def stats() -> dict:
    with urllib.request.urlopen("http://127.0.0.1:8766/api/legal/stats", timeout=15) as r:
        return json.load(r)


def mevzuat_docs() -> int:
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"]) as c:
        c.execute("SET default_transaction_read_only=on")
        c.execute("SET statement_timeout='30s'")
        return c.execute(
            "SELECT count(DISTINCT metadata->>'mevzuat_id') FROM legal_sources WHERE source_type='legislation'"
        ).fetchone()[0]


def fmt(n: int | None) -> str:
    return "-" if n is None else f"{n:,}".replace(",", ".")


def delta(now: int, prev: int | None) -> str:
    return "-" if prev is None else f"{now - prev:+,}".replace(",", ".")


def render() -> str:
    s = stats()
    cd = s["court_decisions"]
    leg = s["legislation_verification"]
    now = {
        "yargitay": cd["yargitay"],
        "danistay": cd["danistay"],
        "aym": cd["anayasa_mahkemesi"],
        "kdk": s["administrative"]["kamu_denetciligi_kurumu"],
        "bedesten": leg["bedesten"],
        "mevzuat_docs": mevzuat_docs(),
        "rg_dogr": leg["both_verified"] + leg["gazette_only"],
        "mbs_dogr": leg["both_verified"] + leg["mbs_only"],
    }
    prev = json.loads(STATE.read_text()) if STATE.exists() else {}
    STATE.write_text(json.dumps(now))
    p = lambda k: prev.get(k)  # noqa: E731
    y_new = now["yargitay"] - BASE["yargitay"]
    d_new = now["danistay"] - BASE["danistay"]
    rows = [
        ("Yargıtay", f"+{fmt(y_new)} yeni", delta(now["yargitay"], p("yargitay")), f"~{fmt(max(MISSING0['yargitay'] - y_new, 0))} karar eksik"),
        ("Danıştay", f"+{fmt(d_new)} yeni", delta(now["danistay"], p("danistay")), f"~{fmt(max(MISSING0['danistay'] - d_new, 0))} karar eksik"),
        ("AYM", fmt(now["aym"]), delta(now["aym"], p("aym")), f"tamam (portal {fmt(PORTAL['aym'])})"),
        ("KDK", fmt(now["kdk"]), delta(now["kdk"], p("kdk")), f"{fmt(PORTAL['kdk'] - now['kdk'])} portalda dosyasız"),
        ("Bedesten", f"{fmt(now['mevzuat_docs'])} belge / {fmt(now['bedesten'])} madde", delta(now["bedesten"], p("bedesten")) + " madde", f"~{fmt(MEVZUAT_PORTAL_DOCS - now['mevzuat_docs'])} belge eksik"),
        ("Resmî Gazete", f"{fmt(now['rg_dogr'])} madde doğrulandı", delta(now["rg_dogr"], p("rg_dogr")), "doğrulama (çekme sonrası açılacak)"),
        ("MBS", f"{fmt(now['mbs_dogr'])} madde doğrulandı", delta(now["mbs_dogr"], p("mbs_dogr")), "doğrulama (çekme sonrası açılacak)"),
    ]
    out = [f"TABLO {time.strftime('%H:%M')} (önceki tabloya göre artış)", "| Kaynak | Şu an | Son tablo | Kalan |", "| --- | --- | --- | --- |"]
    out += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in rows]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()
    while True:
        try:
            print(render(), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"TABLO HATA: {type(exc).__name__} {str(exc)[:80]}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
