from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from api.ai.request_memo import memoize_request


def test_duplicate_inflight_work_runs_once():
    entered, release = Event(), Event()
    calls = []

    @memoize_request
    def work(query):
        calls.append(query)
        entered.set()
        assert release.wait(2)
        return (query,)

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(work, 'question')
        assert entered.wait(2)
        second = pool.submit(work, 'question')
        release.set()
        assert first.result() == second.result() == ('question',)
    assert calls == ['question']


def test_exact_keys_and_request_isolation():
    calls = []
    def lookup(query):
        calls.append(query)
        return query
    first, second = memoize_request(lookup), memoize_request(lookup)
    first('query')
    first('query')
    first('query ')
    second('query')
    assert calls == ['query', 'query ', 'query']


def test_transient_failure_does_not_poison_retry():
    calls = []
    @memoize_request
    def work(query):
        calls.append(query)
        if len(calls) == 1:
            raise ValueError('transient')
        return query
    with pytest.raises(ValueError):
        work('query')
    assert work('query') == 'query'
    assert len(calls) == 2
