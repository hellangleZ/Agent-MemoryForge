import pytest
from fastapi import HTTPException


def _skip_if_fts5_missing() -> None:
    try:
        import sqlite3

        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE t USING fts5(content);")
        finally:
            conn.close()
    except Exception:
        pytest.skip("SQLite FTS5 not available in this environment")


@pytest.mark.unit
def test_file_first_write_search_get_roundtrip(tmp_path, monkeypatch) -> None:
    _skip_if_fts5_missing()
    monkeypatch.setenv("AGENT_MEMORY_BACKEND", "file_first")
    monkeypatch.setenv("AGENT_MEMORY_FILE_ROOT", str(tmp_path))

    from agent_memory_service.app import (
        FileFirstGetRequest,
        FileFirstSearchRequest,
        FileFirstWriteRequest,
        create_app,
    )

    app = create_app()
    write_endpoint = next(
        r.endpoint
        for r in app.router.routes
        if getattr(r, "path", None) == "/v1/memory/write"
    )
    search_endpoint = next(
        r.endpoint
        for r in app.router.routes
        if getattr(r, "path", None) == "/v1/memory/search"
    )
    get_endpoint = next(
        r.endpoint
        for r in app.router.routes
        if getattr(r, "path", None) == "/v1/memory/get"
    )

    tenant_id = "t1"
    workspace_id = "ws1"
    content = "We decided to make Markdown the source of truth (File-First)."

    write_res = write_endpoint(
        FileFirstWriteRequest(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            tier="semantic",
            scope="project",
            content=content,
            metadata={"tags": ["decision"], "source": "unit_test"},
            target="daily",
        )
    )
    path = write_res["data"]["path"]
    assert path.endswith(".md")
    from agent_memory_service.file_first.paths import workspace_root

    assert (
        workspace_root(tenant_id=tenant_id, workspace_id=workspace_id) / path
    ).exists()

    search_res = search_endpoint(
        FileFirstSearchRequest(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            query="source of truth",
            top_k=5,
        )
    )
    hits = search_res["data"]["hits"]
    assert hits
    assert any(h.get("path") == path for h in hits)

    get_res = get_endpoint(
        FileFirstGetRequest(tenant_id=tenant_id, workspace_id=workspace_id, path=path)
    )
    text = get_res["data"]["content"]
    assert "<!-- am:entry" in text
    assert content in text


@pytest.mark.unit
def test_file_first_search_falls_back_to_identifier_and_cleans_metadata_snippets(
    tmp_path, monkeypatch
) -> None:
    _skip_if_fts5_missing()
    monkeypatch.setenv("AGENT_MEMORY_BACKEND", "file_first")
    monkeypatch.setenv("AGENT_MEMORY_FILE_ROOT", str(tmp_path))
    monkeypatch.setenv("AGENT_MEMORY_VECTOR_ENABLED", "0")

    from agent_memory_service.orchestrator import MemoryOrchestrator

    orch = MemoryOrchestrator()
    tenant_id = "t1"
    workspace_id = "ws1"
    for content, tags in [
        (
            "finance_mrr must be refreshed daily by 09:00 Asia/Shanghai.",
            ["finance_mrr", "SLA"],
        ),
        ("The owner of finance_mrr is Alice.", ["finance_mrr", "owner"]),
        (
            "finance_mrr depends on raw_invoices and raw_payments as upstream inputs.",
            ["finance_mrr", "dependencies", "upstream"],
        ),
    ]:
        orch.write_memory(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            payload={
                "tier": "semantic",
                "scope": "project",
                "content": content,
                "metadata": {"tags": tags, "source": "unit_test"},
            },
        )

    entity_hits = orch.search_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "query": "finance_mrr",
            "top_k": 5,
            "tiers": ["semantic"],
            "scopes": ["project"],
        },
    )["hits"]
    entity_text = "\n".join(str(hit.get("snippet") or "") for hit in entity_hits)
    assert "09:00 Asia/Shanghai" in entity_text
    assert "The owner of finance_mrr is Alice" in entity_text
    assert "raw_invoices" in entity_text

    natural_hits = orch.search_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "query": "请从长期记忆里回答：finance_mrr 的刷新 SLA、owner、上游依赖是什么？",
            "top_k": 5,
            "tiers": ["semantic"],
            "scopes": ["project"],
        },
    )["hits"]
    natural_text = "\n".join(str(hit.get("snippet") or "") for hit in natural_hits)
    assert "09:00 Asia/Shanghai" in natural_text
    assert "Alice" in natural_text
    assert "raw_payments" in natural_text


@pytest.mark.unit
def test_file_first_search_logs_structured_recall_without_raw_query(
    tmp_path, monkeypatch, caplog
) -> None:
    _skip_if_fts5_missing()
    monkeypatch.setenv("AGENT_MEMORY_BACKEND", "file_first")
    monkeypatch.setenv("AGENT_MEMORY_FILE_ROOT", str(tmp_path))
    monkeypatch.setenv("AGENT_MEMORY_VECTOR_ENABLED", "0")

    from agent_memory_service.orchestrator import MemoryOrchestrator

    orch = MemoryOrchestrator()
    orch.write_memory(
        tenant_id="t1",
        workspace_id="ws1",
        payload={
            "tier": "semantic",
            "scope": "project",
            "content": "finance_mrr must be refreshed daily by 09:00 Asia/Shanghai.",
            "metadata": {"tags": ["finance_mrr"], "source": "unit_test"},
        },
    )

    raw_query = "raw-query-marker finance_mrr"
    caplog.set_level("INFO", logger="agent_memory_service.backends.file_first")
    orch.search_memory(
        tenant_id="t1",
        workspace_id="ws1",
        payload={
            "query": raw_query,
            "top_k": 5,
            "tiers": ["semantic"],
            "scopes": ["project"],
        },
    )

    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "agent_memory.event" in logs
    assert '"event": "memory.search"' in logs
    assert "query_sha256" in logs
    assert raw_query not in logs


@pytest.mark.unit
def test_file_first_get_rejects_traversal(tmp_path, monkeypatch) -> None:
    _skip_if_fts5_missing()
    monkeypatch.setenv("AGENT_MEMORY_BACKEND", "file_first")
    monkeypatch.setenv("AGENT_MEMORY_FILE_ROOT", str(tmp_path))

    from agent_memory_service.app import FileFirstGetRequest, create_app

    app = create_app()
    get_endpoint = next(
        r.endpoint
        for r in app.router.routes
        if getattr(r, "path", None) == "/v1/memory/get"
    )

    with pytest.raises(HTTPException) as exc:
        get_endpoint(
            FileFirstGetRequest(
                tenant_id="t1",
                workspace_id="ws1",
                path="../secrets.md",
                start_line=1,
                max_lines=10,
            )
        )
    assert exc.value.status_code == 422


@pytest.mark.unit
def test_file_first_tenant_workspace_isolation(tmp_path, monkeypatch) -> None:
    _skip_if_fts5_missing()
    monkeypatch.setenv("AGENT_MEMORY_BACKEND", "file_first")
    monkeypatch.setenv("AGENT_MEMORY_FILE_ROOT", str(tmp_path))

    from agent_memory_service.app import (
        FileFirstSearchRequest,
        FileFirstWriteRequest,
        create_app,
    )

    app = create_app()
    write_endpoint = next(
        r.endpoint
        for r in app.router.routes
        if getattr(r, "path", None) == "/v1/memory/write"
    )
    search_endpoint = next(
        r.endpoint
        for r in app.router.routes
        if getattr(r, "path", None) == "/v1/memory/search"
    )

    write_endpoint(
        FileFirstWriteRequest(
            tenant_id="t1",
            workspace_id="ws1",
            tier="semantic",
            scope="project",
            content="Tenant-scoped memory entry",
            target="daily",
        )
    )

    res_other = search_endpoint(
        FileFirstSearchRequest(
            tenant_id="t2",
            workspace_id="ws2",
            query="Tenant-scoped",
            top_k=5,
        )
    )
    assert res_other["data"]["hits"] == []


@pytest.mark.unit
def test_workspace_root_uses_collision_resistant_scope(monkeypatch, tmp_path) -> None:
    from agent_memory_service.file_first.paths import workspace_root

    monkeypatch.setenv("AGENT_MEMORY_FILE_ROOT", str(tmp_path))

    first = workspace_root(tenant_id="a/b", workspace_id="ws")
    second = workspace_root(tenant_id="a_b", workspace_id="ws")

    assert first != second
    assert first.parent == tmp_path
    assert second.parent == tmp_path


@pytest.mark.unit
def test_canonical_write_read_wm_and_preferences(tmp_path, monkeypatch) -> None:
    _skip_if_fts5_missing()
    monkeypatch.setenv("AGENT_MEMORY_BACKEND", "file_first")
    monkeypatch.setenv("AGENT_MEMORY_FILE_ROOT", str(tmp_path))

    from agent_memory_service.orchestrator import MemoryOrchestrator

    orch = MemoryOrchestrator()

    orch.write_memory(
        tenant_id="t1",
        workspace_id="ws1",
        payload={
            "tier": "wm",
            "scope": "user",
            "task_id": "task_1",
            "state": {"a": 1},
        },
    )
    wm = orch.read_memory(
        tenant_id="t1", workspace_id="ws1", payload={"tier": "wm", "task_id": "task_1"}
    )
    assert wm == {"a": 1}

    orch.write_memory(
        tenant_id="t1",
        workspace_id="ws1",
        payload={
            "tier": "preferences",
            "scope": "user",
            "user_id": "u1",
            "key": "preferred_name",
            "value": "Ralph",
        },
    )
    pref = orch.read_memory(
        tenant_id="t1",
        workspace_id="ws1",
        payload={"tier": "preferences", "user_id": "u1", "key": "preferred_name"},
    )
    assert pref == "Ralph"
    from agent_memory_service.file_first.paths import workspace_root

    assert (
        workspace_root(tenant_id="t1", workspace_id="ws1")
        / "preferences"
        / "u1"
        / "preferred_name.md"
    ).exists()

    all_prefs = orch.read_memory(
        tenant_id="t1",
        workspace_id="ws1",
        payload={"tier": "preferences", "user_id": "u1"},
    )
    assert all_prefs == {"preferred_name": "Ralph"}


@pytest.mark.unit
def test_private_memory_is_filtered_by_actor(tmp_path, monkeypatch) -> None:
    _skip_if_fts5_missing()
    monkeypatch.setenv("AGENT_MEMORY_BACKEND", "file_first")
    monkeypatch.setenv("AGENT_MEMORY_FILE_ROOT", str(tmp_path))

    from agent_memory_service.orchestrator import MemoryOrchestrator

    orch = MemoryOrchestrator()
    tenant_id = "t1"
    workspace_id = "ws1"

    pref = orch.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "preferences",
            "scope": "user",
            "user_id": "alice",
            "key": "timezone",
            "value": "Asia/Shanghai",
        },
    )
    stm = orch.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "stm",
            "scope": "user",
            "conversation_id": "conv_alice",
            "content": "Alice private conversation summary",
            "metadata": {
                "user_id": "alice",
                "conversation_id": "conv_alice",
                "stm_summary": {"final_answer": "Alice private conversation summary"},
            },
        },
    )
    wm = orch.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "wm",
            "scope": "user",
            "task_id": "task_alice",
            "metadata": {
                "user_id": "alice",
                "task_id": "task_alice",
                "state": {"a": 1},
            },
        },
    )

    bob = {"actor_user_id": "bob", "actor_role": "user"}
    bob_search = orch.search_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={"query": "Alice private", "top_k": 10, "tiers": ["stm"], **bob},
    )
    assert bob_search["hits"] == []

    with pytest.raises(HTTPException) as pref_get:
        orch.get_memory(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            payload={"path": pref["path"], **bob},
        )
    assert pref_get.value.status_code == 403

    with pytest.raises(HTTPException) as stm_get:
        orch.get_memory(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            payload={"path": stm["path"], **bob},
        )
    assert stm_get.value.status_code == 403

    with pytest.raises(HTTPException) as wm_read:
        orch.read_memory(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            payload={"tier": "wm", "task_id": "task_alice", **bob},
        )
    assert wm_read.value.status_code == 403

    alice = {"actor_user_id": "alice", "actor_role": "user"}
    assert orch.get_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={"path": pref["path"], **alice},
    )["content"]
    assert orch.get_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={"path": stm["path"], **alice},
    )["content"]
    assert orch.read_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={"tier": "wm", "task_id": "task_alice", **alice},
    ) == {"a": 1}
    assert wm["path"] == "wm/task_alice.md"


@pytest.mark.unit
def test_file_first_search_returns_503_when_index_corrupt(
    tmp_path, monkeypatch
) -> None:
    _skip_if_fts5_missing()
    monkeypatch.setenv("AGENT_MEMORY_BACKEND", "file_first")
    monkeypatch.setenv("AGENT_MEMORY_FILE_ROOT", str(tmp_path))

    from agent_memory_service.app import (
        FileFirstSearchRequest,
        FileFirstWriteRequest,
        create_app,
    )

    app = create_app()
    write_endpoint = next(
        r.endpoint
        for r in app.router.routes
        if getattr(r, "path", None) == "/v1/memory/write"
    )
    search_endpoint = next(
        r.endpoint
        for r in app.router.routes
        if getattr(r, "path", None) == "/v1/memory/search"
    )

    tenant_id = "t1"
    workspace_id = "ws1"
    from agent_memory_service.file_first.paths import workspace_root

    ws_root = workspace_root(tenant_id=tenant_id, workspace_id=workspace_id)
    (ws_root / ".index").mkdir(parents=True, exist_ok=True)
    (ws_root / ".index" / "index.sqlite").write_bytes(b"not a sqlite database")

    write_res = write_endpoint(
        FileFirstWriteRequest(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            tier="semantic",
            scope="project",
            content="Index corruption should not block Markdown writes.",
            target="daily",
        )
    )
    assert write_res["status"] == "success"

    with pytest.raises(HTTPException) as exc:
        search_endpoint(
            FileFirstSearchRequest(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                query="block Markdown writes",
                top_k=5,
            )
        )
    assert exc.value.status_code == 503
