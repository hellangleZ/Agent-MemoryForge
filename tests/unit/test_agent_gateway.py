import types
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from agent_memory_framework.execution_loop import ExecutionLoop
from agent_runtime.product import agent_gateway
from agent_runtime.product.gateway import core_routes as cr
from agent_runtime.product.gateway.models import (
    FileFirstReadProxyRequest,
    FileFirstSearchProxyRequest,
    FileFirstWriteProxyRequest,
)
from agent_runtime.product.auth_tokens import create_access_token
from agent_memory_framework.llm_clients import LLMProviderConfigurationError


def test_health():
    assert agent_gateway.health() == {"ok": True}


def test_preference_confirmation_not_required_by_default(monkeypatch):
    monkeypatch.delenv("PREFERENCE_REQUIRE_CONFIRMATION", raising=False)
    assert cr._preference_confirmation_required() is False


def test_preference_confirmation_can_be_enabled(monkeypatch):
    monkeypatch.setenv("PREFERENCE_REQUIRE_CONFIRMATION", "1")
    assert cr._preference_confirmation_required() is True


def test_chat_requires_user_message(mocker):
    # Patch dependencies to avoid real services
    mocker.patch.object(
        agent_gateway, "create_azure_openai_client", return_value=(Mock(), "m")
    )
    mocker.patch.object(agent_gateway, "MemoryClient", return_value=Mock())
    store = Mock()
    store.get.return_value = None
    store.put.return_value = None

    agent_gateway.app.dependency_overrides[agent_gateway._get_conversation_store] = (
        lambda: store
    )

    payload = {
        "agent": "pm-minimal",
        "user_id": "u",
        "messages": [{"role": "assistant", "content": "hi"}],
    }
    # Direct function call avoids ASGI transport differences in some harnesses.
    req = agent_gateway.ChatRequest(**payload)
    request = Mock()
    request.headers = {"x-workspace-id": "ws_default"}
    token = create_access_token(sub="u", tenant_id="t_u", expires_in_s=60)
    resp = agent_gateway.chat(
        req, request=request, token=token, workspace_id="ws_default", store=store
    )
    assert resp.status == "error"
    assert resp.error == "last user message not found"


def test_chat_success_minimal(mocker):
    # Patch Azure client
    mock_azure = Mock()
    mock_azure.responses.create.return_value = Mock(output=[])
    mocker.patch.object(
        agent_gateway, "create_azure_openai_client", return_value=(mock_azure, "m")
    )
    mocker.patch.object(agent_gateway, "MemoryClient", return_value=Mock())

    # Patch agent class to a tiny fake
    class FakeAgent:
        def __init__(self, runtime):
            self.runtime = runtime

        def run_turn(self, _text):
            return "OK"

    mocker.patch.object(agent_gateway, "_load_agent_class", return_value=FakeAgent)

    store = Mock()
    store.get.return_value = None
    store.put.return_value = None
    agent_gateway.app.dependency_overrides[agent_gateway._get_conversation_store] = (
        lambda: store
    )

    payload = {
        "agent": "pm-minimal",
        "user_id": "u",
        "messages": [{"role": "user", "content": "hello"}],
    }
    req = agent_gateway.ChatRequest(**payload)
    request = Mock()
    request.headers = {"x-trace-id": "t_123", "x-workspace-id": "ws_default"}
    token = create_access_token(sub="u", tenant_id="t_u", expires_in_s=60)
    resp = agent_gateway.chat(
        req, request=request, token=token, workspace_id="ws_default", store=store
    )
    assert resp.status == "success"
    assert resp.trace_id == "t_123"
    assert resp.answer == "OK"
    assert resp.messages[-1].role == "assistant"


def test_chat_emits_structured_tool_intent_and_distill_events(mocker):
    mock_azure = Mock()
    mock_azure.responses.create.return_value = Mock(output=[])
    mocker.patch.object(
        agent_gateway, "create_azure_openai_client", return_value=(mock_azure, "m")
    )

    class FakeAgent:
        def __init__(self, runtime):
            self.runtime = runtime

        def tools_for_turn(self, _text):
            return [
                {
                    "name": "search_semantic_memories",
                    "description": "Search memory",
                    "parameters": {"type": "object", "properties": {}},
                }
            ]

        def run_turn(self, _text):
            return "OK"

    mocker.patch.object(agent_gateway, "_load_agent_class", return_value=FakeAgent)
    mocker.patch.object(cr, "_workspace_mcp_clients", return_value={})
    mocker.patch.object(
        cr,
        "_enqueue_success_chat_distill",
        return_value={"status": "queued", "job_id": "job_1", "round_id": 1},
    )
    log_event = mocker.patch.object(cr, "log_structured_event")

    store = Mock()
    store.get.return_value = None
    store.put.return_value = None

    req = agent_gateway.ChatRequest(
        agent="pm-minimal",
        user_id="u",
        messages=[{"role": "user", "content": "你还记得 finance_mrr 吗？"}],
    )
    request = Mock()
    request.headers = {"x-trace-id": "trace_logs", "x-workspace-id": "ws_default"}
    token = create_access_token(sub="u", tenant_id="t_u", expires_in_s=60)

    resp = agent_gateway.chat(
        req, request=request, token=token, workspace_id="ws_default", store=store
    )

    assert resp.status == "success"
    events = [call.args[1] for call in log_event.call_args_list]
    assert "chat.request" in events
    assert "tool.intent" in events
    assert "chat.success" in events
    assert "distill.enqueue" in events
    tool_intent_call = next(
        call for call in log_event.call_args_list if call.args[1] == "tool.intent"
    )
    assert tool_intent_call.kwargs["memory_tools_visible"] == [
        "search_semantic_memories"
    ]
    distill_call = next(
        call for call in log_event.call_args_list if call.args[1] == "distill.enqueue"
    )
    assert distill_call.kwargs["status"] == "queued"
    assert distill_call.kwargs["job_id"] == "job_1"


def test_tool_result_summary_counts_hits_without_returning_memory_content():
    summary = ExecutionLoop._tool_result_summary(
        {
            "status": "success",
            "data": {"hits": [{"content": "do not log this memory text"}]},
        }
    )
    assert summary["status"] == "success"
    assert summary["hit_count"] == 1
    assert "do not log this memory text" not in str(summary)


def test_chat_skips_workspace_mcp_discovery_without_external_intent(mocker):
    mock_azure = Mock()
    mock_azure.responses.create.return_value = Mock(output=[])
    mocker.patch.object(
        agent_gateway, "create_azure_openai_client", return_value=(mock_azure, "m")
    )

    class FakeAgent:
        def __init__(self, runtime):
            self.runtime = runtime

        def tools_for_turn(self, _text):
            return []

        def run_turn(self, _text):
            return "OK"

    mocker.patch.object(agent_gateway, "_load_agent_class", return_value=FakeAgent)
    mocker.patch.object(
        cr,
        "get_config",
        return_value=types.SimpleNamespace(
            agent_id="a",
            memory_service_url="http://memory-service:8001",
            mcp_tools_enabled=True,
        ),
    )
    mocker.patch.object(cr, "_load_portal_config", return_value={})
    mocker.patch.object(cr, "_get_custom_agent_spec", return_value=None)
    mocker.patch.object(
        cr,
        "_workspace_mcp_clients",
        return_value={
            cr._workspace_mcp_cache_key("t_u", "ws_default"): {"context7": Mock()}
        },
    )
    discover = mocker.patch.object(cr, "discover_tools_from_mcp", return_value={})

    store = Mock()
    store.get.return_value = None
    store.put.return_value = None

    req = agent_gateway.ChatRequest(
        agent="pm-minimal",
        user_id="u",
        messages=[
            {
                "role": "user",
                "content": (
                    "我现在这个 Northstar DW Ops 里，"
                    "finance_mrr 的 freshness SLA 是什么？它上游依赖什么？"
                ),
            }
        ],
    )
    request = Mock()
    request.headers = {"x-workspace-id": "ws_default"}
    token = create_access_token(sub="u", tenant_id="t_u", expires_in_s=60)

    resp = agent_gateway.chat(
        req, request=request, token=token, workspace_id="ws_default", store=store
    )

    assert resp.status == "success"
    discover.assert_not_called()


def test_chat_does_not_discover_global_tools_without_workspace_mcp(mocker, monkeypatch):
    monkeypatch.delenv("AGENT_REFERENCE_RUNTIME_GLOBAL_TOOLS_ENABLED", raising=False)
    mock_azure = Mock()
    mock_azure.responses.create.return_value = Mock(output=[])
    mocker.patch.object(
        agent_gateway, "create_azure_openai_client", return_value=(mock_azure, "m")
    )

    class FakeAgent:
        def __init__(self, runtime):
            self.runtime = runtime

        def tools_for_turn(self, _text):
            return []

        def run_turn(self, _text):
            return "OK"

    mocker.patch.object(agent_gateway, "_load_agent_class", return_value=FakeAgent)
    mocker.patch.object(
        cr,
        "get_config",
        return_value=types.SimpleNamespace(
            agent_id="a",
            memory_service_url="http://memory-service:8001",
            mcp_tools_enabled=True,
        ),
    )
    mocker.patch.object(cr, "_load_portal_config", return_value={})
    mocker.patch.object(cr, "_get_custom_agent_spec", return_value=None)
    mocker.patch.object(cr, "_workspace_mcp_clients", return_value={})
    discover = mocker.patch.object(cr, "discover_tools", return_value={})

    store = Mock()
    store.get.return_value = None
    store.put.return_value = None

    req = agent_gateway.ChatRequest(
        agent="pm-minimal",
        user_id="u",
        messages=[{"role": "user", "content": "use context7 docs for Next.js API"}],
    )
    request = Mock()
    request.headers = {"x-workspace-id": "ws_default"}
    token = create_access_token(sub="u", tenant_id="t_u", expires_in_s=60)

    resp = agent_gateway.chat(
        req, request=request, token=token, workspace_id="ws_default", store=store
    )

    assert resp.status == "success"
    discover.assert_not_called()


def test_chat_requires_workspace_id_header(mocker):
    try:
        agent_gateway._require_workspace_id(None)
        assert False, "expected missing workspace id error"
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400


def test_chat_persists_per_workspace(mocker):
    mock_azure = Mock()
    mock_azure.responses.create.return_value = Mock(output=[])
    mocker.patch.object(
        agent_gateway, "create_azure_openai_client", return_value=(mock_azure, "m")
    )
    mocker.patch.object(agent_gateway, "MemoryClient", return_value=Mock())

    class FakeAgent:
        def __init__(self, runtime):
            self.runtime = runtime

        def run_turn(self, _text):
            return "OK"

    mocker.patch.object(agent_gateway, "_load_agent_class", return_value=FakeAgent)

    store = Mock()
    store.get.return_value = None
    store.put.return_value = None
    agent_gateway.app.dependency_overrides[agent_gateway._get_conversation_store] = (
        lambda: store
    )

    payload = {
        "agent": "pm-minimal",
        "user_id": "u",
        "messages": [{"role": "user", "content": "hello"}],
    }
    req = agent_gateway.ChatRequest(**payload)
    request = Mock()
    request.headers = {"x-workspace-id": "ws_a"}
    token = create_access_token(sub="u", tenant_id="t_u", expires_in_s=60)
    mocker.patch.object(
        cr,
        "_load_portal_config",
        return_value={
            "workspace_members": {"t_u": {"ws_a": [{"user_id": "u", "role": "member"}]}}
        },
    )
    resp = agent_gateway.chat(
        req, request=request, token=token, workspace_id="ws_a", store=store
    )
    assert resp.status == "success"

    assert store.get.call_count == 1
    assert store.put.call_count == 2
    stored_conversation_id = store.get.call_args.args[0]
    assert stored_conversation_id.startswith("t_u:ws_a:")


def test_chat_missing_llm_provider_returns_operational_error(mocker):
    mocker.patch.object(
        agent_gateway,
        "create_azure_openai_client",
        side_effect=LLMProviderConfigurationError("internal provider detail"),
    )
    store = Mock()
    store.get.return_value = None
    store.put.return_value = None

    payload = {
        "agent": "pm-minimal",
        "user_id": "u",
        "messages": [{"role": "user", "content": "hello"}],
    }
    req = agent_gateway.ChatRequest(**payload)
    request = Mock()
    request.headers = {"x-trace-id": "t_missing_llm", "x-workspace-id": "ws_default"}
    token = create_access_token(sub="u", tenant_id="t_u", expires_in_s=60)

    resp = agent_gateway.chat(
        req, request=request, token=token, workspace_id="ws_default", store=store
    )

    assert resp.status == "error"
    assert resp.trace_id == "t_missing_llm"
    assert resp.error
    assert "provider credentials" in resp.error
    assert "internal provider detail" not in resp.error
    assert "OPENAI" not in resp.error


def test_memory_search_rejects_unlisted_memory_url(monkeypatch):
    monkeypatch.setattr(
        cr,
        "get_config",
        lambda: types.SimpleNamespace(memory_service_url="http://memory-service:8001"),
    )
    monkeypatch.setattr(
        cr,
        "_me_from_access_token",
        lambda _token: types.SimpleNamespace(tenant_id="t_u"),
    )

    req = FileFirstSearchProxyRequest(
        query="hello",
        memory_url="http://169.254.169.254/latest/meta-data",
    )

    with pytest.raises(HTTPException) as exc:
        cr.memory_search(req, token="tok", workspace_id="ws_1")

    assert exc.value.status_code == 400
    assert "memory_url override is not allowed" in exc.value.detail


def test_memory_read_rejects_cross_user_preferences(monkeypatch):
    monkeypatch.setattr(
        cr,
        "get_config",
        lambda: types.SimpleNamespace(memory_service_url="http://memory-service:8001"),
    )
    monkeypatch.setattr(
        cr,
        "_me_from_access_token",
        lambda _token: types.SimpleNamespace(sub="alice", tenant_id="t_u"),
    )
    monkeypatch.setattr(
        cr,
        "_assert_workspace_access",
        lambda *_args, **_kwargs: {"role": "user", "member_role": "owner"},
    )

    req = FileFirstReadProxyRequest(tier="preferences", user_id="bob")

    with pytest.raises(HTTPException) as exc:
        cr.memory_read(req, token="tok", workspace_id="ws_default")

    assert exc.value.status_code == 403


def test_memory_read_defaults_preferences_to_authenticated_user(monkeypatch):
    called = {}
    monkeypatch.setattr(
        cr,
        "get_config",
        lambda: types.SimpleNamespace(memory_service_url="http://memory-service:8001"),
    )
    monkeypatch.setattr(
        cr,
        "_me_from_access_token",
        lambda _token: types.SimpleNamespace(sub="alice", tenant_id="t_u"),
    )
    monkeypatch.setattr(
        cr,
        "_assert_workspace_access",
        lambda *_args, **_kwargs: {"role": "user", "member_role": "owner"},
    )

    class _FakeClient:
        def memory_read(self, **kwargs):
            called.update(kwargs)
            return {"status": "success", "data": {}}

    monkeypatch.setattr(cr, "_scoped_memory_client", lambda **_kwargs: _FakeClient())

    req = FileFirstReadProxyRequest(tier="preferences")
    res = cr.memory_read(req, token="tok", workspace_id="ws_default")

    assert res["status"] == "success"
    assert called["user_id"] == "alice"


def test_memory_search_passes_authenticated_actor_to_memory_service(monkeypatch):
    called = {}
    monkeypatch.setattr(
        cr,
        "get_config",
        lambda: types.SimpleNamespace(memory_service_url="http://memory-service:8001"),
    )
    monkeypatch.setattr(
        cr,
        "_me_from_access_token",
        lambda _token: types.SimpleNamespace(sub="alice", tenant_id="t_u"),
    )
    monkeypatch.setattr(
        cr,
        "_assert_workspace_access",
        lambda *_args, **_kwargs: {"role": "user", "member_role": "owner"},
    )

    class _FakeClient:
        def __init__(self, **kwargs):
            called["client_kwargs"] = kwargs

        def memory_search(self, **kwargs):
            called["search"] = kwargs
            return {"status": "success", "data": {"hits": []}}

    monkeypatch.setattr(
        cr, "_scoped_memory_client", lambda **kwargs: _FakeClient(**kwargs)
    )

    req = FileFirstSearchProxyRequest(query="timezone", tiers=["preferences"])
    res = cr.memory_search(req, token="tok", workspace_id="ws_default")

    assert res["status"] == "success"
    assert called["client_kwargs"]["actor_user_id"] == "alice"
    assert called["client_kwargs"]["actor_role"] == "user"


def test_memory_write_proxy_uses_authenticated_scope_and_actor(monkeypatch):
    called = {}
    monkeypatch.setattr(
        cr,
        "get_config",
        lambda: types.SimpleNamespace(memory_service_url="http://memory-service:8001"),
    )
    monkeypatch.setattr(
        cr,
        "_me_from_access_token",
        lambda _token: types.SimpleNamespace(sub="alice", tenant_id="t_u"),
    )
    monkeypatch.setattr(
        cr,
        "_assert_workspace_access",
        lambda *_args, **_kwargs: {"role": "user", "member_role": "member"},
    )
    monkeypatch.setattr(cr._obs_store, "record_metric", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cr._obs_store, "record_audit", lambda *_args, **_kwargs: None)

    class _FakeClient:
        def __init__(self, **kwargs):
            called["client_kwargs"] = kwargs

        def memory_write(self, **kwargs):
            called["write"] = kwargs
            return {
                "status": "success",
                "data": {"path": "stm/conv1.md", "entry_id": "e1"},
            }

    monkeypatch.setattr(
        cr, "_scoped_memory_client", lambda **kwargs: _FakeClient(**kwargs)
    )

    req = FileFirstWriteProxyRequest(
        tier="stm",
        scope="user",
        content="summary",
        conversation_id="conv1",
    )
    res = cr.memory_write(req, token="tok", workspace_id="ws_default")

    assert res["status"] == "success"
    assert called["client_kwargs"]["tenant_id"] == "t_u"
    assert called["client_kwargs"]["workspace_id"] == "ws_default"
    assert called["client_kwargs"]["actor_user_id"] == "alice"
    assert called["client_kwargs"]["actor_role"] == "user"
    assert called["write"]["metadata"]["user_id"] == "alice"
    assert called["write"]["metadata"]["conversation_id"] == "conv1"
    assert called["write"]["conversation_id"] == "conv1"


def test_memory_write_proxy_rejects_private_write_for_other_user(monkeypatch):
    monkeypatch.setattr(
        cr,
        "get_config",
        lambda: types.SimpleNamespace(memory_service_url="http://memory-service:8001"),
    )
    monkeypatch.setattr(
        cr,
        "_me_from_access_token",
        lambda _token: types.SimpleNamespace(sub="alice", tenant_id="t_u"),
    )
    monkeypatch.setattr(
        cr,
        "_assert_workspace_access",
        lambda *_args, **_kwargs: {"role": "user", "member_role": "member"},
    )

    req = FileFirstWriteProxyRequest(
        tier="preferences",
        scope="user",
        user_id="bob",
        key="language",
        value="zh-CN",
    )
    with pytest.raises(HTTPException) as exc:
        cr.memory_write(req, token="tok", workspace_id="ws_default")
    assert exc.value.status_code == 403
