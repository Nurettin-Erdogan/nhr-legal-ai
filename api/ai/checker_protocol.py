"""Strict checker contract diagnostics and bounded format recovery.

No verdict normalization/coercion and no source text in diagnostics. A protocol
failure is not a substantive legal rejection. Retrying rechecks the SAME evidence;
an old or malformed positive verdict can never authorize publication.
"""
import json

from api.ai import synthesis

REDUNDANCY_INSTRUCTION = '''
İsteğe bağlı duplicate_claims alanı ekleyebilirsin: [{"id":4,"duplicate_of":1}].
Yalnız iki iddia da destekli ve aynı kapsamdaysa, sonraki iddianın TÜM anlamı önceki iddiada
zaten varsa kullan. Yeni koşul, istisna, kişi, süre, başlangıç olayı veya farklı karar içeren
cümle tekrar değildir. Sözcük benzerliği yeterli değildir. Emin değilsen alanı boş bırak.
duplicate_of daha küçük bir claim id olmalı. Diğer denetim alanlarını değiştirme.
'''


def _split_duplicates(raw, count):
    value = synthesis._json(raw)
    if not isinstance(value, dict) or 'duplicate_claims' not in value:
        return raw, []
    entries = value.pop('duplicate_claims')
    if not isinstance(entries, list):
        raise ValueError('invalid_duplicates')
    seen = set()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {'id', 'duplicate_of'}
                or type(entry['id']) is not int or type(entry['duplicate_of']) is not int
                or not 1 <= entry['duplicate_of'] < entry['id'] <= count
                or entry['id'] in seen):
            raise ValueError('invalid_duplicates')
        seen.add(entry['id'])
    return json.dumps(value, ensure_ascii=False), entries


def verdict_status(raw: str, count: int) -> str:
    try:
        value = synthesis._json(raw)
    except (ValueError, TypeError, RecursionError):
        return 'invalid_json'
    required = {'claims', 'coverage_preserved', 'source_only', 'clarification_safe'}
    if not isinstance(value, dict) or set(value) != required:
        return 'invalid_top_level_fields'
    if any(type(value[key]) is not bool for key in required - {'claims'}):
        return 'invalid_global_boolean'
    if not isinstance(value['claims'], list) or len(value['claims']) != count:
        return 'invalid_claim_count'
    if not synthesis._well_formed_verdict(raw, count):
        return 'invalid_claim_fields_or_ids'
    if value['source_only'] is not True:
        return 'source_policy_rejected'
    if value['clarification_safe'] is not True:
        return 'clarification_rejected'
    return 'valid'


def check_claims(provider, *, instruction, payload, allow_format_retry=False, diagnostics=None, part_count=0):
    info = diagnostics if diagnostics is not None else {}
    info.pop('checker_part_coverage', None)
    info.pop('checker_duplicates', None)
    count = len(payload['claims'])
    prompt = json.dumps(payload, ensure_ascii=False)
    statuses = []
    for attempt in range(2 if allow_format_retry else 1):
        reminder = '' if attempt == 0 else (
            '\nÖnceki denetim çıktısının veri biçimi geçersizdi. Aynı claims ve aynı evidence '
            'yeniden denetlenecek; iddiaları onaylamak zorunda değilsin. Yalnız şu dört üst '
            'alanı içeren JSON döndür: claims, coverage_preserved, source_only, clarification_safe. '
            'Her claim tam olarak id (tam sayı), supported (boolean), relevant (boolean), '
            'scope_preserved (boolean) ve isteğe bağlı why içerir. Gönderilen her id bir kez '
            'yer almalı; global alanlar da gerçek JSON boolean olmalı. Bilinmeyen/yanlış '
            'iddialar false kalır. Metin, açıklama veya ek alan yazma.')
        if part_count and reminder:
            from api.ai.part_coverage import INSTRUCTION
            reminder += INSTRUCTION
        from api.ai.providers import OllamaProvider
        if isinstance(provider, OllamaProvider) and 'qwen' in provider.model:
            from api.ai.local_synthesis_schema import synthesis_schema
            raw = provider.generate_structured(system_instruction=instruction + reminder,
                prompt=prompt, schema=synthesis_schema('check', payload))
        else:
            raw = provider.generate(system_instruction=instruction + reminder + REDUNDANCY_INSTRUCTION, prompt=prompt)
        normalized, entries = raw, None
        try:
            normalized, duplicates = _split_duplicates(raw, count)
            if part_count:
                from api.ai.part_coverage import split_verdict
                normalized, entries = split_verdict(normalized, part_count, count)
            status = verdict_status(normalized, count)
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            status = 'invalid_part_coverage'
        statuses.append(status)
        info.update(checker_protocol_status=status, checker_protocol_attempts=list(statuses),
                    checker_protocol_retries=attempt)
        if not status.startswith('invalid_'):
            if entries is not None and status == 'valid':
                info['checker_part_coverage'] = entries
            if duplicates and status == 'valid':
                info['checker_duplicates'] = duplicates
            return normalized
    return raw
