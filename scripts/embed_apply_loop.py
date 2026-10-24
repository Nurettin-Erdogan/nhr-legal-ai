"""Gelen kutusundaki embedding sonuç dosyalarını veritabanına sürekli yazar (embed_hub toplama turu bitmeden beklemesin).

  python scripts/embed_apply_loop.py [--workers 4]

embed_hub toplamayı bitirip tek seferde yazıyordu; 256 sunucuda toplama saatler sürdüğünden vektörler günlerce yazılmıyordu
(2026-10-23). Dosya, işlenmeden önce `.work` uzantısıyla "sahiplenilir" (embed_hub'ın `*.jsonl.gz` taramasıyla çakışmaz).
HNSW dizini yüzünden yazım yavaştır (satır başına ~50-100 ms); işlem önceliği düşüktür.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
import embed_hub  # noqa: E402


def _claim(path: Path) -> Path | None:
    claimed = path.with_name(path.name + ".work")
    try:
        os.replace(path, claimed)
    except OSError:
        return None
    return claimed


def _apply(path: Path) -> int:
    try:
        return embed_hub._apply_file(path)
    except Exception as exc:  # noqa: BLE001
        embed_hub._log(f"embed-apply: {path.name} yazılamadı: {exc}")
        try:
            os.replace(path, path.with_name(path.name[: -len(".work")]))  # sonraki turda yeniden denenir
        except OSError:
            pass
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=int(os.getenv("EMBED_APPLY_LOOP_WORKERS", "4")))
    args = parser.parse_args()
    try:
        import ctypes

        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL
    except Exception:  # noqa: BLE001
        pass
    total = 0
    from concurrent.futures import FIRST_COMPLETED, wait

    # Sürekli (kayan) hat: parti engeli yok. Eskiden workers*8 dosyalık parti bitmeden yenisi alınmıyordu; tek yavaş dosya tüm işçileri
    # boşta bekletiyordu (2026-10-24: yazma oturumu 1 iken gelen kutusu büyüyordu).
    inflight: dict = {}
    done_count = 0
    last_log = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        while True:
            if len(inflight) < args.workers:
                room = args.workers - len(inflight)
                for path in sorted(embed_hub.INBOX.glob("*/*.jsonl.gz"))[: room * 2]:
                    if len(inflight) >= args.workers:
                        break
                    claimed = _claim(path)
                    if claimed:
                        inflight[pool.submit(_apply, claimed)] = claimed
            if not inflight:
                time.sleep(10)
                continue
            finished, _ = wait(list(inflight), timeout=15, return_when=FIRST_COMPLETED)
            for future in finished:
                inflight.pop(future, None)
                try:
                    total += future.result()
                except Exception:  # noqa: BLE001
                    pass
                done_count += 1
            if time.time() - last_log >= 60 and done_count:
                embed_hub._log(f"embed-apply: son dakikada {done_count} dosya (bu süreçte toplam {total:,} vektör)")
                done_count = 0
                last_log = time.time()


if __name__ == "__main__":
    raise SystemExit(main())
