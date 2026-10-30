"""Local model checks against frozen public sources, no DB/portal/worker writes."""
import argparse
import json
from pathlib import Path
from time import perf_counter

from api.ai.explanation import CHECK, explain_verified_answer, with_coverage_notice
from api.ai.providers import create_provider
from api.ai.rag import generate_grounded_answer
from api.ai.verification import verify_answer
from scripts.compare_local_rag import context_from_json


class Recorder:
    def __init__(self):
        self.provider = create_provider(provider_name='qwen', model='qwen3.5:4b',
            ollama_num_ctx=4096, ollama_max_output_tokens=768)
        self.calls = []
    def generate(self, **kw):
        start = perf_counter()
        output = self.provider.generate(**kw)
        self.calls.append(dict(seconds=round(perf_counter()-start,3), raw=output))
        return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Refusing to overwrite report')
    provider = Recorder()
    rows = []
    for case in json.loads(args.fixture.read_text(encoding='utf8')):
        contexts = [context_from_json(c) for c in case.get('contexts', [])]
        if any(c.verification != 'official' or c.source_type == 'document' for c in contexts):
            raise ValueError('Only verified public contexts allowed')
        start = perf_counter()
        provider.calls = []
        raw = generate_grounded_answer(provider, question=case['question'], contexts=contexts,
                                       max_context_chars=2400)
        answer = verify_answer(raw, contexts, question=case['question'])
        explanation = explain_verified_answer(provider, question=case['question'], answer=answer)
        explanation = with_coverage_notice(explanation, case['question'])
        row = dict(id=case['id'], question=case['question'], grounded=answer.grounded,
                   extractive=answer.text, answer=explanation.text,
                   explanation_accepted=answer.text!=explanation.text,
                   seconds=round(perf_counter()-start,3), calls=provider.calls,
                   references=[c.reference_line for c in explanation.contexts])
        rows.append(row)
        print(json.dumps({k:v for k,v in row.items() if k!='calls'},ensure_ascii=False),flush=True)
    # Original synthetic examples, not Turkish law. Test semantic checker against
    # condition dropping, negation, invented consequence and unrelated evidence.
    controls = [
        ('supported', 'Deneme başvurusu yazılı yapılır.', 'Deneme başvurusu yazılı yapılmalıdır.', True),
        ('negation', 'Deneme başvurusu kabul edilmez.', 'Deneme başvurusu kabul edilir.', False),
        ('condition', 'Deneme başvurusu yalnız belge sunulursa kabul edilir.', 'Deneme başvurusu kabul edilir.', False),
        ('allegation', 'Davacı başvurusunun kabulünü talep etmiştir.', 'Mahkeme başvuruyu kabul etmiştir.', False),
        ('consequence', 'Deneme başvurusu yazılı yapılır.', 'Başvuru yazılı yapılmazsa on bin lira ceza uygulanır.', False),
        ('wrong_topic', 'Balıkçı barınağının kira sözleşmesi feshedilir.', 'Balıkçı barınağının kira sözleşmesi feshedilir.', False),
    ]
    checks = []
    for name, quote, claim, expected in controls:
        q = 'TÜFE üzeri kira artışı nasıl değerlendirilir?' if name=='wrong_topic' else ('Deneme başvurusu hangi şekilde yapılır?' if name=='supported' else 'Deneme başvurusu kabul edilir mi?')
        output = provider.generate(system_instruction=CHECK, prompt=json.dumps(dict(
            question=q, claims=[dict(text=claim, sources=[1])], quotations={1:quote}),ensure_ascii=False))
        try:
            verdict = json.loads(output.strip().removeprefix('```json').removesuffix('```'))
            accepted = all(verdict.get(k) is True for k in ('supported','relevant','scope_preserved','coverage_preserved'))
        except (ValueError, AttributeError):
            accepted = False
        checks.append(dict(id=name,expected=expected,accepted=accepted,passed=expected==accepted,raw=output))
        print(json.dumps(checks[-1],ensure_ascii=False),flush=True)
    args.output.write_text(json.dumps(dict(answers=rows,synthetic_controls=checks),ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':
    main()
