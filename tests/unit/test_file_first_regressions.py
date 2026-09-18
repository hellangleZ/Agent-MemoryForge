import os

import pytest
from fastapi import HTTPException

from agent_memory_service.backends.file_first import FileFirstBackend


def _make_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MEMORY_FILE_ROOT", str(tmp_path))
    return FileFirstBackend(service_config={})


def test_get_memory_zero_start_line_is_rejected(tmp_path, monkeypatch):
    b = _make_backend(tmp_path, monkeypatch)
    b.write_memory(
        tenant_id="t", workspace_id="w",
        payload={"tier": "semantic", "scope": "project", "content": "a\nb\nc"},
    )
    hit = b.search_memory(tenant_id="t", workspace_id="w", payload={"query": "a"})["hits"][0]
    with pytest.raises(HTTPException):
        b.get_memory(tenant_id="t", workspace_id="w", payload={"path": hit["path"], "start_line": 0})


def test_stm_empty_content_is_rejected(tmp_path, monkeypatch):
    b = _make_backend(tmp_path, monkeypatch)
    with pytest.raises(HTTPException):
        b.write_memory(
            tenant_id="t", workspace_id="w",
            payload={"tier": "stm", "scope": "user", "content": "",
                     "conversation_id": "c1", "metadata": {"conversation_id": "c1"}},
        )


def test_wm_state_with_non_json_value_is_serializable(tmp_path, monkeypatch):
    import datetime
    b = _make_backend(tmp_path, monkeypatch)
    res = b.write_memory(
        tenant_id="t", workspace_id="w",
        payload={"tier": "wm", "scope": "user",
                 "metadata": {"task_id": "task1", "user_id": "u1",
                                "state": {"when": datetime.datetime(2026, 1, 1)}}},
    )
    assert res["path"] == "wm/task1.md"


def test_search_index_not_stale_matches_auto_rebuild_rule(tmp_path, monkeypatch):
    b = _make_backend(tmp_path, monkeypatch)
    b.write_memory(
        tenant_id="t", workspace_id="w",
        payload={"tier": "semantic", "scope": "project", "content": "hello world"},
    )
    stats = b.stats(tenant_id="t", workspace_id="w")
    assert stats["file_first"]["index"]["stale"] is False
