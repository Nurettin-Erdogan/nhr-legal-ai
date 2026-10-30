from contextlib import contextmanager
from types import SimpleNamespace
import psycopg
import pytest
from api.ai import vector_index, retrieval
from tests.factories import court_decision_context


class Connection:
    def __init__(self, ready, database="test"):
        self.ready = ready
        self.info = SimpleNamespace(host="test",port=5432,dbname=database,user="runtime")
        self.calls = []
    @contextmanager
    def transaction(self):
        yield self
    def execute(self, sql, params=None):
        self.calls.append((sql,params))
        if sql == "SHOW statement_timeout":
            self.row = {"statement_timeout":"20s"}
        elif sql == vector_index.SEMANTIC_INDEX_READY_SQL:
            if isinstance(self.ready,Exception):
                raise self.ready
            self.row = {"ready":self.ready}
        return self
    def fetchone(self):
        return self.row


@pytest.fixture(autouse=True)
def reset_cache():
    vector_index._cache.clear()
    yield
    vector_index._cache.clear()


def test_readiness_requires_the_binary_expression_used_by_live_retrieval():
    sql = vector_index.SEMANTIC_INDEX_READY_SQL
    for required in ("ix.indisvalid", "ix.indisready", "bit_hamming_ops", "ix.indkey[0] = 0",
                     "public.legal_chunks", "binary_quantize(embedding)", "bit(768)",
                     "pg_get_indexdef", "ix.indpred IS NULL"):
        assert required in sql
    assert "vector_cosine_ops" not in sql
    connection = Connection(False)
    assert vector_index.shared_vector_index_ready(connection) is False
    assert connection.calls[-1] == ("SELECT set_config('statement_timeout', %s, true)",("20s",))


def test_cache_is_database_scoped_and_rechecks_when_index_may_have_finished(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(vector_index,"monotonic",lambda:clock[0])
    missing, ready = Connection(False), Connection(True,database="other")
    assert vector_index.shared_vector_index_ready(missing) is False
    missing.ready = True
    assert vector_index.shared_vector_index_ready(missing) is False
    assert vector_index.shared_vector_index_ready(ready) is True
    clock[0] += vector_index._TTL_SECONDS + 1
    assert vector_index.shared_vector_index_ready(missing) is True


def test_catalog_error_does_not_claim_missing_index_or_poison_other_retrieval():
    assert vector_index.shared_vector_index_ready(Connection(psycopg.errors.QueryCanceled())) is None
    assert vector_index.shared_vector_index_ready(object()) is None


def test_missing_shared_index_skips_only_unbounded_vector_sort_and_keeps_other_sources(monkeypatch):
    calls = []
    monkeypatch.setattr(vector_index,"shared_vector_index_ready",lambda connection:False)
    context = court_decision_context(content="Ortak velayet için çocuğun yararı gözetilir.")
    def execute(connection,sql,params,**kwargs):
        calls.append(sql)
        assert sql != retrieval.SEMANTIC_RETRIEVAL_SQL
        return [] if sql in (retrieval.LEGISLATION_SEMANTIC_SQL,retrieval.LEGISLATION_M3_SQL) else [context]
    monkeypatch.setattr(retrieval,"_execute_retrieval",execute)
    diagnostics = {}
    rows = retrieval.retrieve_contexts(object(),question="Ortak velayet şartları nelerdir?",top_k=6,
        query_embedding=[0.1]*768,embedding_model="nomic-embed-text",legislation_embedding=[0.2]*1024,
        diagnostics=diagnostics)
    assert rows and diagnostics["partial"] is True
    assert diagnostics["semantic_index_status"] == "missing"
    assert diagnostics["branches"][0]["status"] == "skipped_unindexed"
    assert retrieval.LEGISLATION_SEMANTIC_SQL in calls and retrieval.LEGISLATION_M3_SQL in calls
    assert any(sql not in (retrieval.LEGISLATION_SEMANTIC_SQL,retrieval.LEGISLATION_M3_SQL) for sql in calls)
