"""Canlı API'ye sabit regresyon sorularını sorar ve ölçülebilir kontrolleri raporlar (salt okunur, anonim).

Kontroller kodla yapılır, yargı içermez: cevap kaynağa dayalı mı (`grounded`), atıf var mı, beklenen kanun/madde atıflarda geçiyor mu,
beklenen kaynak türleri geliyor mu, soru terimleri cevapta yer alıyor mu, doğrulanmamış (üçüncü taraf) atıf oranı, süre.
Cevabın hukuken doğru olduğunu ÖLÇMEZ: bu bir avukat değerlendirmesi gerektirir.

    .venv\Scripts\python.exe scripts\eval_live_answers.py --output .local\eval-live.json [--limit 5]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.ai.eval_questions import REGRESSION_QUESTIONS  # noqa: E402


def check(case: dict, body: dict) -> dict:
    citations = body.get("citations", [])
    text = " ".join([body.get("answer", "")] + [c.get("excerpt", "") for c in citations]).lower()
    types = {c.get("source_type") for c in citations}
    law_ok = True
    if case.get("expect_law_no"):
        law_ok = any(c.get("law_no") == case["expect_law_no"] for c in citations)
    article_ok = True
    if case.get("expect_article_no"):
        article_ok = any(c.get("article_no") == case["expect_article_no"] for c in citations)
    return {
        "grounded": bool(body.get("grounded")),
        "has_citations": bool(citations),
        "law_cited": law_ok,
        "article_cited": article_ok,
        "source_types_ok": bool(types & set(case["expect_source_types"])),
        "terms_present": all(term in text for term in case["must_terms"]),
        "third_party_share": (sum(c.get("verification") == "third_party" for c in citations) / len(citations)) if citations else 0.0,
        "unverified_markers": len(body.get("unverified_markers", [])),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8766")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Rapor üzerine yazılmaz")
    cases = list(REGRESSION_QUESTIONS)[: args.limit or None]
    rows = []
    with httpx.Client(timeout=300) as client:
        for case in cases:
            started = time.monotonic()
            try:
                response = client.post(f"{args.api}/api/ai/answer", json={"question": case["question"]})
                seconds = round(time.monotonic() - started, 1)
                if response.status_code != 200:
                    row = {"id": case["id"], "status": response.status_code, "seconds": seconds, "detail": response.text[:160]}
                else:
                    row = {"id": case["id"], "status": 200, "seconds": seconds, **check(case, response.json())}
            except httpx.HTTPError as error:
                row = {"id": case["id"], "status": "hata", "seconds": round(time.monotonic() - started, 1), "detail": str(error)[:160]}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    ok = [row for row in rows if row["status"] == 200]
    flags = ("grounded", "has_citations", "law_cited", "article_cited", "source_types_ok", "terms_present")
    summary = {
        "sorular": len(rows),
        "cevaplanan": len(ok),
        **{flag: f"{sum(bool(row[flag]) for row in ok)}/{len(ok)}" for flag in flags},
        "ucuncu_taraf_atif_orani_ort": round(statistics.mean(row["third_party_share"] for row in ok), 3) if ok else None,
        "sure_sn_medyan": statistics.median(row["seconds"] for row in rows) if rows else None,
        "sure_sn_max": max((row["seconds"] for row in rows), default=None),
    }
    args.output.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ÖZET", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
