"""All configured statute hints: retrieval vs model-evidence admission.

Read-only public corpus. No embedding, provider, private data or model calls.
This is not fresh official-source verification or an answer-quality guarantee.
"""
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api import statute_hints
from api.ai.free_answer import _usable
from api.ai.provision_context import restore_provisions
from api.ai.retrieval import _execute_retrieval, STATUTE_RETRIEVAL_SQL
from api.db import database_connection


def main():
    references = {(hint.law_no, hint.article_no)
                  for topic in statute_hints.TOPICS for hint in topic.hints}
    references.update((h.law_no, h.article_no) for h in statute_hints._EMPLOYMENT_RIGHTS_HINTS)
    results = []
    for law, article in sorted(references):
        with database_connection() as db:
            db.execute('SET TRANSACTION READ ONLY')
            rows = _execute_retrieval(db, STATUTE_RETRIEVAL_SQL,
                dict(law_no=law, article_no=article, as_of=None, top_k=25))
            restored = restore_provisions(rows, db)
        usable = [c for c in restored if _usable(c, 36000) is not None]
        results.append(dict(law=law, article=article, found=len(rows), admitted=len(usable),
            **({'tails': [c.content[-360:] for c in restored if _usable(c, 36000) is None]}
               if '--details' in sys.argv else {}),
            status='missing' if not rows else 'candidate_limit_review' if len(rows) == 25
            else 'rejected' if not usable else 'partially_admitted' if len(usable) < len(rows) else 'admitted'))
    print(json.dumps(dict(scope='all configured current statute hint references; read-only',
        generation_calls=0, references=len(results), counts=dict(Counter(r['status'] for r in results)),
        review=[r for r in results if r['status'] != 'admitted']), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
