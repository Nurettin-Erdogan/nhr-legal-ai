"""altaidevorg/yargitay-karar-data-raw — 10k kalite testi. Import yok."""

from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from ingestion.altai_yargitay import html_content_to_text, prepare_altai_row  # noqa: E402
from ingestion.hf_700k import parse_case_no, parse_date_field  # noqa: E402
from ingestion.http_download import USER_AGENT  # noqa: E402
from ingestion.yargitay.parser import parse_chamber, parse_decision_no, parse_docket_no  # noqa: E402

ROWS_URL = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=altaidevorg/yargitay-karar-data-raw&config=default&split=train"
)
OUT = ROOT / "data" / "eval" / "altai-yargitay"
REPORT = OUT / "quality_10k.json"
TARGET = 10_000


def fetch_page(offset: int, length: int = 100) -> list[dict]:
    url = f"{ROWS_URL}&offset={offset}&length={length}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, 8):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return [item["row"] for item in payload.get("rows") or []]
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 7:
                raise
            wait = min(90, 6 * attempt)
            print(f"HF 429 offset={offset}; sleep {wait}s")
            time.sleep(wait)
    return []


def stream_jsonl(url: str, limit: int) -> list[dict]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    rows: list[dict] = []
    with urllib.request.urlopen(request, timeout=180) as response:
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if len(rows) >= limit:
                break
    return rows


def download_sample() -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / "sample_10k.jsonl"
    if cache.exists() and cache.stat().st_size > 500_000:
        rows = [json.loads(line) for line in cache.read_text(encoding="utf-8").splitlines() if line]
        if len(rows) >= TARGET:
            print(f"reuse {cache} n={len(rows)}")
            return rows[:TARGET]
    collected: list[dict] = []
    for year, want in ((2015, 5000), (2023, 5000)):
        url = (
            "https://huggingface.co/datasets/altaidevorg/yargitay-karar-data-raw"
            f"/resolve/main/yargitay_data_{year}.jsonl"
        )
        print(f"stream {year} n={want}")
        batch = stream_jsonl(url, want)
        print(f"  got {len(batch)}")
        collected.extend(batch)
    cache.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in collected), encoding="utf-8")
    return collected[:TARGET]


def analyze(rows: list[dict]) -> dict:
    n = len(rows)
    empty_html = 0
    empty_text = 0
    html_ok = 0
    esas_ok = 0
    karar_ok = 0
    date_ok = 0
    esas_in_text = 0
    karar_in_text = 0
    date_in_text = 0
    daire_ok = 0
    ids = []
    naturals = []
    prepared_q = Counter()
    for row in rows:
        html = str(row.get("content") or "")
        text = html_content_to_text(html)
        if not html.strip():
            empty_html += 1
        if not text.strip():
            empty_text += 1
        else:
            html_ok += 1
        esas = parse_case_no(row.get("esasNo"))
        karar = parse_case_no(row.get("kararNo"))
        tarih = parse_date_field(row.get("kararTarihi"))
        if esas:
            esas_ok += 1
            if esas in text or esas.replace("/", "/ ") in text or parse_docket_no(text) == esas:
                esas_in_text += 1
        if karar:
            karar_ok += 1
            if karar in text or parse_decision_no(text) == karar:
                karar_in_text += 1
        if tarih:
            date_ok += 1
            if tarih.strftime("%d.%m.%Y") in html or tarih.strftime("%d/%m/%Y") in html:
                date_in_text += 1
        if parse_chamber(str(row.get("daire") or "")):
            daire_ok += 1
        ids.append(str(row.get("id")))
        naturals.append((esas, karar, str(row.get("kararTarihi"))))
        prepared_q[prepare_altai_row(row).quarantine_code or "ok"] += 1
    return {
        "n": n,
        "full_text_html": (n - empty_html) / n,
        "parsed_text_nonempty": html_ok / n,
        "esas_valid": esas_ok / n,
        "karar_valid": karar_ok / n,
        "tarih_valid": date_ok / n,
        "daire_parseable": daire_ok / n,
        "esas_in_parsed_text": esas_in_text / max(1, esas_ok),
        "karar_in_parsed_text": karar_in_text / max(1, karar_ok),
        "tarih_in_html": date_in_text / max(1, date_ok),
        "duplicate_id": (n - len(set(ids))) / n,
        "duplicate_natural": (n - len(set(naturals))) / n,
        "prepare_quarantine": dict(prepared_q),
    }


def db_match(rows: list[dict]) -> dict:
    import psycopg
    from psycopg.rows import dict_row

    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        return {"error": "DATABASE_ADMIN_URL yok"}
    sample = random.Random(3600001).sample(rows, min(100, len(rows)))
    ext = [f"yargitay:{row['id']}" for row in sample if row.get("id")]
    with psycopg.connect(url, row_factory=dict_row) as connection:
        ext_hits = connection.execute(
            """
            SELECT ls.external_id, ls.ingest_status, d.docket_no, d.decision_no, d.decision_date
            FROM legal_sources ls
            JOIN court_decision_details d ON d.legal_source_id = ls.id
            WHERE ls.is_current AND ls.deleted_at IS NULL AND ls.external_id = ANY(%s)
            """,
            (ext,),
        ).fetchall()
        natural_hits = 0
        for row in sample:
            esas = parse_case_no(row.get("esasNo"))
            karar = parse_case_no(row.get("kararNo"))
            if not esas or not karar:
                continue
            found = connection.execute(
                """
                SELECT 1 FROM court_decision_details d
                JOIN legal_sources ls ON ls.id = d.legal_source_id
                WHERE ls.is_current AND ls.deleted_at IS NULL
                  AND lower(d.court_name)='yargıtay'
                  AND d.docket_no = %s AND d.decision_no = %s
                LIMIT 1
                """,
                (esas, karar),
            ).fetchone()
            if found:
                natural_hits += 1
    by_status = Counter(item["ingest_status"] for item in ext_hits)
    return {
        "sample": len(sample),
        "external_id_hits": len(ext_hits),
        "external_id_hit_rate": len(ext_hits) / max(1, len(sample)),
        "hits_by_ingest_status": dict(by_status),
        "natural_key_hits": natural_hits,
        "natural_key_hit_rate": natural_hits / max(1, len(sample)),
        "note": "SELECT only; official ready overwrite yok",
    }


def verdict(analysis: dict) -> dict:
    usable = (
        analysis["parsed_text_nonempty"] > 0.95
        and analysis["esas_valid"] > 0.95
        and analysis["karar_valid"] > 0.95
        and analysis["tarih_valid"] > 0.95
        and analysis["duplicate_id"] < 0.05
    )
    return {
        "usable_as_third_party_seed": usable,
        "usable_as_official_verified": False,
        "html_parser_ok": analysis["parsed_text_nonempty"] > 0.95,
    }


def main() -> None:
    t0 = time.perf_counter()
    rows = download_sample()
    analysis = analyze(rows)
    db = db_match(rows)
    report = {
        "dataset": "altaidevorg/yargitay-karar-data-raw",
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.perf_counter() - t0, 1),
        "sample": analysis,
        "db_match_100": db,
        "verdict": verdict(analysis),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print("wrote", REPORT)


if __name__ == "__main__":
    main()
