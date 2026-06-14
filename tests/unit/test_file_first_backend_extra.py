import os

import pytest

from agent_memory_service.backends.file_first import FileFirstBackend, _append_text, _count_lines
from agent_memory_service.file_first.index_sqlite import SearchHit


def _make_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MEMORY_FILE_ROOT", str(tmp_path))
    return FileFirstBackend(service_config={})


def test_append_and_count_lines(tmp_path):
    path = tmp_path / "file.md"
    assert _count_lines(path) == 1
    line_start = _append_text(path, "hello")
    assert line_start == 1
    assert _count_lines(path) == 2


def test_write_search_get_rebuild(monkeypatch, tmp_path):
    backend = _make_backend(tmp_path, monkeypatch)
    tenant_id = "t"
    workspace_id = "w"

    write = backend.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "semantic",
            "scope": "project",
            "content": "hello world",
            "metadata": {"id": "x1"},
            "target": "daily",
        },
    )
    assert write["path"].endswith(".md")

    search = backend.search_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={"query": "hello", "top_k": 5},
    )
    assert search["hits"]

    get = backend.get_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={"path": write["path"], "start_line": 1, "max_lines": 2},
    )
    assert "hello" in get["content"]

    monkeypatch.setenv("AGENT_MEMORY_INDEX_REBUILD_ENABLED", "1")
    rebuilt = backend.rebuild_index(tenant_id=tenant_id, workspace_id=workspace_id)
    assert rebuilt["status"] == "success"


def test_write_preferences_and_wm(monkeypatch, tmp_path):
    backend = _make_backend(tmp_path, monkeypatch)
    tenant_id = "t"
    workspace_id = "w"

    pref = backend.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "preferences",
            "scope": "user",
            "content": "pref",
            "metadata": {"key": "lang"},
            "target": "preferences",
        },
    )
    assert pref["path"] == "preferences/_global/lang.md"

    wm = backend.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "wm",
            "scope": "task",
            "content": "",
            "metadata": {},
            "target": "wm",
            "task_id": "task1",
            "state": {"a": 1},
        },
    )
    assert wm["path"].endswith("wm/task1.md")


def test_wm_read_expires_ttl_state(monkeypatch, tmp_path):
    backend = _make_backend(tmp_path, monkeypatch)
    tenant_id = "t"
    workspace_id = "w"
    now = {"s": 1000.0}
    monkeypatch.setattr(
        "agent_memory_service.backends.file_first.time.time",
        lambda: now["s"],
    )

    wm = backend.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "wm",
            "scope": "task",
            "content": "",
            "metadata": {"ttl_s": 5},
            "target": "wm",
            "task_id": "task1",
            "state": {"a": 1},
        },
    )
    assert backend.read_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={"tier": "wm", "task_id": "task1"},
    ) == {"a": 1}

    now["s"] = 1006.0
    assert backend.read_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={"tier": "wm", "task_id": "task1"},
    ) is None
    ws = backend._ws_root(tenant_id=tenant_id, workspace_id=workspace_id)
    assert not (ws / wm["path"]).exists()


def test_graph_tier_is_separate_from_semantic_search(monkeypatch, tmp_path):
    backend = _make_backend(tmp_path, monkeypatch)
    tenant_id = "t"
    workspace_id = "w"

    backend.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "semantic",
            "scope": "project",
            "content": "Ralph uses pgvector for semantic memory",
            "metadata": {},
        },
    )
    graph = backend.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "graph",
            "scope": "project",
            "content": "",
            "metadata": {"subject": "Ralph", "relation": "uses", "obj": "Neo4j"},
        },
    )

    semantic = backend.search_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={"query": "Ralph uses", "top_k": 5, "tiers": ["semantic"]},
    )
    assert all(hit["tier"] == "semantic" for hit in semantic["hits"])

    graph_hits = backend.search_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "query": "Ralph uses",
            "top_k": 5,
            "tiers": ["graph"],
            "memory_kinds": ["kg_relation"],
            "path_prefixes": ["graph/relations/"],
        },
    )
    assert graph_hits["hits"][0]["path"] == graph["path"]
    assert graph_hits["hits"][0]["memory_kind"] == "kg_relation"


def test_search_rejects_bad_top_k(monkeypatch, tmp_path):
    backend = _make_backend(tmp_path, monkeypatch)
    with pytest.raises(Exception):
        backend.search_memory(
            tenant_id="t",
            workspace_id="w",
            payload={"query": "x", "top_k": 0},
        )


def test_search_uses_pgvector_backend_when_configured(monkeypatch, tmp_path):
    backend = _make_backend(tmp_path, monkeypatch)
    monkeypatch.setenv("AGENT_MEMORY_VECTOR_ENABLED", "1")
    monkeypatch.setenv("AGENT_MEMORY_VECTOR_BACKEND", "pgvector")
    monkeypatch.setattr(backend, "_embed_text", lambda _text: [1.0, 0.0, 0.0])

    class _FakePgIndex:
        closed = False

        def vector_search(self, **kwargs):
            assert kwargs["query_embedding"] == [1.0, 0.0, 0.0]
            return [
                SearchHit(
                    score=0.9,
                    snippet="vector only",
                    path="memory/vector.md",
                    line=1,
                    entry_id="v1",
                    tier="semantic",
                    scope="project",
                    created_at=None,
                    metadata={},
                )
            ]

        def close(self):
            self.closed = True

    monkeypatch.setattr(backend, "_pgvector_index", lambda **_kwargs: _FakePgIndex())

    result = backend.search_memory(
        tenant_id="t",
        workspace_id="w",
        payload={"query": "no matching fts text", "top_k": 5},
    )

    assert result["hits"][0]["path"] == "memory/vector.md"


def test_auto_rebuild_on_failure_recovers_from_corrupted_index(monkeypatch, tmp_path):
    backend = _make_backend(tmp_path, monkeypatch)
    tenant_id = "t"
    workspace_id = "w"

    backend.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "semantic",
            "scope": "project",
            "content": "hello world",
            "metadata": {"id": "x1"},
            "target": "daily",
        },
    )
    # Create index.
    assert backend.search_memory(
        tenant_id=tenant_id, workspace_id=workspace_id, payload={"query": "hello", "top_k": 5}
    )["hits"]

    ws = backend._ws_root(tenant_id=tenant_id, workspace_id=workspace_id)
    index_path = ws / ".index" / "index.sqlite"
    assert index_path.exists()
    index_path.write_bytes(b"corrupt")

    monkeypatch.setenv("AGENT_MEMORY_INDEX_AUTO_REBUILD_ON_FAILURE", "1")
    monkeypatch.setenv("AGENT_MEMORY_INDEX_AUTO_REBUILD_FAILURE_BACKOFF_S", "0")

    # Should auto heal and still return results.
    search = backend.search_memory(
        tenant_id=tenant_id, workspace_id=workspace_id, payload={"query": "hello", "top_k": 5}
    )
    assert search["hits"]


def test_auto_rebuild_on_stale_kicks_off_background_rebuild(monkeypatch, tmp_path):
    from agent_memory_service.backends import file_first as ff

    backend = _make_backend(tmp_path, monkeypatch)
    tenant_id = "t"
    workspace_id = "w"

    write = backend.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "semantic",
            "scope": "project",
            "content": "hello world",
            "metadata": {"id": "x1"},
            "target": "daily",
        },
    )
    # Create index.
    backend.search_memory(
        tenant_id=tenant_id, workspace_id=workspace_id, payload={"query": "hello", "top_k": 5}
    )

    ws = backend._ws_root(tenant_id=tenant_id, workspace_id=workspace_id)
    touched = ws / write["path"]
    assert touched.exists()
    # Simulate manual edit after index mtime.
    now = float(os.path.getmtime(str(touched))) + 10.0
    os.utime(touched, (now, now))

    monkeypatch.setenv("AGENT_MEMORY_INDEX_AUTO_REBUILD_ON_STALE", "1")
    monkeypatch.setenv("AGENT_MEMORY_INDEX_AUTO_REBUILD_STALE_COOLDOWN_S", "0")
    monkeypatch.setenv("AGENT_MEMORY_INDEX_AUTO_REBUILD_STALE_CHECK_INTERVAL_S", "0")

    calls = {"n": 0}
    orig = backend._rebuild_index_from_workspace

    def _wrapped(*, ws_root):
        calls["n"] += 1
        return orig(ws_root=ws_root)

    monkeypatch.setattr(backend, "_rebuild_index_from_workspace", _wrapped)

    class _InlineThread:
        def __init__(self, target, name=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(ff.threading, "Thread", _InlineThread)

    backend.search_memory(
        tenant_id=tenant_id, workspace_id=workspace_id, payload={"query": "hello", "top_k": 5}
    )
    assert calls["n"] >= 1
