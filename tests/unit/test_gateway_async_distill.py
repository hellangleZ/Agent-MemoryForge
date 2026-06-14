from __future__ import annotations

import types

import pytest

from agent_runtime.memory_distill.distill_settings import MemoryDistillSettings
from agent_runtime.product.chat_models import ChatMessage, ChatRequest
from agent_runtime.product.gateway import core_routes as cr
from agent_runtime.product.usage_store import SQLiteUsageStore


class _FakeConversationStore:
    def __init__(self) -> None:
        self.messages = []
        self.metadata = {}

    def get_recent(self, *_args, **_kwargs):
        return None

    def put(self, *, messages, metadata=None, **_kwargs):
        self.messages = list(messages)
        self.metadata = dict(metadata or {})


class _FakeMemoryClient:
    def retrieve_stm(self, **_kwargs):
        return {"status": "success", "data": []}

    def retrieve_wm(self, **_kwargs):
        return {"status": "success", "data": None}


class _Registry:
    def list_tools(self, _category):
        return []


class _Agent:
    def __init__(self, runtime):
        self.runtime = runtime
        self.tool_registry = _Registry()
        self.execution_loop = types.SimpleNamespace(llm_call_fn=None)
        self.conversation_history = []

    def run_turn(self, _last_user):
        return "hello from agent"


def _patch_chat_dependencies(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_STEP_MODE_ENABLED", "0")
    monkeypatch.setenv("MCP_TOOLS_ENABLED", "0")
    usage = SQLiteUsageStore(db_path=str(tmp_path / "usage.db"))
    monkeypatch.setattr(cr, "_usage_store", usage)
    monkeypatch.setattr(
        cr,
        "_me_from_access_token",
        lambda *_: types.SimpleNamespace(sub="alice", tenant_id="tenant_acme"),
    )
    monkeypatch.setattr(
        cr,
        "get_config",
        lambda: types.SimpleNamespace(
            agent_id="pm-minimal",
            memory_service_url="http://memory",
            mcp_tools_enabled=False,
        ),
    )
    monkeypatch.setattr(cr, "_scoped_memory_client", lambda **_kwargs: _FakeMemoryClient())
    monkeypatch.setattr(
        cr,
        "_load_portal_config",
        lambda: {
            "workspace_members": {
                "tenant_acme": {"ws1": [{"user_id": "alice", "role": "member"}]}
            }
        },
    )
    monkeypatch.setattr(cr, "_get_custom_agent_spec", lambda **_kwargs: None)

    from agent_runtime.product import agent_gateway

    monkeypatch.setattr(agent_gateway, "create_azure_openai_client", lambda: (object(), "gpt-test"))
    monkeypatch.setattr(agent_gateway, "_load_agent_class", lambda _agent: _Agent)


def _chat_once(store=None):
    req = ChatRequest(
        agent="pm-minimal",
        user_id="alice",
        messages=[ChatMessage(role="user", content="my favorite language is Python")],
    )
    return cr.chat(
        req=req,
        request=types.SimpleNamespace(headers={}, state=types.SimpleNamespace()),
        token="token-for-test",
        workspace_id="ws1",
        store=store or _FakeConversationStore(),
    )


@pytest.mark.unit
def test_chat_enqueues_async_distill_without_sync_preference_extraction(monkeypatch, tmp_path):
    _patch_chat_dependencies(monkeypatch, tmp_path)
    enqueued = []

    assert not hasattr(cr, "two_stage_preferences")
    monkeypatch.setattr(
        cr.MemoryDistillSettings,
        "from_env",
        lambda: MemoryDistillSettings(enabled=True, queue_key="test:distill:q"),
    )
    monkeypatch.setattr(
        cr,
        "enqueue_distill_job",
        lambda *, settings, job: enqueued.append((settings, job)) or {
            "status": "queued",
            "job_id": job.job_id,
        },
    )

    resp = _chat_once()

    assert resp.status == "success"
    assert len(enqueued) == 1
    settings, job = enqueued[0]
    assert settings.enabled is True
    assert job.tenant_id == "tenant_acme"
    assert job.workspace_id == "ws1"
    assert job.user_id == "alice"
    assert job.round_id == 1
    assert job.last_user == "my favorite language is Python"
    assert job.assistant_answer == "hello from agent"
    assert [m["role"] for m in job.messages] == ["user", "assistant"]


@pytest.mark.unit
def test_chat_does_not_block_when_distill_enqueue_fails(monkeypatch, tmp_path):
    _patch_chat_dependencies(monkeypatch, tmp_path)
    assert not hasattr(cr, "two_stage_preferences")
    monkeypatch.setattr(
        cr.MemoryDistillSettings,
        "from_env",
        lambda: MemoryDistillSettings(enabled=True, queue_key="test:distill:q"),
    )
    monkeypatch.setattr(
        cr,
        "enqueue_distill_job",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("redis unavailable")),
    )

    resp = _chat_once()

    assert resp.status == "success"
    assert resp.answer == "hello from agent"
