"""Çekici düğüm (AWS/Azure): iş dosyalarındaki karar kimliklerinin resmî metnini Bedesten'den çeker, dosyaya yazar.

Veritabanı yok, yalnız standart kütüphane + `ingestion/bedesten_emsal.py` + `ingestion/text.py`. PC (ana veritabanı)
`scripts/fetcher_hub.py` ile iş dosyası gönderir, sonuç parçalarını alır, karşılaştırıp işler.

Dizin (düğümde, betiğin yanında):
  jobs/<ad>.jsonl.gz         her satır {"external_id": "yargitay:123"}; işlenince silinir
  jobs/<ad>.progress         işlenen satır sayısı (kaldığı yerden devam)
  out/<ad>-<başlangıç>.jsonl.gz  sonuç parçası (200 kayıt); yazılırken .tmp, bitince ad değişir
  worker.log                 5 dk'da bir ölçüm satırı

Sonuç satırı: {"external_id", "status": ok|not_found|error, "text", "error", "fetched_at"}
Hız: IP başına ~750 istek/sa (4,4 sn aralık, 429'da yavaşlar). Tek süreç çalışır (systemd: nhr-fetcher.service).
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from ingestion.bedesten_emsal import BedestenClient, BedestenError, BedestenRateLimited  # noqa: E402
from ingestion.text import html_to_text, normalize_text  # noqa: E402

JOBS = ROOT / "jobs"
OUT = ROOT / "out"
PART_SIZE = 200
FLOOR = 4.4
STOP = False
log = logging.getLogger("fetch_worker")


def _stop(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


class Fetcher:
    def __init__(self) -> None:
        self.client = BedestenClient(min_interval=4.5, timeout=30.0)
        self.streak = 0
        self.requests = 0
        self.limited = 0
        self.beat = (time.time(), 0, 0)

    def _heartbeat(self) -> None:
        at, req, lim = self.beat
        now = time.time()
        if now - at >= 300:
            rate = (self.requests - req) / ((now - at) / 3600)
            log.info("ölçüm: %d istek/5 dk = %.0f istek/sa | 429=%d | aralık=%.1f sn",
                     self.requests - req, rate, self.limited - lim, self.client.min_interval)
            self.beat = (now, self.requests, self.limited)

    def fetch(self, document_id: str) -> dict:
        errors = 0
        while not STOP:
            self._heartbeat()
            self.requests += 1
            try:
                text = normalize_text(html_to_text(self.client.content_html(document_id)))
            except BedestenRateLimited as exc:
                self.limited += 1
                self.streak = 0
                self.client.min_interval = min(8.0, self.client.min_interval * 1.03)
                time.sleep(exc.retry_after)
                continue
            except BedestenError as exc:
                message = str(exc)
                if "bulunamadı" in message or "Record not found" in message or "boş" in message:
                    return {"status": "not_found", "error": message[:160]}
                errors += 1
                if errors >= 4:
                    return {"status": "error", "error": message[:160]}
                time.sleep(10 * errors)
                continue
            self.streak += 1
            if self.streak >= 20:
                self.client.min_interval = max(FLOOR, self.client.min_interval * 0.97)
                self.streak = 0
            return {"status": "ok", "text": text}
        raise KeyboardInterrupt


def _write_part(job: str, start: int, rows: list[dict]) -> None:
    final = OUT / f"{job}-{start:07d}.jsonl.gz"
    tmp = final.with_suffix(".gz.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, final)


def run_job(fetcher: Fetcher, path: Path) -> bool:
    job = path.name[: -len(".jsonl.gz")]
    progress = path.with_name(job + ".progress")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        ids = [json.loads(line)["external_id"] for line in handle if line.strip()]
    done = int(progress.read_text()) if progress.exists() else 0
    log.info("iş %s: %d kayıt, %d yapılmış", job, len(ids), done)
    while done < len(ids):
        start = done
        rows = []
        for external_id in ids[start:start + PART_SIZE]:
            if STOP:
                return False
            document_id = external_id.split(":", 1)[1]
            result = fetcher.fetch(document_id)
            result.update(external_id=external_id, fetched_at=datetime.now(UTC).isoformat(timespec="seconds"))
            rows.append(result)
            time.sleep(0)  # aralığı BedestenClient (reserve_slot) uygular
        _write_part(job, start, rows)
        done = start + len(rows)
        progress.write_text(str(done))
        log.info("iş %s: %d/%d", job, done, len(ids))
    path.unlink(missing_ok=True)
    progress.unlink(missing_ok=True)
    return True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / "worker.log", encoding="utf-8"), logging.StreamHandler()])
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    JOBS.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    fetcher = Fetcher()
    while not STOP:
        jobs = sorted(JOBS.glob("*.jsonl.gz"))
        if not jobs:
            time.sleep(60)
            continue
        try:
            run_job(fetcher, jobs[0])
        except KeyboardInterrupt:
            break
    log.info("durduruldu")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
