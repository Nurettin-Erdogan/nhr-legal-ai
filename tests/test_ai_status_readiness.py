from contextlib import contextmanager

import pytest

from api.ai import routes


@pytest.mark.parametrize("index_ready,vectors,expected", [
    (False, True, False), (None, True, False),
    (True, False, False), (True, True, True),
])
def test_status_requires_usable_index_and_matching_vectors(monkeypatch, index_ready, vectors, expected):
    class Connection:
        def execute(self, *args):
            return self

        def fetchone(self):
            return {"exists": vectors}

    @contextmanager
    def connection():
        yield Connection()

    monkeypatch.setattr(routes, "_status_semantic_cache", None)
    monkeypatch.setattr(routes, "database_connection", connection)
    monkeypatch.setattr(routes, "shared_vector_index_ready", lambda conn: index_ready)
    assert routes._semantic_search_ready("model-a") is expected


def test_status_cache_does_not_leak_between_embedding_models(monkeypatch):
    monkeypatch.setattr(routes, "_status_semantic_cache", (routes.monotonic(), "old", True))

    @contextmanager
    def connection():
        yield object()

    monkeypatch.setattr(routes, "database_connection", connection)
    monkeypatch.setattr(routes, "shared_vector_index_ready", lambda conn: False)
    assert routes._semantic_search_ready("new") is False
