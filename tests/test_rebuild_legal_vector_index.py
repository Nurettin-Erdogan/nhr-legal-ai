from scripts.rebuild_legal_vector_index import CREATE_SQL, run
from api.ai.vector_index import INDEX_READY_SQL


class Connection:
    def __init__(self,*,ready=False,named=None,building=()):
        self.ready,self.named,self.building=ready,named,building
        self.calls=[]
    def execute(self,sql,params=None):
        self.calls.append(sql)
        self.sql=sql
        if sql==CREATE_SQL:
            self.ready=True
        return self
    def fetchone(self):
        return {"ready":self.ready} if self.sql==INDEX_READY_SQL else self.named
    def fetchall(self):
        return self.building


def test_default_plan_does_not_start_ddl_or_change_settings():
    connection=Connection()
    assert run(connection)==0
    assert all(sql.lstrip().startswith("SELECT") for sql in connection.calls)


def test_explicit_build_is_concurrent_and_never_deletes_vectors_or_existing_index():
    connection=Connection()
    assert run(connection,apply=True)==0
    assert "CREATE INDEX CONCURRENTLY" in CREATE_SQL
    assert "WHERE embedding IS NOT NULL" in CREATE_SQL
    assert not any("DROP " in sql or "UPDATE " in sql or "DELETE " in sql for sql in connection.calls)
    assert connection.calls[-1]==INDEX_READY_SQL


def test_existing_invalid_index_or_active_build_requires_review_without_mutation():
    for connection in (Connection(named={"indisvalid":False,"indisready":True}),
                       Connection(building=[{"phase":"building index"}])):
        assert run(connection,apply=True)==2
        assert all(sql.lstrip().startswith("SELECT") for sql in connection.calls)


def test_explicit_recovery_drops_only_empty_invalid_placeholder_concurrently():
    connection=Connection(named={"indisvalid":False,"indisready":False,"bytes":0,"correct_table":True})
    assert run(connection,apply=True,repair_empty_invalid=True)==0
    assert "DROP INDEX CONCURRENTLY public.idx_legal_chunks_embedding_hnsw" in connection.calls
    assert "SET lock_timeout = 0" in connection.calls


def test_recovery_never_drops_nonempty_ready_wrong_table_or_active_indexes():
    for changed in ({"bytes":8192},{"indisready":True},{"correct_table":False},{"indisvalid":True}):
        named={"indisvalid":False,"indisready":False,"bytes":0,"correct_table":True,**changed}
        connection=Connection(named=named)
        assert run(connection,apply=True,repair_empty_invalid=True)==2
        assert not any(sql.startswith("DROP") for sql in connection.calls)
