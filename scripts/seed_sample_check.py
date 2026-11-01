"""`seed_sample_export.py` örneklemini resmî portalla karşılaştırır (veritabanı KULLANMAZ; Azure'da çalışır).

Her kayıt için resmî metin kimlikle çekilir (1 istek) ve `verify_seeds.compare_texts` kuralıyla karşılaştırılır:
  verified   : boşluk/noktalama farkı ya da kayıt resmî metnin parçası (kayıt resmîyle aynı hukuki içerik)
  mismatch   : harf/rakam farkı var
  unavailable: portal kaydı vermiyor (ör. "Record not found")
Sonuçlar JSONL'a eklenir (kaldığı yerden devam eder) ve özet, Wilson %95 güven aralığıyla yazdırılır.

  python scripts/seed_sample_check.py --in ~/seed-sample.jsonl.gz --out ~/seed-sample-results.jsonl
  python scripts/seed_sample_check.py --summary --out ~/seed-sample-results.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

STOP = False


def _handle_stop(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def summarize(results_path: Path) -> None:
    rows = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for source in (None, "yargitay", "danistay"):
        subset = [r for r in rows if source is None or r["external_id"].startswith(source + ":")]
        if not subset:
            continue
        counts: dict[str, int] = {}
        kinds: dict[str, int] = {}
        for r in subset:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            if r.get("verification"):
                kinds[r["verification"]] = kinds.get(r["verification"], 0) + 1
        decided = counts.get("verified", 0) + counts.get("mismatch", 0)
        low, high = wilson(counts.get("verified", 0), decided)
        label = source or "toplam"
        print(f"[{label}] n={len(subset)} {counts} | açılan {decided}: doğrulanan oranı %{100 * counts.get('verified', 0) / max(decided, 1):.1f} "
              f"(%95 aralık %{100 * low:.1f}-%{100 * high:.1f}) | türler {kinds}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="input", help="seed-sample.jsonl.gz")
    parser.add_argument("--out", required=True)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--delay", type=float, default=4.6)
    parser.add_argument("--cooldown", type=float, default=15.0)
    args = parser.parse_args()
    out = Path(args.out).expanduser()
    if args.summary:
        summarize(out)
        return 0
    if not args.input:
        raise SystemExit("--in gerekli")
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    from ingestion.bedesten_emsal import BedestenRateLimited
    from ingestion.hf_700k import strip_third_party_markup
    from verify_seeds import _fetch_official_text, compare_texts

    done = set()
    if out.exists():
        done = {json.loads(line)["external_id"] for line in out.read_text(encoding="utf-8").splitlines() if line.strip()}
    with gzip.open(Path(args.input).expanduser(), "rt", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    todo = [r for r in records if r["external_id"] not in done]
    print(f"toplam {len(records)}, yapılmış {len(done)}, kalan {len(todo)}", flush=True)
    t0 = time.time()
    processed = 0
    with out.open("a", encoding="utf-8") as sink:
        for record in todo:
            if STOP:
                break
            source, document_id = record["external_id"].split(":", 1)
            status, verification, reason = "unavailable", "", ""
            while not STOP:
                try:
                    official = _fetch_official_text(source, None, document_id)
                except BedestenRateLimited:
                    time.sleep(args.cooldown)
                    continue
                except Exception as exc:  # noqa: BLE001
                    message = str(exc)
                    if "geçersiz" in message or "bulunamadı" in message or "Record not found" in message:
                        reason = message[:100]
                    elif "429" in message or "hız sınırı" in message:
                        time.sleep(args.cooldown)
                        continue
                    else:
                        reason = message[:100]
                    break
                if official.strip():
                    status, verification = compare_texts(record["text"], official, strip_third_party_markup(official))
                else:
                    reason = "boş resmî metin"
                break
            sink.write(json.dumps({"external_id": record["external_id"], "decision_date": record["decision_date"],
                                   "status": status, "verification": verification, "reason": reason,
                                   "seed_len": len(record["text"])}, ensure_ascii=False) + "\n")
            sink.flush()
            processed += 1
            if processed % 50 == 0:
                print(f"{datetime.now():%H:%M:%S} {processed}/{len(todo)} | {(time.time() - t0) / 60:.0f} dk", flush=True)
            time.sleep(args.delay)
    summarize(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
