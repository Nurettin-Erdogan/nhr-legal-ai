"""Synthetic embedding latency benchmark. No generation, user data, or DB writes.

Use the identical Ollama model digests on both sides. Remote services should
be reached via an already authorized SSH tunnel, not a new public Ollama port.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
from time import perf_counter
from urllib.parse import urlsplit

import httpx


QUERIES = (
    "Kiracı kira bedelini ödemediğinde yazılı bildirim ve ödeme süresi.",
    "İşe iade talebinde aynı işkolundaki işyerlerinde çalışanların sayılması.",
    "Banka havalesiyle verilen borç, ödeme belgesi ve ilamsız takibe itiraz.",
    "Miras bırakanın taşınmaz devri hakkında tanık ve banka kayıtlarının değerlendirilmesi.",
    "İş kazasında işverenin gözetme yükümlülüğü ve tazminat talebi.",
    "Evlilik içinde alınan ve konut kredisi ödenen taşınmazın mal rejiminde değerlendirilmesi.",
    "İdari işlemin iptali talebinde başvuru yolu ve görevli mahkeme.",
    "Belirsiz süreli iş sözleşmesinde bildirim süreleri ve kıdemin hesaplanması.",
)
MODELS = (("nomic-embed-text", 768), ("bge-m3", 1024))


def summary(values):
    ordered = sorted(values)
    return {
        "count": len(values),
        "median_ms": round(statistics.median(values), 2),
        "p95_ms": round(ordered[max(0, math.ceil(len(ordered) * .95) - 1)], 2),
        "max_ms": round(max(values), 2),
    }


def embed(client, model, dimensions, text):
    started = perf_counter()
    response = client.post("/api/embed", json={
        "model": model, "input": [text], "dimensions": dimensions,
        "truncate": True, "keep_alive": "5m",
    })
    response.raise_for_status()
    body = response.json()
    elapsed = (perf_counter() - started) * 1000
    vectors = body.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != 1:
        raise ValueError("Invalid vector count")
    vector = vectors[0]
    if len(vector) != dimensions or not all(isinstance(x, (float, int)) and math.isfinite(x) for x in vector):
        raise ValueError("Invalid embedding dimensions/values")
    if sum(x * x for x in vector) <= 0:
        raise ValueError("Zero embedding")
    return {
        "client_ms": round(elapsed, 2),
        "server_total_ms": round(body.get("total_duration", 0) / 1e6, 2),
        "server_load_ms": round(body.get("load_duration", 0) / 1e6, 2),
        "prompt_tokens": body.get("prompt_eval_count"),
    }, vector


def run(base_url, label, rounds):
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use an HTTP(S) endpoint without credentials/query parameters")
    report = {"label": label, "utc": datetime.now(timezone.utc).isoformat(), "models": {}}
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=120, trust_env=False) as client:
        tags = client.get("/api/tags").raise_for_status().json()["models"]
        running = client.get("/api/ps").raise_for_status().json()["models"]
        for model, dims in MODELS:
            tag = next((m for m in tags if m.get("name", "").split(":")[0] == model), None)
            if tag is None:
                report["models"][model] = {"error": "Model not installed; no download performed"}
                continue
            first, witness = embed(client, model, dims, QUERIES[0])
            rows = []
            for i in range(rounds):
                row, _ = embed(client, model, dims, QUERIES[i % len(QUERIES)])
                rows.append(row)
            report["models"][model] = {
                "digest": tag.get("digest"), "dimensions": dims,
                "initially_loaded": any(m.get("name", "").split(":")[0] == model for m in running),
                "first_observed": first, "warm": summary([r["client_ms"] for r in rows]),
                "warm_rows": rows,
                # Public synthetic query only; useful for cross-machine cosine validation.
                "synthetic_witness_vector": witness,
            }
            print(f"{model}: first={first['client_ms']}ms warm={report['models'][model]['warm']}", flush=True)
        if all("error" not in report["models"][m] for m, _ in MODELS):
            pairs = []
            with ThreadPoolExecutor(max_workers=2) as pool:
                for i in range(4):
                    started = perf_counter()
                    results = [pool.submit(embed, client, m, d, QUERIES[i]) for m, d in MODELS]
                    for result in results:
                        result.result()
                    pairs.append((perf_counter() - started) * 1000)
            report["parallel_query_pair"] = summary(pairs)
            print("two-model parallel pair:", report["parallel_query_pair"], flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--label", default="local")
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 3 <= args.rounds <= 40:
        parser.error("rounds must be 3..40")
    report = run(args.base_url, args.label, args.rounds)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
