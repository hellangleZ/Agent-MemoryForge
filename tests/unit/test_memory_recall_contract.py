from typing import Any, Dict, List, Optional

from agent_memory_framework.memory_runtime.context_builder import ContextBuilder
from agent_memory_framework.memory_runtime.memory_manager import MemoryManager
from agent_memory_lib.client import MemoryClient


class _FakeMemoryClient:
    def __init__(self) -> None:
        self.search_calls: List[Dict[str, Any]] = []
        self.read_calls: List[Dict[str, Any]] = []

    def memory_read(self, **kwargs):
        self.read_calls.append(kwargs)
        tier = kwargs.get("tier")
        if tier == "preferences":
            user_id = kwargs.get("user_id")
            if user_id == "alice":
                return {
                    "status": "success",
                    "data": {
                        "language": "zh-CN",
                        "timezone": "Asia/Shanghai",
                        "answer_style": "短句、先结论",
                    },
                }
            if user_id == "bob":
                return {"status": "success", "data": {"language": "en-US", "timezone": "UTC"}}
            return {"status": "success", "data": {}}
        if tier == "stm":
            conv = kwargs.get("conversation_id")
            if conv == "conv_dw_1":
                return {
                    "status": "success",
                    "data": [
                        {
                            "round_id": 1,
                            "summary": "上一轮我们在排查 finance_mrr freshness，已确认用户关心 SLA、owner 和上游依赖。",
                        }
                    ],
                }
            return {"status": "success", "data": []}
        return {"status": "success", "data": None}

    def memory_search(self, **kwargs):
        self.search_calls.append(kwargs)
        query = kwargs.get("query")
        tier = (kwargs.get("tiers") or [""])[0]
        if query == "finance_mrr" and tier == "semantic":
            return {
                "status": "success",
                "data": {
                    "hits": [
                        {
                            "snippet": "finance_mrr 的刷新 SLA 是每天 09:00 Asia/Shanghai 前完成，owner 是 Alice。",
                            "path": "memory/dw.md",
                            "line": 8,
                        }
                    ]
                },
            }
        if query == "finance_mrr" and tier == "graph":
            return {
                "status": "success",
                "data": {
                    "hits": [
                        {"snippet": "finance_mrr -[depends_on]-> raw_invoices"},
                        {"snippet": "finance_mrr -[depends_on]-> raw_payments"},
                    ]
                },
            }
        return {"status": "success", "data": {"hits": []}}

    def retrieve_wm(self, user_id: str, task_id: str):
        if user_id == "alice" and task_id == "conv_dw_1":
            return {
                "status": "success",
                "data": {
                    "status": "active",
                    "goal": "完成 finance_mrr freshness 问题定位",
                    "steps": [
                        {"id": "1", "text": "确认 SLA", "status": "done"},
                        {"id": "2", "text": "检查 raw_invoices 延迟", "status": "doing"},
                        {"id": "3", "text": "输出修复建议", "status": "todo"},
                    ],
                },
            }
        if user_id == "alice" and task_id == "old_task":
            return {"status": "success", "data": {"status": "done", "goal": "旧任务，不应进入 context"}}
        return {"status": "success", "data": None}

    def list_ltm_preferences(self, user_id: str, limit: int = 50):
        if user_id == "alice":
            return {
                "status": "success",
                "data": {
                    "language": "zh-CN",
                    "timezone": "Asia/Shanghai",
                    "answer_style": "短句、先结论",
                },
            }
        if user_id == "bob":
            return {"status": "success", "data": {"language": "en-US", "timezone": "UTC"}}
        return {"status": "success", "data": {}}

    def retrieve_stm(self, conversation_id: str, last_k: int = 15):
        return self.memory_read(tier="stm", conversation_id=conversation_id, limit=last_k)


def _sdk_context(
    *,
    client: Optional[MemoryClient] = None,
    user_id: str = "alice",
    conversation_id: str = "conv_dw_1",
    query: str = "finance_mrr 的刷新 SLA 和上游依赖是什么？",
    **kwargs,
) -> str:
    client = client or MemoryClient("http://memory.example", tenant_id="tenant_acme", workspace_id="dw_ops")
    messages = client.build_context(
        query=query,
        user_id=user_id,
        conversation_id=conversation_id,
        **kwargs,
    )
    return "\n".join(str(message.get("content") or "") for message in messages)


def test_sdk_context_recalls_expected_preference_stm_semantic_and_graph(mocker):
    client = MemoryClient("http://memory.example", tenant_id="tenant_acme", workspace_id="dw_ops")
    fake = _FakeMemoryClient()
    mocker.patch.object(client, "memory_read", side_effect=fake.memory_read)
    mocker.patch.object(client, "memory_search", side_effect=fake.memory_search)

    content = _sdk_context(client=client)

    assert "## User Preferences" in content
    assert "answer_style: 短句、先结论" in content
    assert "## Recent Conversation Memory" in content
    assert "排查 finance_mrr freshness" in content
    assert "## Relevant Semantic Facts" in content
    assert "09:00 Asia/Shanghai" in content
    assert "## Knowledge Graph" in content
    assert "raw_invoices" in content
    assert "raw_payments" in content
    assert "memory/dw.md" not in content
    assert "score" not in content.lower()
    assert "entry_id" not in content


def test_sdk_context_does_not_recall_other_user_preferences_or_other_conversation_stm(mocker):
    client = MemoryClient("http://memory.example", tenant_id="tenant_acme", workspace_id="dw_ops")
    fake = _FakeMemoryClient()
    mocker.patch.object(client, "memory_read", side_effect=fake.memory_read)
    mocker.patch.object(client, "memory_search", side_effect=fake.memory_search)

    content = _sdk_context(
        client=client,
        user_id="bob",
        conversation_id="conv_new",
        query="finance_mrr 的刷新 SLA 是什么？",
    )

    assert "language: en-US" in content
    assert "timezone: UTC" in content
    assert "短句、先结论" not in content
    assert "排查 finance_mrr freshness" not in content
    assert "09:00 Asia/Shanghai" in content


def test_sdk_context_uses_identifier_fallback_but_limits_backend_searches(mocker):
    client = MemoryClient("http://memory.example", tenant_id="tenant_acme", workspace_id="dw_ops")
    fake = _FakeMemoryClient()
    mocker.patch.object(client, "memory_read", side_effect=fake.memory_read)
    search = mocker.patch.object(client, "memory_search", side_effect=fake.memory_search)

    content = _sdk_context(
        client=client,
        query="我现在这个 Northstar DW Ops 里，finance_mrr 的 freshness SLA 是什么？它上游依赖什么？",
        include_preferences=False,
        include_stm=False,
        max_search_queries=2,
    )

    queries = [call.kwargs["query"] for call in search.call_args_list]
    assert "finance_mrr" in queries
    assert len([q for q in queries if q]) <= 4
    assert "09:00 Asia/Shanghai" in content
    assert "raw_invoices" in content


def test_sdk_current_user_message_can_override_preference_without_mutating_memory(mocker):
    client = MemoryClient("http://memory.example", tenant_id="tenant_acme", workspace_id="dw_ops")
    fake = _FakeMemoryClient()
    mocker.patch.object(client, "memory_read", side_effect=fake.memory_read)
    mocker.patch.object(client, "memory_search", side_effect=fake.memory_search)

    content = _sdk_context(
        client=client,
        query="Use English and give me a long detailed explanation of finance_mrr SLA.",
        user_id="alice",
        conversation_id="conv_new",
    )

    assert "Prefer the user's current message if it conflicts with memory" in content
    assert "language: zh-CN" in content
    read_calls = [call for call in fake.read_calls if call.get("tier") == "preferences"]
    assert read_calls == [{"tier": "preferences", "user_id": "alice", "limit": 50}]


class _ManagerClient(_FakeMemoryClient):
    def __init__(self, *, wm_task_id: str) -> None:
        super().__init__()
        self.wm_task_id = wm_task_id

    def retrieve_wm(self, user_id: str, task_id: str):
        return super().retrieve_wm(user_id=user_id, task_id=self.wm_task_id)


def _reference_context(*, wm_task_id: str = "conv_dw_1", query: str = "继续这个任务，下一步做什么？") -> str:
    memory_client = _ManagerClient(wm_task_id=wm_task_id)
    manager = MemoryManager(
        memory_client=memory_client,
        user_id="alice",
        conversation_id="conv_dw_1",
        config={"stm_max_summaries": 2, "semantic_top_k": 3},
    )
    builder = ContextBuilder(memory_manager=manager, config={"stm_max_summaries": 2, "semantic_top_k": 3})
    messages = builder.build_enhanced_context(user_query=query, conversation_history=[])
    return "\n".join(str(message.get("content") or "") for message in messages)


def test_reference_context_injects_active_working_memory(monkeypatch):
    monkeypatch.setenv("CONTEXT_PLANNER_ENABLED", "0")
    monkeypatch.setenv("AGENT_STM_CONTEXT_LAST_K", "2")

    content = _reference_context()

    assert "## Working Memory" in content
    assert "完成 finance_mrr freshness 问题定位" in content
    assert "[x] 1. 确认 SLA" in content
    assert "[~] 2. 检查 raw_invoices 延迟" in content


def test_reference_context_excludes_done_working_memory(monkeypatch):
    monkeypatch.setenv("CONTEXT_PLANNER_ENABLED", "0")

    content = _reference_context(wm_task_id="old_task")

    assert "## Working Memory" not in content
    assert "旧任务，不应进入 context" not in content


def test_reference_context_keeps_memory_sections_separate(monkeypatch):
    monkeypatch.setenv("CONTEXT_PLANNER_ENABLED", "0")

    content = _reference_context(query="finance_mrr 今天如果晚于 SLA，应该找谁，先查哪些上游？")

    assert "## User Preferences" in content
    assert "## Relevant Conversation History" in content
    assert "## Relevant Semantic Facts" in content
    assert "## Knowledge Graph" in content
    assert content.index("## Relevant Semantic Facts") < content.index("## Knowledge Graph")
