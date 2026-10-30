"""Read-only public retrieval audit. No model generation, cloud, or chat writes.

Fixed synthetic cases make branch losses reproducible without paid calls.
Only public source references and aggregate diagnostics are printed.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.ai import pipeline, retrieval
from api.ai.discovery import select_answer_contexts
from api.ai.synthesis import _source_views, _without_cut_off_tail
from api.config import get_settings
from api.schemas import AIAnswerRequest

CASES = (
    ("reinstatement", "2026 yılı itibarıyla işe iade davası açmanın şartları nelerdir? İşyerindeki 30 işçi şartı nasıl hesaplanır? İlgili güncel kanun maddelerini ve doğrulanabildiğin iki Yargıtay kararını resmî kaynaklarıyla göster."),
    ("explicit_with_cases", "Kiracıya 30 gün ödeme süresi verdim ancak ihtarnamede borç ödenmezse sözleşmenin feshedileceğini belirtmedim. TBK m.315'e göre bu ihtar geçerli midir? İlgili Yargıtay kararlarıyla ve doğrulanabilir kaynaklarla açıkla."),
    ("topic_with_cases", "Kira ihtarında ödeme yapılmazsa sözleşmenin feshedileceğinin belirtilmemesi hakkında Yargıtay kararları"),
    ("mediation", "Kira uyuşmazlıklarında zorunlu arabuluculuk ve dava şartı"),
)

def describe(context):
    complete = bool(_source_views([context], 36000))
    trimmed = _without_cut_off_tail(context) if not complete else None
    return dict(chunk=str(context.chunk_id), source=str(context.source_id),
                type=context.source_type, reference=context.reference_line,
                verification=context.verification, characters=len(context.content),
                usable=complete or bool(trimmed and _source_views([trimmed], 36000)))

async def main():
    settings = get_settings()
    execute = retrieval._execute_retrieval
    capture = []
    def traced(connection, sql, params, **kwargs):
        rows = execute(connection, sql, params, **kwargs)
        branch = next((name for name in ("STATUTE_RETRIEVAL_SQL", "SEMANTIC_RETRIEVAL_SQL", "LEGISLATION_M3_SQL", "LEGISLATION_SEMANTIC_SQL")
                       if sql == getattr(retrieval, name)), "lexical")
        capture.append((branch, rows))
        return rows
    retrieval._execute_retrieval = traced
    try:
        for name, question in CASES:
            if '--case' in sys.argv and name != sys.argv[sys.argv.index('--case') + 1]:
                continue
            capture.clear()
            start = monotonic()
            shared, legislation = await asyncio.gather(pipeline._embed_question(question), pipeline._embed_legislation_question(question))
            diagnostic = {}
            rows = await pipeline._retrieve_with_warm_retry(AIAnswerRequest(question=question),
                user_id=None, query_embedding=shared, legislation_embedding=legislation,
                top_k=48, embedding_model=settings.embedding_model, diagnostics=diagnostic)
            selected = select_answer_contexts(rows, settings.rag_top_k + 2, question=question)
            model_pool = pipeline._with_decisions(selected, rows, question=question)
            from api.ai.provision_context import restore_provisions
            from api.db import database_connection
            with database_connection() as connection:
                restored_pool = restore_provisions(model_pool, connection)
            print(json.dumps(dict(case=name, seconds=round(monotonic()-start, 2),
                explicit_laws=retrieval.question_law_numbers(question),
                explicit_articles=retrieval.question_article_numbers(question),
                embeddings=dict(shared=shared is not None, legislation=legislation is not None),
                diagnostics=diagnostic,
                branches=[dict(name=b, count=len(items), decisions=sum(c.source_type == "court_decision" for c in items)) for b, items in capture],
                returned=[describe(c) for c in rows[:12]],
                model_pool=[describe(c) for c in model_pool],
                restored_pool=[describe(c) for c in restored_pool]), ensure_ascii=False, default=str), flush=True)
    finally:
        retrieval._execute_retrieval = execute

if __name__ == "__main__":
    asyncio.run(main())
