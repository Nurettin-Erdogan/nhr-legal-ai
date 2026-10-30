"""Read-only, synthetic assistant diagnostics; no saved conversation writes.

Default: local retrieval only. --live also spends configured cloud tokens on
these fixed public questions. No credentials or raw provider exceptions logged.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
from pathlib import Path
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.ai import pipeline
from api.ai.discovery import select_answer_contexts
from api.ai.synthesis import _source_views, _without_cut_off_tail
from api.config import get_settings
from api.schemas import AIAnswerRequest

QUESTIONS = (
    "Kira artışında uygulanacak mevzuatı ve ilgili kararları araştır.",
    "İşten çıkarıldım haklarım nelerdir?",
    "Boşanmada ortak velayet hangi şartlarda mümkündür?",
)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--trace-rejections", action="store_true",
                        help="Only these fixed public examples: print support findings and public evidence")
    args = parser.parse_args()
    if args.trace_rejections and args.live:
        from api.ai import synthesis
        check = synthesis._support_failures

        def traced(text, quotes, references):
            failures = check(text, quotes, references)
            if failures:
                notes = [f for f in failures if f in synthesis._CHECKER_JUDGED
                         and len(quotes) >= synthesis._LONG_EVIDENCE]
                print(json.dumps({"support_findings": failures,
                                  "hard_failures": [f for f in failures if f not in notes],
                                  "checker_notes": notes, "claim": text,
                                  "evidence": quotes, "references": references}, ensure_ascii=False), flush=True)
            return failures

        synthesis._support_failures = traced
    settings = get_settings()
    for run in range(max(1, min(args.repeat, 3))):
        for question in QUESTIONS[:max(1, min(args.limit, 3))]:
            started = monotonic()
            request = AIAnswerRequest(question=question)
            row = {"run": run + 1, "question": question, "live": args.live}
            try:
                if args.live:
                    response, timings = await pipeline.execute_answer(request, None)
                    row.update(answer=response.answer, grounded=response.grounded,
                               provider=response.provider, model=response.model,
                               citations=[c.reference for c in response.citations],
                               timings=dataclasses.asdict(timings))
                else:
                    shared, legislation = await asyncio.gather(
                        pipeline._embed_question(question), pipeline._embed_legislation_question(question))
                    diagnostic = {}
                    contexts = await pipeline._retrieve_with_warm_retry(request,
                        user_id=None, query_embedding=shared, legislation_embedding=legislation,
                        top_k=48, embedding_model=settings.embedding_model, diagnostics=diagnostic)
                    selected = select_answer_contexts(contexts, settings.rag_top_k + 2, question=question)
                    row.update(diagnostics=diagnostic, selected=[
                        {"type": c.source_type, "reference": c.reference_line,
                         "characters": len(c.content),
                         "complete_evidence": bool(_source_views([c], settings.rag_synthesis_context_chars)),
                         "trimmable": _without_cut_off_tail(c) is not None}
                        for c in selected])
            except Exception as error:
                row["error_type"] = type(error).__name__
            row["seconds"] = round(monotonic() - started, 2)
            print(json.dumps(row, ensure_ascii=False, default=str), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
