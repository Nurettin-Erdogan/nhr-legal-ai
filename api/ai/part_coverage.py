"""Explicit checker-to-sentence coverage, not a semantic entailment oracle."""
import json

from api.ai import synthesis

MARKER = 'PART_COVERAGE_V1'
INSTRUCTION = '''
PART_COVERAGE_V1: question_parts listesindeki HER alt soru için part_coverage içinde tek kayıt ver.
part_id listedeki 1 tabanlı sıradır; claim_ids o alt soruyu gerçekten açıklayan claims kimlikleridir.
Bir maddenin bulunması veya ortak kaynak numarası cevap sayılmaz. complete ancak o alt sorunun
istenen koşul/süre/istisna/yolunu supported=true, relevant=true, scope_preserved=true cümleler
birlikte açıklıyorsa true olur. Kısmen anlatılmışsa false; hiçbir cümle açıklamıyorsa claim_ids boş.
Diğer dört üst alanın yanında zorunlu ek alan:
"part_coverage":[{"part_id":1,"claim_ids":[1],"complete":true,"why":""}].
why yalnız eksikliği kısaca açıklar, kanıt değildir. Her part_id bir kez, gerçek JSON bool/tamsayı kullan.
Eksiklik varsa why başında nedenini ayır: kaynak havuzunda gereken dayanak yoksa "kaynak_eksik:",
dayanak var ama cevap anlatmamış veya koşulu bozmuşsa "ifade_duzelt:" kullan. Emin değilsen yalnız
eksikliği açıkla; kaynak eksikliği varsayma. Tam karşılanan bölümün why alanı boş kalabilir.
'''


def split_verdict(raw, part_count, claim_count):
    value = synthesis._json(raw)
    if not isinstance(value, dict) or 'part_coverage' not in value:
        raise ValueError('missing_part_coverage')
    entries = value['part_coverage']
    if not isinstance(entries, list) or len(entries) != part_count:
        raise ValueError('invalid_part_count')
    seen = set()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {'part_id', 'claim_ids', 'complete', 'why'}
                or type(entry['part_id']) is not int or not 1 <= entry['part_id'] <= part_count
                or entry['part_id'] in seen or type(entry['complete']) is not bool
                or not isinstance(entry['why'], str) or not isinstance(entry['claim_ids'], list)):
            raise ValueError('invalid_part_fields')
        ids = entry['claim_ids']
        if (any(type(i) is not int or not 1 <= i <= claim_count for i in ids)
                or len(set(ids)) != len(ids) or (entry['complete'] and not ids)):
            raise ValueError('invalid_part_claim_ids')
        seen.add(entry['part_id'])
    base = {k: v for k, v in value.items() if k != 'part_coverage'}
    return json.dumps(base, ensure_ascii=False), entries


def final_coverage(entries, candidate_to_original, displayed_ids, *, duplicate_aliases=None):
    # Aliases are created only after two source-approved claims pass lossless
    # ordered-token containment. Rejected claims never receive an alias.
    aliases = duplicate_aliases or {}
    result = []
    for entry in entries:
        original_ids = [candidate_to_original[i] for i in entry['claim_ids']]
        resolved = [i if i in displayed_ids else aliases.get(i) for i in original_ids]
        surviving = list(dict.fromkeys(i for i in resolved if i in displayed_ids))
        complete = entry['complete'] and bool(original_ids) and all(i in displayed_ids for i in resolved)
        result.append({'part_id': entry['part_id'], 'complete': complete,
                       'displayed_sentence_ids': surviving,
                       'status': 'checker_covered' if complete else 'incomplete_after_filtering',
                       'why': entry['why'][:200]})
    return result
