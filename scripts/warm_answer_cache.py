"""Genel hukuk soruları için kaynaklarıyla doğrulanmış cevapları önceden hazırlar (api/ai/warm_cache.py, migration 065).

Her soru GERÇEK cevap hattından geçer (arama, yazma, kod kapıları, bağımsız denetim); yalnız tam, kaynaklı ve kısmi olmayan cevaplar
kaydedilir. Kayıt, atıf yapılan parçaların o anki durumuna bağlıdır: mevzuat değişirse kayıt kendiliğinden geçersiz olur. Tabloya
yalnız bu betik (nhr_app) yazar; kullanıcı verisi ve canlı trafik buraya girmez.

  python scripts/warm_answer_cache.py                         # docs/warmup-questions.txt, 2 eşzamanlı
  python scripts/warm_answer_cache.py --limit 10              # deneme
  python scripts/warm_answer_cache.py --concurrency 3 --refresh   # var olanları da yeniden üret
  python scripts/warm_answer_cache.py --dry-run               # yalnız say

Kayıtlar mevzuat güncellenince ya da `ANSWER_PIPELINE_VERSION` yükselince yeniden üretilmelidir (betiği tekrar çalıştırın).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from api.ai import warm_cache  # noqa: E402
from api.db import admin_database_connection  # noqa: E402
from api.schemas import AIAnswerRequest  # noqa: E402


def read_questions(path: Path) -> list[tuple[str, list[str]]]:
    """(soru, takma adlar). Satır biçimi: `Soru? || eşdeğer ifade || bir başka eşdeğer ifade`. Cevap yalnız ilk (asıl) soru için
    üretilir; takma adlar aynı cevaba bağlanır. Takma ad yalnız ANLAMCA AYNI soru olmalıdır (farklı bir şey soruyorsa ayrı satır)."""
    seen, questions = set(), []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        main, *aliases = [part.strip() for part in text.split("||") if part.strip()]
        key = warm_cache.question_key(main)
        if key in seen:
            continue
        seen.add(key)
        kept = []
        for alias in aliases:
            alias_key = warm_cache.question_key(alias)
            if alias_key not in seen:
                seen.add(alias_key)
                kept.append(alias)
        questions.append((main, kept))
    return questions


async def warm_one(item: tuple[str, list[str]], semaphore: asyncio.Semaphore, refresh: bool,
                   runs: int) -> tuple[str, str, float, int]:
    question, aliases = item
    from api.ai.pipeline import execute_answer

    async with semaphore:
        started = time.monotonic()
        if not refresh:
            with admin_database_connection() as connection:
                if warm_cache.lookup(connection, question) is not None and all(
                        warm_cache.lookup(connection, alias) is not None for alias in aliases):
                    return question, "zaten hazır", 0.0, 0
        captured: list = []
        why = ""
        for attempt in range(1, runs + 1):
            token = warm_cache.collector.set(lambda asked, answer, model: captured.append((asked, answer, model)))
            try:
                response, timings = await execute_answer(AIAnswerRequest(question=question), None)
            except Exception as exc:  # noqa: BLE001 - one failing question must not stop the batch
                return question, f"hata: {str(exc)[:70]}", time.monotonic() - started, 0
            finally:
                warm_cache.collector.reset(token)
            if captured:
                break
            free = timings.extra.get("free_answer") or {}
            why = (f"tür={response.answer_kind} durum={free.get('status')} kapsam={free.get('coverage_preserved')} "
                   f"kısmi={bool(free.get('partial_answer'))} eksik_bölüm={bool(free.get('uncovered_parts'))} koşu={attempt}")
        elapsed = time.monotonic() - started
        if not captured:
            return question, f"atlandı ({why})", elapsed, 0
        asked, answer, model = captured[-1]
        with admin_database_connection() as connection:
            stored = warm_cache.store(connection, asked, answer, model)
            if stored:
                for alias in aliases:
                    warm_cache.store(connection, alias, answer, model)
            connection.commit()
        label = "kaydedildi" if stored else "atlandı (kaynaklar okunamadı)"
        return (f"{question} (+{len(aliases)} takma ad)" if aliases and stored else question), label, elapsed, len(answer.text)


async def run(questions: list[tuple[str, list[str]]], concurrency: int, refresh: bool, runs: int) -> int:
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [asyncio.create_task(warm_one(question, semaphore, refresh, runs)) for question in questions]
    counts: dict[str, int] = {}
    for position, task in enumerate(asyncio.as_completed(tasks), 1):
        question, status, seconds, size = await task
        key = status.split(" (")[0].split(":")[0]
        counts[key] = counts.get(key, 0) + 1
        print(f"[{position}/{len(tasks)}] {status} | {seconds:.0f} sn {size} krk | {question[:80]}", flush=True)
    print("özet:", ", ".join(f"{name}={count}" for name, count in sorted(counts.items())), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=ROOT / "docs" / "warmup-questions.txt")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--runs", type=int, default=2, help="tam ve kaynaklı cevap çıkmazsa bir soru için en çok kaç koşu")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    questions = read_questions(args.file)
    if args.limit:
        questions = questions[: args.limit]
    print(f"{len(questions)} soru ({sum(len(a) for _, a in questions)} takma ad), eşzamanlılık {args.concurrency}", flush=True)
    if args.dry_run:
        return 0
    # Offline there is no user waiting: allow the completeness retry the live path skips after 45 s.
    from api.ai import free_answer
    free_answer._RETRY_ONLY_BEFORE_SECONDS = 300.0
    return asyncio.run(run(questions, max(1, args.concurrency), args.refresh, max(1, args.runs)))


if __name__ == "__main__":
    raise SystemExit(main())
