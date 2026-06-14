def test_removed_memory_routes_are_not_registered():
    from agent_memory_service.app import create_app

    app = create_app()
    paths = {getattr(r, "path", None) for r in app.router.routes}
    assert "/store" not in paths
    assert "/retrieve" not in paths
    assert "/clear" not in paths


def test_memory_service_adapter_refuses_when_scoping_disabled(monkeypatch):
    monkeypatch.setenv("AGENT_MEMORY_ENABLE_SCOPING", "0")

    from agent_memory_framework.adapters.memory_service import MemoryServiceStore
    from agent_memory_framework.memory import (
        MemoryQuery,
        MemoryRecord,
        MemoryRef,
        MemoryScope,
        MemoryTier,
    )

    store = MemoryServiceStore(client=None)  # type: ignore[arg-type]
    ref = MemoryRef(
        tenant_id="t", workspace_id="ws", scope=MemoryScope.user, user_id="u"
    )

    try:
        store.store(MemoryRecord(tier=MemoryTier.semantic, ref=ref, content="x"))
        assert False, "expected error"
    except RuntimeError as exc:
        assert "Memory scoping is disabled" in str(exc)

    try:
        store.retrieve(MemoryQuery(tier=MemoryTier.semantic, ref=ref, query="q"))
        assert False, "expected error"
    except RuntimeError as exc:
        assert "Memory scoping is disabled" in str(exc)
