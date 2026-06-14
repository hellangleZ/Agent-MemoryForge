import json
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from agent_runtime.product.auth_tokens import create_access_token
from agent_memory_framework.demo_agent import DemoAgent
from agent_memory_framework.llm_clients import LLMProviderConfigurationError


class _FakeMemoryClient:
    """Hermetic MemoryClient stub: never does network I/O."""

    def store_stm(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"status": "success", "data": {"id": "stm_1"}}

    def retrieve_stm(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"status": "success", "data": []}

    def store_wm(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"status": "success", "data": {"id": "wm_1"}}

    def retrieve_wm(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"status": "success", "data": None}

    def store_ltm_preference(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"status": "success", "data": {"id": "pref_1"}}

    def retrieve_ltm_preference(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"status": "success", "data": None}

    def list_ltm_preferences(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"status": "success", "data": {}}

    def memory_search(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"status": "success", "data": {"hits": []}}


class _ConversationStoreStub:
    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []
        self.metadata: Dict[str, Any] = {}

    def get_recent(self, _conversation_id: str, max_messages: int) -> Any:
        return type(
            "Conversation",
            (),
            {
                "messages": list(self.messages[-max_messages:]),
                "metadata": dict(self.metadata),
            },
        )()

    def put(
        self,
        *,
        conversation_id: str,
        user_id: str,
        messages: List[Dict[str, Any]],
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        self.messages = list(messages)
        self.metadata = dict(metadata or {})


class _LLMStub:
    """Two-call LLM stub: tool call on first invocation, final text on second."""

    def __init__(self) -> None:
        self.calls = 0
        self.messages_seen: List[List[Dict[str, Any]]] = []

    def __call__(self, _messages: List[Dict[str, Any]], **_kwargs: Any) -> Dict[str, Any]:
        self.calls += 1
        self.messages_seen.append(list(_messages))
        if self.calls == 1:
            return {
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "function": {"name": "echo", "arguments": json.dumps({"text": "hi"})},
                    }
                ],
                "choices": [{"message": {"content": ""}}],
            }
        return {"choices": [{"message": {"content": "FINAL"}}]}


class _ToolEventAgent(DemoAgent):
    def get_system_prompt(self) -> str:
        return "You are a test agent."

    def register_domain_tools(self, registry) -> None:
        registry.register(
            name="echo",
            func=lambda text: {"status": "success", "data": text},
            category="test",
            schema={
                "description": "Echo back text",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        )


def _iter_sse_events(text: str) -> List[Dict[str, Any]]:
    """Parse minimal SSE format emitted by /v1/chat/stream (event+data lines)."""
    events: List[Dict[str, Any]] = []
    cur_event: Optional[str] = None
    cur_data: Optional[str] = None

    for line in text.splitlines():
        if not line.strip():
            if cur_event:
                payload = {}
                if cur_data:
                    try:
                        payload = json.loads(cur_data)
                    except Exception:
                        payload = {"raw": cur_data}
                events.append({"event": cur_event, "data": payload})
            cur_event = None
            cur_data = None
            continue

        if line.startswith("event:"):
            cur_event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            cur_data = line.split(":", 1)[1].strip()

    return events


@pytest.mark.integration
def test_chat_stream_emits_tool_events_and_tokens(monkeypatch):
    # Disable MCP tool discovery to keep the test hermetic.
    monkeypatch.setenv("MCP_TOOLS_ENABLED", "0")
    # Step-mode can introduce an extra LLM call (plan offer). Disable it here so
    # the test stays focused on tool SSE events and token streaming.
    monkeypatch.setenv("AGENT_STEP_MODE_ENABLED", "0")

    from config import agent_config as agent_cfg

    old_global = getattr(agent_cfg, "_global_config", None)
    agent_cfg.reload_config()

    from agent_runtime.product.gateway.app import create_app
    from agent_runtime.product.gateway import core_routes
    from agent_runtime.product import agent_gateway

    llm = _LLMStub()

    # Patch all external/service dependencies used by the gateway handler.
    monkeypatch.setattr(core_routes, "_scoped_memory_client", lambda **_kw: _FakeMemoryClient())
    monkeypatch.setattr(core_routes, "_llm_call_factory", lambda *_a, **_kw: llm)
    monkeypatch.setattr(agent_gateway, "create_azure_openai_client", lambda: (object(), "m"))
    monkeypatch.setattr(agent_gateway, "_load_agent_class", lambda _name: _ToolEventAgent)

    app = create_app()
    store = _ConversationStoreStub()
    app.dependency_overrides[core_routes._get_conversation_store] = lambda: store
    client = TestClient(app)

    token = create_access_token(sub="u", tenant_id="t_u", expires_in_s=60)
    trace_id = "trace_e2e_1"

    resp = client.post(
        "/v1/chat/stream",
        headers={
            "Authorization": f"Bearer {token}",
            "x-workspace-id": "ws_default",
            "x-trace-id": trace_id,
        },
        json={
            "agent": "pm-minimal",
            "user_id": "u",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert resp.status_code == 200

    events = _iter_sse_events(resp.text)
    assert any(e["event"] == "meta" and e["data"].get("trace_id") == trace_id for e in events)
    assert any(e["event"] == "tool" and e["data"].get("event") == "tool.start" for e in events)
    assert any(e["event"] == "tool" and e["data"].get("event") == "tool.end" for e in events)
    assert any(e["event"] == "token" and (e["data"].get("text") or "") for e in events)
    assert any(e["event"] == "done" for e in events)

    # Ensure our stub drove exactly one tool turn then finalized.
    assert llm.calls == 2

    # Second turn: verify the gateway injects persisted history (prior assistant answer)
    # into the prompt before adding the current user message.
    meta = next((e for e in events if e["event"] == "meta"), None)
    assert meta and meta["data"].get("conversation_id")
    conv_id = meta["data"]["conversation_id"]

    resp2 = client.post(
        "/v1/chat/stream",
        headers={
            "Authorization": f"Bearer {token}",
            "x-workspace-id": "ws_default",
            "x-trace-id": "trace_e2e_2",
        },
        json={
            "agent": "pm-minimal",
            "user_id": "u",
            "conversation_id": conv_id,
            "messages": [{"role": "user", "content": "next"}],
        },
    )
    assert resp2.status_code == 200
    assert llm.calls >= 3

    # Call #3 is the first LLM invocation of the second request.
    assert len(llm.messages_seen) >= 3
    prompt_messages = llm.messages_seen[2]
    assert any(m.get("role") == "assistant" and m.get("content") == "FINAL" for m in prompt_messages)

    # Restore config singleton to avoid leaking settings into other tests.
    agent_cfg._global_config = old_global


@pytest.mark.integration
def test_chat_stream_hides_llm_provider_configuration_details(monkeypatch):
    monkeypatch.setenv("MCP_TOOLS_ENABLED", "0")

    from config import agent_config as agent_cfg

    old_global = getattr(agent_cfg, "_global_config", None)
    agent_cfg.reload_config()

    from agent_runtime.product.gateway.app import create_app
    from agent_runtime.product.gateway import core_routes
    from agent_runtime.product import agent_gateway

    def _raise_config_error():
        raise LLMProviderConfigurationError("Missing OPENAI_BASE_URL/OPENAI_API_KEY")

    monkeypatch.setattr(agent_gateway, "create_azure_openai_client", _raise_config_error)

    app = create_app()
    store = _ConversationStoreStub()
    app.dependency_overrides[core_routes._get_conversation_store] = lambda: store
    client = TestClient(app)

    token = create_access_token(sub="u", tenant_id="t_u", expires_in_s=60)
    resp = client.post(
        "/v1/chat/stream",
        headers={
            "Authorization": f"Bearer {token}",
            "x-workspace-id": "ws_default",
            "x-trace-id": "trace_missing_llm",
        },
        json={
            "agent": "pm-minimal",
            "user_id": "u",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert resp.status_code == 200
    events = _iter_sse_events(resp.text)
    error_event = next(e for e in events if e["event"] == "error")
    error_text = error_event["data"].get("error") or ""
    assert "provider credentials" in error_text
    assert "OPENAI" not in error_text
    assert "AZURE" not in error_text
    assert any(e["event"] == "done" for e in events)

    agent_cfg._global_config = old_global
