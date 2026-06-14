from agent_memory_service.file_first.index_pgvector import PgVectorIndex, _vector_literal


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.conn.calls.append((sql, params))
        if sql.strip().startswith("DELETE"):
            self.rowcount = 1

    def fetchall(self):
        return [
            (
                "memory/2026-01-01.md",
                3,
                "e1",
                "semantic",
                "project",
                "2026-01-01T00:00:00Z",
                {"source": "unit"},
                "hello",
                0.875,
            )
        ]


class _Connection:
    def __init__(self):
        self.calls = []
        self.rollback_count = 0

    def cursor(self):
        return _Cursor(self)

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        pass


def test_vector_literal_rejects_non_finite_values():
    assert _vector_literal([1, 0.25, -2]) == "[1,0.25,-2]"


def test_pgvector_search_orders_by_pgvector_operator_with_scoped_params():
    conn = _Connection()
    index = PgVectorIndex(
        dsn="postgresql://example/db",
        tenant_id="t1",
        workspace_id="w1",
        dim=3,
        connection=conn,
    )
    conn.calls.clear()

    hits = index.vector_search(
        query_embedding=[1, 0, 0],
        top_k=2,
        tiers=["semantic"],
        scopes=["project"],
    )

    sql, params = conn.calls[-1]
    assert "embedding <=>" in sql
    assert params == ("[1,0,0]", "t1", "w1", ["semantic"], ["project"], "[1,0,0]", 2)
    assert hits[0].score == 0.875


def test_pgvector_insert_binds_line_start_before_embedding():
    conn = _Connection()
    index = PgVectorIndex(
        dsn="postgresql://example/db",
        tenant_id="t1",
        workspace_id="w1",
        dim=3,
        connection=conn,
    )
    conn.calls.clear()

    index.insert_vector(
        path="memory/2026-01-01.md",
        entry_id="e1",
        tier="semantic",
        scope="project",
        memory_kind="fact",
        created_at="2026-01-01T00:00:00Z",
        line_start=7,
        content="hello",
        metadata={"source": "unit"},
        embedding=[1, 0, 0],
    )

    sql, params = conn.calls[-1]
    assert sql.count("%s") == len(params)
    assert params[8] == 7
    assert params[9] == "[1,0,0]"
