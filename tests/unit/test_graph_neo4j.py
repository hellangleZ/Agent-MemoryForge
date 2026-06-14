
from agent_memory_service.derived import graph_neo4j


def test_graph_enabled_parses_env(monkeypatch):
    monkeypatch.delenv("AGENT_MEMORY_GRAPH_ENABLED", raising=False)
    assert graph_neo4j.graph_enabled() is False
    monkeypatch.setenv("AGENT_MEMORY_GRAPH_ENABLED", "true")
    assert graph_neo4j.graph_enabled() is True


def test_validated_edge_filters_invalid():
    edge = graph_neo4j.GraphEdge(
        tenant_id="t",
        workspace_id="w",
        scope="s",
        subject="",
        relation="rel",
        obj="obj",
        entry_id="e",
        source_path="path.md",
        source_line=1,
    )
    assert graph_neo4j._validated_edge(edge) is None


def test_validated_edge_normalizes():
    edge = graph_neo4j.GraphEdge(
        tenant_id="t",
        workspace_id="w",
        scope="s",
        subject=" a ",
        relation="rel",
        obj="obj",
        entry_id="e",
        source_path="path.md",
        source_line=1,
    )
    validated = graph_neo4j._validated_edge(edge)
    assert validated is not None
    assert validated.subject == "a"


def test_rel_id_is_deterministic():
    edge = graph_neo4j.GraphEdge(
        tenant_id="t",
        workspace_id="w",
        scope="s",
        subject="a",
        relation="r",
        obj="b",
        entry_id="e",
        source_path="path.md",
        source_line=1,
    )
    assert graph_neo4j._rel_id(edge) == graph_neo4j._rel_id(edge)


def test_best_effort_upsert_skips_when_disabled(monkeypatch):
    monkeypatch.delenv("AGENT_MEMORY_GRAPH_ENABLED", raising=False)
    edge = graph_neo4j.GraphEdge(
        tenant_id="t",
        workspace_id="w",
        scope="s",
        subject="a",
        relation="r",
        obj="b",
        entry_id="e",
        source_path="path.md",
        source_line=1,
    )
    graph_neo4j.best_effort_upsert(cfg={}, edge=edge)


def test_best_effort_upsert_missing_config(monkeypatch):
    monkeypatch.setenv("AGENT_MEMORY_GRAPH_ENABLED", "1")
    edge = graph_neo4j.GraphEdge(
        tenant_id="t",
        workspace_id="w",
        scope="s",
        subject="a",
        relation="r",
        obj="b",
        entry_id="e",
        source_path="path.md",
        source_line=1,
    )
    graph_neo4j.best_effort_upsert(cfg={}, edge=edge)
