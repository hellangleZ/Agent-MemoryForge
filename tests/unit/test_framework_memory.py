import pytest

from agent_memory_framework.adapters.memory_service import MemoryServiceStore
from agent_memory_framework.memory import (
    MemoryQuery,
    MemoryRecord,
    MemoryRef,
    MemoryScope,
    MemoryTier,
)


class DummyMemoryClient:
    def __init__(self):
        self.calls = []

    def memory_write(self, **kwargs):
        self.calls.append(("memory_write", kwargs))
        return {"status": "success", "data": {"entry_id": "rec_1"}}

    def memory_search(self, **kwargs):
        self.calls.append(("memory_search", kwargs))
        return {
            "status": "success",
            "data": {"hits": [{"entry_id": "rec_2", "snippet": "hello", "score": 0.7}]},
        }

    def store_ltm_preference(self, user_id, key, value):
        self.calls.append(("store_ltm_preference", user_id, key, value))
        return {"status": "success"}

    def retrieve_ltm_preference(self, user_id, key):
        self.calls.append(("retrieve_ltm_preference", user_id, key))
        return "dark"

    def store_stm(self, conversation_id, round_id, summary):
        self.calls.append(("store_stm", conversation_id, round_id, summary))
        return {"status": "success"}

    def retrieve_stm(self, conversation_id, last_k):
        self.calls.append(("retrieve_stm", conversation_id, last_k))
        return {"status": "success", "data": [{"round_id": 1, "summary": "sum"}]}

    def store_wm(self, user_id, task_id, state):
        self.calls.append(("store_wm", user_id, task_id, state))
        return {"status": "success"}

    def retrieve_wm(self, user_id, task_id):
        self.calls.append(("retrieve_wm", user_id, task_id))
        return {"status": "success", "data": {"phase": "p1"}}


def test_memory_store_retrieve_injects_tenant_workspace_scope():
    client = DummyMemoryClient()
    store = MemoryServiceStore(client=client)

    ref = MemoryRef(
        tenant_id="t1", workspace_id="ws1", scope=MemoryScope.user, user_id="u1"
    )
    query = MemoryQuery(tier=MemoryTier.semantic, ref=ref, query="frontend", top_k=3)
    records = store.retrieve(query)

    assert len(records) == 1
    assert records[0].ref.tenant_id == "t1"
    assert records[0].ref.workspace_id == "ws1"

    method, kwargs = client.calls[0]
    assert method == "memory_search"
    assert kwargs["tenant_id"] == "t1"
    assert kwargs["workspace_id"] == "ws1"
    assert kwargs["scopes"] == ["user"]
    assert kwargs["tiers"] == ["semantic"]


def test_memory_store_preferences_round_trip():
    client = DummyMemoryClient()
    store = MemoryServiceStore(client=client)

    ref = MemoryRef(
        tenant_id="t1", workspace_id="ws1", scope=MemoryScope.user, user_id="u1"
    )
    stored = store.store(
        MemoryRecord(
            tier=MemoryTier.preferences,
            ref=ref,
            content="",
            metadata={"key": "theme", "value": "dark"},
        )
    )
    assert stored.tier is MemoryTier.preferences
    assert client.calls[0][0] == "store_ltm_preference"

    retrieved = store.retrieve(
        MemoryQuery(tier=MemoryTier.preferences, ref=ref, query="theme")
    )
    assert len(retrieved) == 1
    assert retrieved[0].metadata["key"] == "theme"
    assert retrieved[0].metadata["value"] == "dark"
    assert client.calls[1][0] == "retrieve_ltm_preference"


def test_memory_store_stm_requires_conversation_id_and_round_id():
    client = DummyMemoryClient()
    store = MemoryServiceStore(client=client)
    ref = MemoryRef(
        tenant_id="t1", workspace_id="ws1", scope=MemoryScope.user, user_id="u1"
    )

    with pytest.raises(ValueError):
        store.store(
            MemoryRecord(
                tier=MemoryTier.stm,
                ref=ref,
                content="summary",
                metadata={"round_id": 1},
            )
        )
