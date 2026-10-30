from dataclasses import replace

from api.ai.evidence_readiness import prepare_parts
from tests.factories import legislation_context


def source(i, text='usable'):
    return legislation_context(chunk_id=f'00000000-0000-0000-0000-{i:012d}',
                               source_id=f'00000000-0000-0001-0000-{i:012d}', content=text)


def test_ready_parts_do_not_repeat_searches():
    a, b = source(1), source(2)
    def forbidden(query):
        raise AssertionError('unnecessary search')
    pool, parts, status = prepare_parts([('A', frozenset({a.chunk_id})), ('B', frozenset({b.chunk_id}))],
        [a, b], forbidden, usable=lambda c: True)
    assert pool == [a, b]
    assert status == dict(parts=2, targeted_searches=0, ready_parts=2, unready_parts=0)


def test_only_missing_part_is_researched_and_sources_not_cross_bound():
    a, b = source(1), source(2)
    calls = []
    def retrieve(query):
        calls.append(query)
        return [b]
    pool, parts, status = prepare_parts([('A', frozenset({a.chunk_id})), ('B', frozenset())],
        [a], retrieve, usable=lambda c: True)
    assert calls == ['B']
    assert parts == [('A', frozenset({a.chunk_id})), ('B', frozenset({b.chunk_id}))]
    assert pool == [a, b] and status['ready_parts'] == 2


def test_repair_cannot_admit_unverified_or_unusable_sources():
    bad = replace(source(1), verification='third_party')
    cut = source(2, 'cut')
    pool, parts, status = prepare_parts([('A', frozenset())], [], lambda q: [bad, cut],
        usable=lambda c: c.content != 'cut')
    assert pool == [] and parts == [('A', frozenset())]
    assert status['unready_parts'] == 1


def test_failed_repair_preserves_other_parts_and_does_not_invent_coverage():
    a = source(1)
    def broken(query):
        raise RuntimeError('unavailable')
    pool, parts, status = prepare_parts([('A', frozenset({a.chunk_id})), ('B', frozenset())],
        [a], broken, usable=lambda c: True)
    assert pool == [a] and not parts[1][1]
    assert status['unready_parts'] == 1


def test_two_requested_decisions_are_not_satisfied_by_statutes_or_duplicate_chunks():
    from api.ai.evidence_readiness import requested_decisions_ready
    from tests.factories import court_decision_context
    a = court_decision_context()
    duplicate = replace(a, chunk_id=source(7).chunk_id)
    b = replace(a, source_id=source(8).source_id, chunk_id=source(8).chunk_id, decision_no='2026/3')
    question = 'İki Yargıtay kararını göster'
    assert not requested_decisions_ready(question, [source(1), source(2)])
    assert not requested_decisions_ready(question, [a, duplicate])
    assert requested_decisions_ready(question, [a, b])


def test_pipeline_reuses_prepared_plan_without_another_planner_call(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from api.ai import pipeline, free_answer, provision_context, decision_context
    a = source(1, 'Kiracı kira bedelini öder.')
    monkeypatch.setattr(pipeline, 'get_settings', lambda: SimpleNamespace(legislation_embedding_model=''))
    monkeypatch.setattr(pipeline, 'database_connection', lambda: nullcontext(object()))
    monkeypatch.setattr(pipeline, 'retrieve_contexts', lambda *args, **kwargs: [a])
    monkeypatch.setattr(pipeline, '_case_statute_contexts', lambda *args: [a])
    monkeypatch.setattr(provision_context, 'restore_provisions', lambda rows, db: rows)
    monkeypatch.setattr(decision_context, 'restore_decisions', lambda rows, db: rows)
    def forbidden(*args, **kwargs):
        raise AssertionError('a second planning call is forbidden')
    monkeypatch.setattr(free_answer, 'plan_question', forbidden)
    monkeypatch.setattr(free_answer, '_usable', lambda c, budget: c)
    captured = {}
    def write(provider, **kwargs):
        captured.update(kwargs)
        return 'checked answer'
    monkeypatch.setattr(free_answer, 'free_verified_answer', write)
    timings = pipeline.PipelineTimings()
    result = pipeline._free_answer(object(), 'Kiracının koşulları', [a], [], timings, object(),
        prepared_plan=[('Kiracının koşulları', ('kira koşulları',))])
    assert result == 'checked answer'
    assert captured['parts'][0][1] == frozenset({a.chunk_id})
    assert timings.extra['evidence_readiness']['ready_parts'] == 1
    assert 'write_and_check' in timings.extra['natural_stages_ms']


def test_ready_simple_chat_skips_planner_duplicate_search_and_official_network(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from api.ai import pipeline, free_answer, provision_context, decision_context, official_research, relevance
    law = source(1, 'Kira artışı tüketici fiyat endeksine göre belirlenir.')
    monkeypatch.setattr(pipeline, 'get_settings', lambda: SimpleNamespace(
        legislation_embedding_model='', official_web_research_enabled=True))
    monkeypatch.setattr(pipeline, 'database_connection', lambda: nullcontext(object()))
    def forbidden(*args, **kwargs):
        raise AssertionError('ready simple chat must not repeat planning/search/network work')
    monkeypatch.setattr(pipeline, 'retrieve_contexts', forbidden)
    monkeypatch.setattr(free_answer, 'plan_question', forbidden)
    monkeypatch.setattr(official_research, 'research_official', forbidden)
    monkeypatch.setattr(free_answer, '_usable', lambda c, budget: c)
    monkeypatch.setattr(relevance, 'context_relevant', lambda q, c: True)
    monkeypatch.setattr(provision_context, 'restore_provisions', lambda rows, db: rows)
    monkeypatch.setattr(decision_context, 'restore_decisions', lambda rows, db: rows)
    monkeypatch.setattr(free_answer, 'free_verified_answer', lambda *args, **kwargs: 'checked answer')
    timings = pipeline.PipelineTimings()
    result = pipeline._free_answer(object(), 'Kira artışı nasıl belirlenir?', [law], [], timings,
                                   object(), public_web_scope=True)
    assert result == 'checked answer'
    assert timings.extra['initial_evidence_reused'] is True
    assert timings.extra['official_web_routing'] == ['local_sources_ready']


def test_duplicate_numeric_plan_references_use_one_exact_lookup_without_embedding(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from api.ai import pipeline, free_answer, provision_context, decision_context, retrieval, relevance
    law = source(1, 'İşveren, iş sözleşmesini geçerli bir nedene dayanarak feshedebilir.')
    monkeypatch.setattr(pipeline, 'get_settings', lambda: SimpleNamespace(legislation_embedding_model='must-not-load'))
    monkeypatch.setattr(pipeline, 'database_connection', lambda: nullcontext(object()))
    def forbidden(*args, **kwargs):
        raise AssertionError('numeric reference must not embed or repeat broad discovery')
    monkeypatch.setattr(pipeline, 'create_embedding_provider', forbidden)
    monkeypatch.setattr(pipeline, 'retrieve_contexts', forbidden)
    monkeypatch.setattr(pipeline, '_case_statute_contexts', forbidden)
    monkeypatch.setattr(provision_context, 'restore_provisions', lambda rows, db: rows)
    monkeypatch.setattr(decision_context, 'restore_decisions', lambda rows, db: rows)
    monkeypatch.setattr(free_answer, '_usable', lambda c, budget: c)
    monkeypatch.setattr(relevance, 'context_relevant', lambda q, c: True)
    lookups, captured = [], {}
    def exact(connection, sql, params, **kwargs):
        lookups.append(params)
        return [law]
    monkeypatch.setattr(retrieval, '_execute_retrieval', exact)
    def write(provider, **kwargs):
        captured.update(kwargs)
        return 'checked answer'
    monkeypatch.setattr(free_answer, 'free_verified_answer', write)
    plan = [('Koşullar nelerdir?', ('4857 sayılı Kanun m. 18',)),
            ('İşçi sayısı nasıl hesaplanır?', ('4857 sayılı Kanun m. 18',))]
    timings = pipeline.PipelineTimings()
    assert pipeline._free_answer(object(), 'Birden çok konu?', [], [], timings,
                                 object(), prepared_plan=plan, public_web_scope=True) == 'checked answer'
    assert len(lookups) == 1 and lookups[0]['law_no'] == '4857' and lookups[0]['article_no'] == '18'
    assert all(ids == frozenset({law.chunk_id}) for _, ids in captured['parts'])
    assert timings.extra['local_plan_evidence_reused'] is True
    assert captured['deferred_research'] is True


def test_provisional_initial_source_does_not_hide_a_facet_without_local_evidence(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from api.ai import pipeline, free_answer, provision_context, decision_context, retrieval, relevance
    a = source(1, 'İşveren iş sözleşmesini geçerli bir nedene dayanarak feshedebilir.')
    b = source(2, 'Başvuru, yazılı dilekçe ve delillerle yapılır.')
    monkeypatch.setattr(pipeline, 'get_settings', lambda: SimpleNamespace(legislation_embedding_model=''))
    monkeypatch.setattr(pipeline, 'database_connection', lambda: nullcontext(object()))
    monkeypatch.setattr(provision_context, 'restore_provisions', lambda rows, db: rows)
    monkeypatch.setattr(decision_context, 'restore_decisions', lambda rows, db: rows)
    monkeypatch.setattr(free_answer, '_usable', lambda c, budget: c)
    monkeypatch.setattr(relevance, 'context_relevant', lambda q, c: True)
    monkeypatch.setattr(retrieval, '_execute_retrieval', lambda *args, **kwargs: [a])
    monkeypatch.setattr(pipeline, '_case_statute_contexts', lambda *args: [])
    searched, captured = [], {}
    def discover(connection, *, question, **kwargs):
        searched.append(question)
        return [b]
    monkeypatch.setattr(pipeline, 'retrieve_contexts', discover)
    def write(provider, **kwargs):
        captured.update(kwargs)
        return 'checked answer'
    monkeypatch.setattr(free_answer, 'free_verified_answer', write)
    timings = pipeline.PipelineTimings()
    plan = [('Kaynaklı ilk konu', ('4857 sayılı Kanun m. 18',)),
            ('Deliller nasıl sunulur?', ('İkinci konu delilleri',))]
    assert pipeline._free_answer(object(), 'İki ayrı konu?', [a], [], timings, object(),
        prepared_plan=plan, public_web_scope=True) == 'checked answer'
    assert 'İkinci konu delilleri' in searched
    assert b.chunk_id in captured['parts'][1][1]
    assert timings.extra['local_plan_evidence_reused'] is False


def test_one_planner_reference_does_not_hide_other_catalogued_procedural_paths(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from api.ai import pipeline, free_answer, provision_context, decision_context, retrieval, relevance

    text = 'Borçlunun ilamsız takibe itiraz etmesi hâlinde başvurulabilecek yollar ve süreler nelerdir?'
    monkeypatch.setattr(pipeline, 'get_settings', lambda: SimpleNamespace(legislation_embedding_model=''))
    monkeypatch.setattr(pipeline, 'database_connection', lambda: nullcontext(object()))
    monkeypatch.setattr(provision_context, 'restore_provisions', lambda rows, db: rows)
    monkeypatch.setattr(decision_context, 'restore_decisions', lambda rows, db: rows)
    monkeypatch.setattr(free_answer, '_usable', lambda c, budget: c)
    monkeypatch.setattr(relevance, 'context_relevant', lambda q, c: True)
    lookups, captured = [], {}

    def exact(connection, sql, params, **kwargs):
        article = params['article_no']
        lookups.append(article)
        return [replace(source(int(article)), law_no='2004', article_no=article)]

    monkeypatch.setattr(retrieval, '_execute_retrieval', exact)
    monkeypatch.setattr(pipeline, 'retrieve_contexts', lambda *a, **kw: [])

    def write(provider, **kwargs):
        captured.update(kwargs)
        return 'checked answer'

    monkeypatch.setattr(free_answer, 'free_verified_answer', write)
    timings = pipeline.PipelineTimings()
    assert pipeline._free_answer(object(), text, [], [], timings, object(), public_web_scope=True,
        prepared_plan=[(text, ('2004 sayılı Kanun m. 67',))]) == 'checked answer'
    assert {'66', '67', '68'} <= set(lookups)
    assert lookups.count('67') == 1
    assert {'66', '67', '68'} <= {c.article_no for c in captured['contexts']}
    assert timings.extra['local_plan_evidence_reused'] is True
