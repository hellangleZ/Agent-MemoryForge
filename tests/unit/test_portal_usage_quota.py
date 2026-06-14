from __future__ import annotations

import types

import pytest
from fastapi import HTTPException

from agent_runtime.product.auth_store import UserRecord
from agent_runtime.product.chat_models import ChatMessage, ChatRequest
from agent_runtime.product.gateway import core_routes as cr
from agent_runtime.product.gateway import portal_helpers as ph
from agent_runtime.product.gateway import portal_routes as pr
from agent_runtime.product.gateway.models import AdminQuotaRequest
from agent_runtime.product.usage_store import SQLiteUsageStore


def _admin_me():
    return types.SimpleNamespace(sub="admin", tenant_id="tenant_acme")


@pytest.mark.unit
def test_require_admin_uses_explicit_user_role(monkeypatch):
    monkeypatch.setattr(
        ph,
        "_me_from_access_token",
        lambda *_: types.SimpleNamespace(sub="ops", tenant_id="tenant_acme"),
    )
    monkeypatch.setattr(
        ph,
        "_auth_store",
        types.SimpleNamespace(
            get_user=lambda _username: UserRecord(
                username="ops",
                password_hash="hash",
                tenant_id="tenant_acme",
                role="admin",
            )
        ),
    )

    me = ph._require_admin(token="t")

    assert me.sub == "ops"


@pytest.mark.unit
def test_require_admin_rejects_non_admin_even_with_admin_tenant(monkeypatch):
    monkeypatch.setattr(
        ph,
        "_me_from_access_token",
        lambda *_: types.SimpleNamespace(sub="bob", tenant_id="admin_bob"),
    )
    monkeypatch.setattr(
        ph,
        "_auth_store",
        types.SimpleNamespace(
            get_user=lambda _username: UserRecord(
                username="bob",
                password_hash="hash",
                tenant_id="admin_bob",
                role="user",
            )
        ),
    )

    with pytest.raises(HTTPException) as exc:
        ph._require_admin(token="t")

    assert exc.value.status_code == 403


@pytest.mark.unit
def test_admin_usage_routes_set_quota_and_report_summary(monkeypatch, tmp_path):
    usage = SQLiteUsageStore(db_path=str(tmp_path / "usage.db"))
    monkeypatch.setattr(pr, "_usage_store", usage)

    quota = pr.portal_set_admin_quota(
        AdminQuotaRequest(
            workspace_id="w1",
            user_id="alice",
            monthly_token_quota=20,
            enabled=True,
        ),
        me=_admin_me(),
    )
    assert quota["data"]["quota"]["monthly_token_quota"] == 20

    usage.record_usage(
        tenant_id="tenant_acme",
        workspace_id="w1",
        user_id="alice",
        agent_id="pm-minimal",
        model="gpt-test",
        input_tokens=5,
        output_tokens=7,
        status="success",
        month="2026-06",
        ts_s=1,
    )

    summary = pr.portal_admin_usage(workspace_id="w1", month="2026-06", me=_admin_me())

    assert summary["data"]["month"] == "2026-06"
    assert summary["data"]["items"][0]["user_id"] == "alice"
    assert summary["data"]["items"][0]["total_tokens"] == 12
    assert summary["data"]["items"][0]["remaining_tokens"] == 8
    assert summary["data"]["items"][0]["blocked"] is False


@pytest.mark.unit
def test_admin_quota_requires_positive_limit_when_enabled(monkeypatch, tmp_path):
    usage = SQLiteUsageStore(db_path=str(tmp_path / "usage.db"))
    monkeypatch.setattr(pr, "_usage_store", usage)

    with pytest.raises(HTTPException) as exc:
        pr.portal_set_admin_quota(
            AdminQuotaRequest(
                workspace_id="w1",
                user_id="alice",
                monthly_token_quota=0,
                enabled=True,
            ),
            me=_admin_me(),
        )

    assert exc.value.status_code == 400
    assert (
        usage.list_quotas(tenant_id="tenant_acme", workspace_id="w1", user_id="alice") == []
    )


class _FakeConversationStore:
    def get_recent(self, *_args, **_kwargs):
        return None

    def put(self, **_kwargs):
        return None


def _workspace_member_config() -> dict:
    return {
        "workspace_members": {
            "tenant_acme": {"w1": [{"user_id": "alice", "role": "member"}]}
        }
    }


@pytest.mark.unit
def test_chat_rejects_before_llm_when_quota_exceeded(monkeypatch, tmp_path):
    usage = SQLiteUsageStore(db_path=str(tmp_path / "usage.db"))
    usage.set_quota(
        tenant_id="tenant_acme",
        workspace_id="w1",
        user_id="alice",
        monthly_token_quota=1,
        enabled=True,
    )
    monkeypatch.setattr(cr, "_usage_store", usage)
    monkeypatch.setattr(
        cr,
        "_me_from_access_token",
        lambda *_: types.SimpleNamespace(sub="alice", tenant_id="tenant_acme"),
    )
    monkeypatch.setattr(cr, "_load_portal_config", _workspace_member_config)

    from agent_runtime.product import agent_gateway

    monkeypatch.setattr(
        agent_gateway,
        "create_azure_openai_client",
        lambda: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )

    req = ChatRequest(
        agent="pm-minimal",
        user_id="u_001",
        messages=[ChatMessage(role="user", content="hello world")],
    )

    with pytest.raises(HTTPException) as exc:
        cr.chat(
            req=req,
            request=types.SimpleNamespace(headers={}, state=types.SimpleNamespace()),
            token="t",
            workspace_id="w1",
            store=_FakeConversationStore(),
        )

    assert exc.value.status_code == 429


@pytest.mark.unit
def test_chat_stream_rejects_spoofed_user_id_when_authenticated_user_is_over_quota(monkeypatch, tmp_path):
    usage = SQLiteUsageStore(db_path=str(tmp_path / "usage.db"))
    usage.set_quota(
        tenant_id="tenant_acme",
        workspace_id="w1",
        user_id="alice",
        monthly_token_quota=1,
        enabled=True,
    )
    monkeypatch.setattr(cr, "_usage_store", usage)
    monkeypatch.setattr(
        cr,
        "_me_from_access_token",
        lambda *_: types.SimpleNamespace(sub="alice", tenant_id="tenant_acme"),
    )
    monkeypatch.setattr(cr, "_load_portal_config", _workspace_member_config)

    req = ChatRequest(
        agent="pm-minimal",
        user_id="u_001",
        messages=[ChatMessage(role="user", content="hello world")],
    )

    with pytest.raises(HTTPException) as exc:
        cr.chat_stream(
            req=req,
            request=types.SimpleNamespace(headers={}, state=types.SimpleNamespace()),
            token="t",
            workspace_id="w1",
            store=_FakeConversationStore(),
        )

    assert exc.value.status_code == 429


@pytest.mark.unit
def test_chat_records_usage_after_success(monkeypatch, tmp_path):
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
    monkeypatch.setattr(cr, "_scoped_memory_client", lambda **_kwargs: object())
    monkeypatch.setattr(cr, "_load_portal_config", _workspace_member_config)
    monkeypatch.setattr(cr, "_get_custom_agent_spec", lambda **_kwargs: None)

    from agent_runtime.product import agent_gateway

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

    monkeypatch.setattr(agent_gateway, "create_azure_openai_client", lambda: (object(), "gpt-test"))
    monkeypatch.setattr(agent_gateway, "_load_agent_class", lambda _agent: _Agent)

    req = ChatRequest(
        agent="pm-minimal",
        user_id="u_001",
        messages=[ChatMessage(role="user", content="hello world")],
    )
    resp = cr.chat(
        req=req,
        request=types.SimpleNamespace(headers={}, state=types.SimpleNamespace()),
        token="t",
        workspace_id="w1",
        store=_FakeConversationStore(),
    )

    rows = usage.list_usage_summary(
        tenant_id="tenant_acme", workspace_id="w1", month=None
    )
    assert resp.status == "success"
    assert rows[0].user_id == "alice"
    assert rows[0].total_tokens > 0
