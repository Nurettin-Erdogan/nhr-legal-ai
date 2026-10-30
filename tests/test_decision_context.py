from dataclasses import replace
import hashlib
import pytest
from api.ai.decision_context import complete_decision, restore_decisions
from tests.factories import court_decision_context


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_header_hit_recovers_full_reasoning_without_changing_citation_identity():
    header = 'Dava tapu iptali istemine ilişkindir.'
    full = header + '\n' + ('Bu bölümde deliller birlikte değerlendirilir. ' * 8)
    hit = court_decision_context(content=header)
    restored = complete_decision(hit, full, digest(full))
    assert restored.content == full
    assert restored.chunk_id == hit.chunk_id and restored.source_id == hit.source_id
    assert restored.reference_line == hit.reference_line


@pytest.mark.parametrize('mutation', ['digest', 'membership', 'private', 'unverified', 'oversize'])
def test_mismatched_or_unsafe_document_is_not_restored(mutation):
    text = 'Kaynak cümlesi. ' * 20
    hit = court_decision_context(content='Kaynak cümlesi.')
    if mutation == 'membership':
        hit = replace(hit, content='Başka metin.')
    if mutation == 'private':
        hit = replace(hit, source_type='document')
    if mutation == 'unverified':
        hit = replace(hit, verification='third_party')
    if mutation == 'oversize':
        text *= 100
    assert complete_decision(hit, text, 'wrong' if mutation == 'digest' else digest(text)) is None


def test_sql_binds_source_chunk_revision_and_verified_current_state():
    from contextlib import nullcontext
    class DB:
        def transaction(self):
            return nullcontext()
        def execute(self, sql, params=None):
            if params:
                for token in ['chunk.id=%(chunk)s', 'ls.id=%(source)s', 'ls.is_current',
                    "ls.source_type='court_decision'", 'IS NOT DISTINCT FROM %(version)s',
                    'IS NOT DISTINCT FROM %(revision)s', "ls.ingest_status = 'ready'"]:
                    assert token in sql
            return self
        def fetchone(self):
            return None
    hit = court_decision_context()
    assert restore_decisions([hit], DB()) == [hit]
