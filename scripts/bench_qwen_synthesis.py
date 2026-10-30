"""Compare local finalists with identical verified corpus and actual synthesis.

No cloud calls, ingestion, application configuration or conversation writes.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import httpx

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.ai.providers import create_provider  # noqa: E402
from api.ai.retrieval import STATUTE_RETRIEVAL_SQL, _execute_retrieval  # noqa: E402
from api.ai.synthesis import synthesize_answer  # noqa: E402
from api.db import database_connection  # noqa: E402

CASES = [
    ('rent', 'Kiracı kirayı ödemezse fesih için yazılı ihtarda ne belirtilmelidir ve hangi süre verilir?',
     [('6098', '315')]),
    ('leave', 'Yıllık ücretli izne hak kazanma koşulu, izin süreleri ve yaş istisnaları nelerdir?',
     [('4857', '53')]),
    ('enforcement', 'Senet yoksa ilamsız takip yapılabilir mi? Borçlu itiraz ederse hangi yollar ve süreler vardır?',
     [('2004', '58'), ('2004', '67'), ('2004', '68')]),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Output already exists')
    report = dict(kind='local_actual_synthesis_not_full_UI', paid_calls=0,
                  models=args.models, frozen=[], rows=[])

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

    frozen = []
    for case_id, question, refs in CASES:
        contexts = []
        with database_connection() as db:
            db.execute('SET TRANSACTION READ ONLY')
            for law, article in refs:
                contexts.extend(_execute_retrieval(db, STATUTE_RETRIEVAL_SQL,
                    dict(law_no=law, article_no=article, as_of=None, top_k=3), timeout='10s'))
            from api.ai.provision_context import restore_provisions
            contexts = restore_provisions(contexts, db)
        contexts = list({c.chunk_id: c for c in contexts
                         if c.verification == 'official' and c.source_type == 'legislation'}.values())
        frozen.append((case_id, question, contexts))
        report['frozen'].append(dict(case=case_id, question=question, refs=refs,
                                     contexts=[asdict(c) for c in contexts]))
    save()
    with httpx.Client(base_url='http://127.0.0.1:11434', timeout=180, trust_env=False) as client:
        for model in args.models:
            for loaded in client.get('/api/ps').json().get('models', []):
                client.post('/api/generate', json={'model': loaded['name'], 'keep_alive': 0})
            provider = create_provider(provider_name='ollama', model=model,
                ollama_num_ctx=8192, ollama_max_output_tokens=2048,
                ollama_timeout_seconds=120, ollama_keep_alive='5m')
            for case_id, question, contexts in frozen:
                row = dict(model=model, case=case_id, input_sources=len(contexts))
                if not contexts:
                    row['error'] = 'missing_fixture_evidence'
                else:
                    info = {}
                    start = time.monotonic()
                    try:
                        answer = synthesize_answer(provider, question=question, contexts=contexts,
                            max_context_chars=12000, diagnostics=info)
                        row.update(accepted=answer is not None,
                            answer=answer.text if answer else None,
                            citations=[c.reference_line for c in answer.contexts] if answer else [])
                    except Exception as exc:
                        row['error'] = type(exc).__name__
                    row.update(seconds=round(time.monotonic() - start, 3), diagnostics=info)
                report['rows'].append(row)
                save()
                print(json.dumps({k: row[k] for k in ('model', 'case', 'accepted', 'seconds', 'error') if k in row}), flush=True)
            client.post('/api/generate', json={'model': model, 'keep_alive': 0})


if __name__ == '__main__':
    main()
