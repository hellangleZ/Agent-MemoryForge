from __future__ import annotations


from agent_memory_framework.feature_flags import (
    enable_parallel,
    enable_scoping,
    parallel_workers,
)


def test_feature_flags_defaults(monkeypatch):
    monkeypatch.delenv("AGENT_MEMORY_ENABLE_PARALLEL", raising=False)
    monkeypatch.delenv("AGENT_MEMORY_ENABLE_SCOPING", raising=False)
    monkeypatch.delenv("AGENT_MEMORY_PARALLEL_WORKERS", raising=False)

    assert enable_parallel(default=True) is True
    assert enable_scoping(default=True) is True
    assert parallel_workers(default=None) is None


def test_feature_flags_parse(monkeypatch):
    monkeypatch.setenv("AGENT_MEMORY_ENABLE_PARALLEL", "0")
    monkeypatch.setenv("AGENT_MEMORY_ENABLE_SCOPING", "false")
    monkeypatch.setenv("AGENT_MEMORY_PARALLEL_WORKERS", "3")
    assert enable_parallel(default=True) is False
    assert enable_scoping(default=True) is False
    assert parallel_workers(default=None) == 3


def test_parallel_workers_invalid(monkeypatch):
    monkeypatch.setenv("AGENT_MEMORY_PARALLEL_WORKERS", "0")
    assert parallel_workers(default=None) is None
    monkeypatch.setenv("AGENT_MEMORY_PARALLEL_WORKERS", "-1")
    assert parallel_workers(default=None) is None
    monkeypatch.setenv("AGENT_MEMORY_PARALLEL_WORKERS", "nope")
    assert parallel_workers(default=None) is None
