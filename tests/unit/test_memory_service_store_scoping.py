from unittest.mock import MagicMock

from agent_memory_framework.adapters.memory_service import MemoryServiceStore
from agent_memory_framework.memory import (
    MemoryQuery,
    MemoryRecord,
    MemoryRef,
    MemoryScope,
    MemoryTier,
)


def test_memory_service_store_prefixes_ids():
    client = MagicMock()
    store = MemoryServiceStore(client=client)
    ref = MemoryRef(
        tenant_id="t1", workspace_id="ws1", scope=MemoryScope.user, user_id="u"
    )

    store.store(
        MemoryRecord(
            tier=MemoryTier.stm,
            ref=ref,
            content="s",
            metadata={"conversation_id": "c1", "round_id": 1},
        )
    )

    call = client.store_stm.call_args.kwargs
    assert call["conversation_id"].startswith("t:t1:ws:ws1:")

    store.store(
        MemoryRecord(
            tier=MemoryTier.wm,
            ref=ref,
            content="",
            metadata={"task_id": "task1", "state": {"x": 1}},
        )
    )
    call = client.store_wm.call_args.kwargs
    assert call["task_id"].startswith("t:t1:ws:ws1:")


def test_memory_service_retrieve_prefixes_ids():
    client = MagicMock()
    client.retrieve_stm.return_value = {"status": "success", "data": []}
    client.retrieve_wm.return_value = {"status": "success", "data": None}

    store = MemoryServiceStore(client=client)
    ref = MemoryRef(
        tenant_id="t1", workspace_id="ws1", scope=MemoryScope.user, user_id="u"
    )

    store.retrieve(MemoryQuery(tier=MemoryTier.stm, ref=ref, query="c1", top_k=5))
    assert client.retrieve_stm.call_args.kwargs["conversation_id"].startswith(
        "t:t1:ws:ws1:"
    )

    store.retrieve(MemoryQuery(tier=MemoryTier.wm, ref=ref, query="task1", top_k=5))
    assert client.retrieve_wm.call_args.kwargs["task_id"].startswith("t:t1:ws:ws1:")
