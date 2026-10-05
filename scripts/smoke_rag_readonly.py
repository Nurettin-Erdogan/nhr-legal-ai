"""Real local DB + model smoke test; no persistence, portal or worker operations.

Run from the repository root. Reports grounding (text support), NOT a guarantee
of legal correctness or exhaustive retrieval. Warm/cold GPU times may differ.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.ai.providers import create_provider
from api.ai.rag import generate_grounded_answer
from api.ai.research import load_candidate_page
from api.ai.trust import verified_contexts
from api.ai.retrieval import retrieve_contexts
from api.ai.verification import verify_answer
from api.config import get_settings
from api.db import database_connection


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question', action='append')
    parser.add_argument('--include-research', action='store_true')
    args = parser.parse_args()
    questions = args.question or [
        'İcra takibinde itirazın iptali davası süresi nedir?',
        'Boşanmada ortak velayet hangi şartlarda verilir?',
    ]
    settings = get_settings()
    failed = False
    for question in questions:
        started = perf_counter()
        report = {'question': question}
        try:
            with database_connection() as connection:
                connection.execute('SET TRANSACTION READ ONLY')
                contexts = retrieve_contexts(connection, question=question, top_k=settings.rag_top_k)
            # This diagnostic cannot promote records. Production verifies them
            # on demand; the read-only smoke test uses only already trusted rows.
            contexts = verified_contexts(contexts)
            report['retrieval_seconds'] = round(perf_counter()-started, 3)
            provider = create_provider(
                provider_name=settings.ai_provider, model=settings.ai_model,
                ollama_base_url=settings.ollama_base_url,
                ollama_timeout_seconds=settings.ollama_timeout_seconds,
                ollama_max_output_tokens=settings.ollama_max_output_tokens,
                ollama_num_ctx=settings.ollama_num_ctx,
                ollama_keep_alive=settings.ollama_keep_alive,
            )
            raw = generate_grounded_answer(provider, question=question, contexts=contexts,
                                          max_context_chars=settings.rag_context_chars)
            answer = verify_answer(raw, contexts)
            report.update(total_seconds=round(perf_counter()-started, 3),
                          grounded=answer.grounded, answer=answer.text,
                          citations=[{'reference': c.reference_line, 'verification': c.verification}
                                     for c in answer.contexts])
            failed |= not answer.grounded
            if args.include_research:
                search_started = perf_counter()
                _, candidates, _, candidate_total, partial = load_candidate_page(question, 10, 0)
                report['research'] = dict(seconds=round(perf_counter()-search_started, 3),
                                          candidate_total=candidate_total, partial=partial,
                                          verified_page_size=len(verified_contexts(candidates)),
                                          live_verification='not_run_readonly')
        except Exception as exc:
            # Never print connection credentials or arbitrary provider error bodies.
            report['error_type'] = type(exc).__name__
            failed = True
        print(json.dumps(report, ensure_ascii=False), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
