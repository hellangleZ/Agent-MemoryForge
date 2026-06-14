import sqlite3
from typing import Any, Dict

import pytest
from fastapi import HTTPException

from agent_memory_lib.client import MemoryClient


def _skip_if_fts5_missing() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    except sqlite3.OperationalError as exc:
        pytest.skip(f"SQLite FTS5 unavailable: {exc}")
    finally:
        conn.close()


def _seed_recall_data(orch, *, tenant_id: str = "tenant_acme", workspace_id: str = "dw_ops") -> None:
    orch.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "preferences",
            "scope": "user",
            "user_id": "alice",
            "key": "language",
            "value": "zh-CN",
            "actor_user_id": "alice",
            "actor_role": "user",
        },
    )
    orch.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "preferences",
            "scope": "user",
            "user_id": "alice",
            "key": "answer_style",
            "value": "短句、先结论",
            "actor_user_id": "alice",
            "actor_role": "user",
        },
    )
    orch.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "preferences",
            "scope": "user",
            "user_id": "bob",
            "key": "language",
            "value": "en-US",
            "actor_user_id": "bob",
            "actor_role": "user",
        },
    )
    orch.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "stm",
            "scope": "user",
            "conversation_id": "conv_dw_1",
            "content": "上一轮我们在排查 finance_mrr freshness，已确认用户关心 SLA、owner 和上游依赖。",
            "metadata": {
                "user_id": "alice",
                "conversation_id": "conv_dw_1",
                "round_id": 1,
                "stm_summary": {
                    "round_id": 1,
                    "final_answer": "上一轮我们在排查 finance_mrr freshness，已确认用户关心 SLA、owner 和上游依赖。",
                },
            },
            "actor_user_id": "alice",
            "actor_role": "user",
        },
    )
    orch.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "wm",
            "scope": "user",
            "task_id": "conv_dw_1",
            "metadata": {
                "user_id": "alice",
                "task_id": "conv_dw_1",
                "state": {
                    "status": "active",
                    "goal": "完成 finance_mrr freshness 问题定位",
                    "steps": [
                        {"id": "1", "text": "确认 SLA", "status": "done"},
                        {"id": "2", "text": "检查 raw_invoices 延迟", "status": "doing"},
                    ],
                },
            },
            "actor_user_id": "alice",
            "actor_role": "user",
        },
    )
    orch.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "semantic",
            "scope": "project",
            "content": "finance_mrr 的刷新 SLA 是每天 09:00 Asia/Shanghai 前完成，owner 是 Alice。",
            "metadata": {"tags": ["dw", "sla"], "source": "seed"},
        },
    )
    orch.write_memory(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "tier": "semantic",
            "scope": "project",
            "content": "orders_daily 的刷新 SLA 是 T+1 08:30，owner 是 Bob。",
            "metadata": {"tags": ["dw", "sla"], "source": "seed"},
        },
    )
    for subject, relation, obj in [
        ("finance_mrr", "depends_on", "raw_invoices"),
        ("finance_mrr", "depends_on", "raw_payments"),
        ("raw_invoices", "produced_by", "billing_elt"),
    ]:
        orch.write_memory(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            payload={
                "tier": "graph",
                "scope": "project",
                "subject": subject,
                "relation": relation,
                "obj": obj,
            },
        )


class _OrchestratorClient(MemoryClient):
    def __init__(self, orch, *, tenant_id: str, workspace_id: str, actor_user_id: str) -> None:
        super().__init__(
            "http://memory.local",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            actor_role="user",
        )
        self._orch = orch

    def memory_read(self, **kwargs):
        payload = {
            **kwargs,
            "actor_user_id": self.actor_user_id,
            "actor_role": self.actor_role,
        }
        return {
            "status": "success",
            "data": self._orch.read_memory(
                tenant_id=self.tenant_id,
                workspace_id=self.workspace_id,
                payload=payload,
            ),
        }

    def memory_search(self, **kwargs):
        payload = {
            **kwargs,
            "actor_user_id": self.actor_user_id,
            "actor_role": self.actor_role,
        }
        return {
            "status": "success",
            "data": self._orch.search_memory(
                tenant_id=self.tenant_id,
                workspace_id=self.workspace_id,
                payload=payload,
            ),
        }


@pytest.fixture()
def seeded_orchestrator(tmp_path, monkeypatch):
    _skip_if_fts5_missing()
    monkeypatch.setenv("AGENT_MEMORY_BACKEND", "file_first")
    monkeypatch.setenv("AGENT_MEMORY_FILE_ROOT", str(tmp_path))
    monkeypatch.setenv("AGENT_MEMORY_VECTOR_ENABLED", "0")
    from agent_memory_service.orchestrator import MemoryOrchestrator

    orch = MemoryOrchestrator()
    _seed_recall_data(orch)
    orch.write_memory(
        tenant_id="tenant_acme",
        workspace_id="support_ops",
        payload={
            "tier": "semantic",
            "scope": "project",
            "content": "refund_policy 的审批 owner 是 Support Lead。",
            "metadata": {"tags": ["support"], "source": "seed"},
        },
    )
    return orch


def test_real_sdk_context_recalls_all_expected_memory_tiers(seeded_orchestrator):
    client = _OrchestratorClient(
        seeded_orchestrator,
        tenant_id="tenant_acme",
        workspace_id="dw_ops",
        actor_user_id="alice",
    )

    content = "\n".join(
        message["content"]
        for message in client.build_context(
            query="finance_mrr 的刷新 SLA、owner、上游依赖是什么？",
            user_id="alice",
            conversation_id="conv_dw_1",
            max_search_queries=2,
        )
    )

    assert "## User Preferences" in content
    assert "answer_style: 短句、先结论" in content
    assert "## Recent Conversation Memory" in content
    assert "排查 finance_mrr freshness" in content
    assert "## Relevant Semantic Facts" in content
    assert "09:00 Asia/Shanghai" in content
    assert "owner 是 Alice" in content
    assert "## Knowledge Graph" in content
    assert "raw_invoices" in content
    assert "raw_payments" in content
    assert "entry_id" not in content
    assert "<!-- am:entry" not in content


def test_private_tiers_are_user_scoped_but_semantic_and_graph_are_workspace_shared(seeded_orchestrator):
    bob = _OrchestratorClient(
        seeded_orchestrator,
        tenant_id="tenant_acme",
        workspace_id="dw_ops",
        actor_user_id="bob",
    )

    content = "\n".join(
        message["content"]
        for message in bob.build_context(
            query="finance_mrr 的刷新 SLA 和上游依赖是什么？",
            user_id="bob",
            conversation_id="conv_dw_1",
            max_search_queries=2,
        )
    )

    assert "language: en-US" in content
    assert "短句、先结论" not in content
    assert "排查 finance_mrr freshness" not in content
    assert "09:00 Asia/Shanghai" in content
    assert "raw_invoices" in content

    with pytest.raises(HTTPException) as wm_read:
        seeded_orchestrator.read_memory(
            tenant_id="tenant_acme",
            workspace_id="dw_ops",
            payload={
                "tier": "wm",
                "task_id": "conv_dw_1",
                "actor_user_id": "bob",
                "actor_role": "user",
            },
        )
    assert wm_read.value.status_code == 403


def test_workspace_scope_prevents_cross_workspace_semantic_recall(seeded_orchestrator):
    support_user = _OrchestratorClient(
        seeded_orchestrator,
        tenant_id="tenant_acme",
        workspace_id="support_ops",
        actor_user_id="alice",
    )

    content = "\n".join(
        message["content"]
        for message in support_user.build_context(
            query="finance_mrr 的刷新 SLA 是什么？",
            user_id="alice",
            conversation_id="conv_dw_1",
            max_search_queries=2,
        )
    )

    assert "finance_mrr 的刷新 SLA" not in content
    assert "09:00 Asia/Shanghai" not in content
    assert "raw_invoices" not in content


def test_distill_contract_classifies_preferences_semantic_graph_and_stm(monkeypatch):
    from agent_runtime.memory_distill.job_schema import new_job
    from scripts import memory_distill_worker

    class _CapturingClient:
        def __init__(self, _base_url):
            self.calls = []

        def with_scope(self, tenant_id, workspace_id):
            self.scope = (tenant_id, workspace_id)
            return self

        def memory_write(self, **kwargs):
            self.calls.append(kwargs)
            return {"status": "success"}

    class _DistillResult:
        stm_summary = {"final_answer": "用户要求记住 finance_mrr SLA、owner 和上游依赖。"}
        semantic_facts = [
            {
                "text": "finance_mrr 的刷新 SLA 是每天 09:00 Asia/Shanghai 前完成，owner 是 Alice。",
                "importance": 0.95,
            }
        ]
        preferences = [{"key": "answer_style", "value": "中文短句", "confidence": 0.95}]
        kg_relations = [
            {"subject": "finance_mrr", "relation": "depends_on", "obj": "raw_invoices", "confidence": 0.95},
            {"subject": "finance_mrr", "relation": "depends_on", "obj": "raw_payments", "confidence": 0.95},
        ]

    monkeypatch.delenv("MEMORY_DISTILL_PREFERENCE_REQUIRE_CONFIRMATION", raising=False)
    client = _CapturingClient("http://memory.local")
    monkeypatch.setattr(memory_distill_worker, "MemoryClient", lambda base_url: client)
    job = new_job(
        tenant_id="tenant_acme",
        workspace_id="dw_ops",
        user_id="alice",
        conversation_id="conv_dw_1",
        round_id=1,
        messages=[
            {
                "role": "user",
                "content": (
                    "记住：finance_mrr 的 SLA 是每天 09:00 Asia/Shanghai 前完成，"
                    "owner 是 Alice，上游依赖 raw_invoices 和 raw_payments。"
                    "以后回答我都用中文短句。"
                ),
            }
        ],
        last_user=(
            "记住：finance_mrr 的 SLA 是每天 09:00 Asia/Shanghai 前完成，"
            "owner 是 Alice，上游依赖 raw_invoices 和 raw_payments。"
            "以后回答我都用中文短句。"
        ),
        assistant_answer="好的。",
    )

    memory_distill_worker._store_distilled_memories(
        base_url="http://memory.local",
        job=job,
        result=_DistillResult(),
    )

    tiers = [call["tier"] for call in client.calls]
    assert tiers.count("stm") == 1
    assert tiers.count("semantic") == 1
    assert tiers.count("preferences") == 1
    assert tiers.count("graph") == 2


def test_distill_contract_does_not_promote_transient_chat_to_long_term(monkeypatch):
    from agent_runtime.memory_distill.job_schema import new_job
    from scripts import memory_distill_worker

    class _CapturingClient:
        def __init__(self, _base_url):
            self.calls = []

        def with_scope(self, tenant_id, workspace_id):
            return self

        def memory_write(self, **kwargs):
            self.calls.append(kwargs)
            return {"status": "success"}

    class _DistillResult:
        stm_summary = {"final_answer": "用户表示刚才只是闲聊天气，没有什么要记。"}
        semantic_facts = [{"text": "用户刚才聊了天气", "importance": 0.99}]
        preferences = []
        kg_relations = []

    client = _CapturingClient("http://memory.local")
    monkeypatch.setattr(memory_distill_worker, "MemoryClient", lambda base_url: client)
    job = new_job(
        tenant_id="tenant_acme",
        workspace_id="dw_ops",
        user_id="alice",
        conversation_id="conv_weather",
        round_id=1,
        messages=[{"role": "user", "content": "我们刚才聊了下天气，没什么要记的。"}],
        last_user="我们刚才聊了下天气，没什么要记的。",
        assistant_answer="明白。",
    )

    memory_distill_worker._store_distilled_memories(
        base_url="http://memory.local",
        job=job,
        result=_DistillResult(),
    )

    tiers = [call["tier"] for call in client.calls]
    assert tiers == ["stm"]
