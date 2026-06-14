import types
import json

import pytest
from fastapi import HTTPException

from agent_runtime.product.gateway import portal_routes as pr
from agent_runtime.product.gateway import portal_helpers as ph
from agent_runtime.product.gateway.models import (
    FileFirstReadProxyRequest,
    PortalAgentUpsertRequest,
    ToolPolicyRequest,
    WorkspaceConfigRequest,
    WorkspaceSecretsRequest,
)
from agent_runtime.product.observability import InMemoryObservabilityStore, AuditEvent, MetricPoint


class _DummyTool:
    def __init__(self, name="tool"):
        self._name = name

    def to_metadata(self):
        return {"name": self._name}


def _fake_me():
    return types.SimpleNamespace(sub="admin", tenant_id="admin_t")


def test_portal_list_tools_grouped(monkeypatch):
    pr._TOOLS_DISCOVERY_CACHE.clear()
    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _fake_me())
    monkeypatch.setattr(pr, "_workspace_mcp_clients", lambda: {})
    monkeypatch.setattr(pr, "_build_mcp_clients_from_workspace_config", lambda *_: {})
    monkeypatch.setattr(pr, "discover_tools_grouped", lambda: {"ns": {"t": _DummyTool()}})

    result = pr.portal_list_tools(token="t", workspace_id="w", refresh=True)
    assert result["status"] == "success"
    assert "ns" in result["data"]


def test_portal_list_tools_mcp(monkeypatch):
    pr._TOOLS_DISCOVERY_CACHE.clear()
    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _fake_me())
    monkeypatch.setattr(pr, "_workspace_mcp_clients", lambda: {})
    monkeypatch.setattr(
        pr, "_build_mcp_clients_from_workspace_config", lambda *a, **k: {"ns": object()}
    )
    monkeypatch.setattr(
        pr, "discover_tools_from_mcp", lambda *_, **__: {"t": _DummyTool("t")}
    )

    result = pr.portal_list_tools(token="t", workspace_id="w", refresh=True)
    assert result["status"] == "success"
    assert result["data"]["ns"][0]["name"] == "t"


def test_portal_agents_upsert_and_delete(monkeypatch):
    store = {"custom_agents": {}}
    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _fake_me())
    monkeypatch.setattr(pr, "_load_portal_config", lambda: store)
    monkeypatch.setattr(pr, "_save_portal_config", lambda cfg: store.update(cfg))
    monkeypatch.setattr(pr, "_save_custom_agent", pr._save_custom_agent)
    monkeypatch.setattr(pr, "_delete_custom_agent", pr._delete_custom_agent)
    monkeypatch.setattr(pr, "_custom_agents_for_tenant", pr._custom_agents_for_tenant)

    req = PortalAgentUpsertRequest(id="a1", name="Agent", description=None, system_prompt="hi", tools=[])
    res = pr.portal_upsert_agent(req, token="t", workspace_id="w")
    assert res["status"] == "success"

    res = pr.portal_delete_agent("a1", token="t", workspace_id="w")
    assert res["status"] == "success"


def test_portal_agent_upsert_rejects_body_workspace_mismatch(monkeypatch):
    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _fake_me())

    req = PortalAgentUpsertRequest(
        id="a1",
        name="Agent",
        description=None,
        system_prompt="hi",
        tools=[],
        workspace_id="ws_b",
    )

    with pytest.raises(HTTPException) as exc:
        pr.portal_upsert_agent(req, token="t", workspace_id="ws_a")

    assert exc.value.status_code == 400
    assert "x-workspace-id" in exc.value.detail


def test_portal_tool_policy(monkeypatch):
    store = {}
    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _fake_me())
    monkeypatch.setattr(pr, "_load_portal_config", lambda: store)
    monkeypatch.setattr(pr, "_save_portal_config", lambda cfg: store.update(cfg))

    req = ToolPolicyRequest(allowlist=["a"], denylist=[], overrides={})
    res = pr.portal_set_tool_policy(req, token="t", workspace_id="w")
    assert res["status"] == "success"

    res = pr.portal_get_tool_policy(token="t", workspace_id="w")
    assert res["data"]["allowlist"] == ["a"]


def test_portal_tools_status_reports_saved_and_applied_mcp(monkeypatch):
    pr._TOOLS_DISCOVERY_CACHE.clear()
    store = {
        "tenant_workspace_mcp": {
            "admin_t": {
                "w": {
                    "mcp_servers_json": '[{"transport":"stdio","command":"python"}]'
                }
            }
        }
    }
    clients = {"admin_t:w": {"memory": object()}}

    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _fake_me())
    monkeypatch.setattr(pr, "_load_portal_config", lambda: store)
    monkeypatch.setattr(pr, "_workspace_mcp_clients", lambda: clients)
    monkeypatch.setattr(
        pr, "discover_tools_from_mcp", lambda *_, **__: {"t": _DummyTool("memory.t")}
    )

    pr.portal_list_tools(token="t", workspace_id="w", refresh=True)
    res = pr.portal_tools_status(token="t", workspace_id="w")

    assert res["status"] == "success"
    assert res["data"]["workspace_configured"] is True
    assert res["data"]["workspace_saved"] is True
    assert res["data"]["workspace_applied"] is True
    assert res["tools"][0]["name"] == "memory.t"


def test_portal_tools_status_redacts_operator_mcp_environment(monkeypatch):
    monkeypatch.setenv(
        "AGENT_MEMORY_MCP_SERVERS",
        '[{"headers":{"Authorization":"Bearer super-secret-token-value"}}]',
    )
    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _fake_me())
    monkeypatch.setattr(pr, "_load_portal_config", lambda: {})
    monkeypatch.setattr(pr, "_workspace_mcp_clients", lambda: {})

    res = pr.portal_tools_status(token="t", workspace_id="w")

    assert res["data"]["env"]["AGENT_MEMORY_MCP_SERVERS"] is True
    assert "super-secret-token-value" not in json.dumps(res)


def test_portal_workspace_config_preserves_nested_mcp_namespace(monkeypatch):
    store = {}

    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _fake_me())
    monkeypatch.setattr(pr, "_load_portal_config", lambda: store)
    monkeypatch.setattr(pr, "_save_portal_config", lambda cfg: store.update(cfg))

    req = WorkspaceConfigRequest(
        mcp={
            "mcp_http_url": "http://127.0.0.1:8787/mcp",
            "mcp_http_namespace": "custom",
            "mcp_http_headers_json": "{}",
        }
    )
    res = pr.portal_set_workspace_config(req, token="t", workspace_id="w")

    saved = res["data"]["saved"]["mcp"]
    assert saved["mcp_http_namespace"] == "custom"
    assert (
        store["tenant_workspace_mcp"]["admin_t"]["w"]["mcp_http_namespace"]
        == "custom"
    )


def test_portal_workspace_config_extracts_inline_mcp_secret(monkeypatch):
    store = {}

    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _fake_me())
    monkeypatch.setattr(pr, "_load_portal_config", lambda: store)
    monkeypatch.setattr(pr, "_save_portal_config", lambda cfg: store.update(cfg))

    req = WorkspaceConfigRequest(
        mcp={
            "mcp_http_url": "https://mcp.context7.com/mcp",
            "mcp_http_namespace": "context7",
            "mcp_http_headers_json": json.dumps(
                {"CONTEXT7_API_KEY": "example-context7-value"}
            ),
        }
    )
    res = pr.portal_set_workspace_config(req, token="t", workspace_id="w")

    saved = res["data"]["saved"]["mcp"]
    assert json.loads(saved["mcp_http_headers_json"]) == {
        "CONTEXT7_API_KEY": "${CONTEXT7_API_KEY}"
    }
    assert (
        json.loads(
            store["tenant_workspace_mcp"]["admin_t"]["w"]["mcp_http_headers_json"]
        )
        == {"CONTEXT7_API_KEY": "${CONTEXT7_API_KEY}"}
    )


def test_workspace_mcp_does_not_expand_process_environment(monkeypatch):
    store = {
        "tenant_workspace_mcp": {
            "admin_t": {
                "w": {
                    "mcp_servers_json": json.dumps(
                        [
                            {
                                "namespace": "unsafe",
                                "transport": "stdio",
                                "command": "python",
                                "args": ["-m", "server", "${DOCS_PROFILE}"],
                            }
                        ]
                    )
                }
            }
        }
    }
    monkeypatch.setenv("DOCS_PROFILE", "should-not-leak")
    monkeypatch.setattr(ph, "_load_portal_config", lambda: store)

    clients = ph._build_mcp_clients_from_workspace_config("w", tenant_id="admin_t")

    assert clients == {}


def test_workspace_mcp_does_not_use_operator_fallback_by_default(monkeypatch):
    monkeypatch.setenv(
        "AGENT_MEMORY_MCP_SERVERS",
        '[{"transport":"http","namespace":"operator","url":"https://mcp.context7.com/mcp"}]',
    )
    monkeypatch.delenv("AGENT_WORKSPACE_MCP_USE_OPERATOR_FALLBACK", raising=False)
    monkeypatch.setattr(ph, "_load_portal_config", lambda: {})

    clients = ph._build_mcp_clients_from_workspace_config("w", tenant_id="admin_t")

    assert clients == {}


def test_workspace_mcp_http_rejects_private_network_url(monkeypatch):
    store = {
        "tenant_workspace_mcp": {
            "admin_t": {
                "w": {
                    "mcp_http_url": "http://127.0.0.1:8787/mcp",
                    "mcp_http_namespace": "local",
                }
            }
        }
    }
    monkeypatch.setattr(ph, "_load_portal_config", lambda: store)

    with pytest.raises(HTTPException) as exc:
        ph._build_mcp_clients_from_workspace_config("w", tenant_id="admin_t")

    assert exc.value.status_code == 400


def test_workspace_mcp_http_allows_explicit_allowlisted_host(monkeypatch):
    store = {
        "tenant_workspace_mcp": {
            "admin_t": {
                "w": {
                    "mcp_http_url": "https://mcp.context7.com/mcp",
                    "mcp_http_namespace": "context7",
                    "mcp_http_headers_json": json.dumps(
                        {"CONTEXT7_API_KEY": "${CONTEXT7_API_KEY}"}
                    ),
                }
            }
        },
        "tenant_workspace_mcp_secrets": {"admin_t": {"w": {}}},
    }
    monkeypatch.setattr(ph, "_load_portal_config", lambda: store)
    monkeypatch.setattr(
        ph,
        "_workspace_mcp_secrets_for_tenant",
        lambda *_args, **_kwargs: {"CONTEXT7_API_KEY": "tenant-secret"},
    )

    clients = ph._build_mcp_clients_from_workspace_config("w", tenant_id="admin_t")

    assert sorted(clients) == ["context7"]


def test_portal_workspace_secrets_are_status_only(monkeypatch):
    store = {}
    clients = {"admin_t:w": object()}

    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _fake_me())
    monkeypatch.setattr(pr, "_load_portal_config", lambda: store)
    monkeypatch.setattr(pr, "_save_portal_config", lambda cfg: store.update(cfg))
    monkeypatch.setattr(pr, "_workspace_mcp_clients", lambda: clients)

    req = WorkspaceSecretsRequest(values={"NEON_API_KEY": "neon-secret"}, clear=[])
    saved = pr.portal_set_workspace_secrets(req, token="t", workspace_id="w")

    assert saved["data"]["configured"] == {"NEON_API_KEY": True}
    assert "neon-secret" not in str(saved)
    stored = store["tenant_workspace_mcp_secrets"]["admin_t"]["w"]["NEON_API_KEY"]
    assert isinstance(stored, dict)
    assert stored["alg"] == "fernet-sha256"
    assert "neon-secret" not in json.dumps(store)
    assert ph._workspace_mcp_secrets_for_tenant(
        store, tenant_id="admin_t", workspace_id="w"
    ) == {"NEON_API_KEY": "neon-secret"}
    assert clients == {}

    listed = pr.portal_get_workspace_secrets(token="t", workspace_id="w")
    assert listed["data"]["configured"] == {"NEON_API_KEY": True}
    assert listed["data"]["names"] == ["NEON_API_KEY"]
    assert "neon-secret" not in str(listed)


def test_portal_workspace_secret_names_are_validated(monkeypatch):
    store = {}

    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _fake_me())
    monkeypatch.setattr(pr, "_load_portal_config", lambda: store)

    req = WorkspaceSecretsRequest(values={"bad-name": "secret"}, clear=[])
    with pytest.raises(HTTPException) as exc:
        pr.portal_set_workspace_secrets(req, token="t", workspace_id="w")

    assert exc.value.status_code == 400
    assert "secret names" in exc.value.detail


def test_workspace_secret_key_required_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("PORTAL_SECRETS_KEY", raising=False)
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)

    with pytest.raises(HTTPException) as exc:
        ph._encrypt_workspace_secret("secret")

    assert exc.value.status_code == 500
    assert "PORTAL_SECRETS_KEY" in exc.value.detail


def test_workspace_secret_key_must_not_reuse_jwt_secret_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "same-secret")
    monkeypatch.setenv("PORTAL_SECRETS_KEY", "same-secret")

    with pytest.raises(HTTPException) as exc:
        ph._encrypt_workspace_secret("secret")

    assert exc.value.status_code == 500
    assert "distinct" in exc.value.detail


def test_build_mcp_clients_resolves_http_headers_from_workspace_secret(monkeypatch):
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    store = {
        "tenant_workspace_mcp": {
            "admin_t": {
                "w": {
                    "mcp_servers_json": (
                        '[{"transport":"http","namespace":"neon",'
                        '"url":"https://mcp.neon.tech/mcp",'
                        '"headers":{"Authorization":"Bearer ${NEON_API_KEY}"}}]'
                    )
                }
            }
        },
        "tenant_workspace_mcp_secrets": {
            "admin_t": {"w": {"NEON_API_KEY": "workspace-neon-token"}}
        },
    }

    monkeypatch.setattr(ph, "_load_portal_config", lambda: store)

    clients = ph._build_mcp_clients_from_workspace_config("w", tenant_id="admin_t")

    assert clients["neon"]._server.headers == {
        "Authorization": "Bearer workspace-neon-token"
    }


def test_workspace_stdio_mcp_rejects_basename_path_bypass(monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_MCP_STDIO_ENABLED", "1")
    monkeypatch.setenv("AGENT_WORKSPACE_MCP_STDIO_ALLOWED_COMMANDS", "python")

    with pytest.raises(HTTPException) as exc:
        ph._validate_workspace_mcp_stdio_command("/tmp/evil/python")

    assert exc.value.status_code == 400


def test_workspace_stdio_mcp_rejects_secret_args(monkeypatch):
    store = {
        "tenant_workspace_mcp": {
            "admin_t": {
                "w": {
                    "mcp_servers_json": json.dumps(
                        [
                            {
                                "namespace": "unsafe",
                                "transport": "stdio",
                                "command": "python",
                                "args": ["--api-key", "${NEON_API_KEY}"],
                            }
                        ]
                    )
                }
            }
        },
        "tenant_workspace_mcp_secrets": {
            "admin_t": {"w": {"NEON_API_KEY": "workspace-token"}}
        },
    }
    monkeypatch.setenv("AGENT_WORKSPACE_MCP_STDIO_ENABLED", "1")
    monkeypatch.setenv("AGENT_WORKSPACE_MCP_STDIO_ALLOWED_COMMANDS", "python")
    monkeypatch.setattr(ph, "_load_portal_config", lambda: store)

    with pytest.raises(HTTPException) as exc:
        ph._build_mcp_clients_from_workspace_config("w", tenant_id="admin_t")

    assert exc.value.status_code == 400
    assert "command args" in exc.value.detail


def test_portal_metrics_and_audit(monkeypatch):
    obs = InMemoryObservabilityStore()
    obs.record_metric(
        MetricPoint(ts_s=1, tenant_id="admin_t", workspace_id="w", name="metric", value=1.0, tags={})
    )
    obs.record_audit(
        AuditEvent(ts_s=1, tenant_id="admin_t", workspace_id="w", actor="u", action="act", resource="res", ok=True)
    )

    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _fake_me())
    monkeypatch.setattr(pr, "_obs_store", obs)

    metrics = pr.portal_metrics(token="t", workspace_id="w")
    assert metrics["data"]["total"] == 1

    audit = pr.portal_audit(token="t", workspace_id="w")
    assert audit["data"]["total"] == 1


def test_portal_monitoring_exports_require_workspace_access(monkeypatch):
    user = types.SimpleNamespace(sub="alice", tenant_id="tenant_a")
    store = {"workspace_members": {"tenant_a": {"ws_private": []}}}

    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: user)
    monkeypatch.setattr(ph, "_role_for_me", lambda _me: "user")
    monkeypatch.setattr(ph, "_load_portal_config", lambda: store)

    with pytest.raises(HTTPException) as metrics_exc:
        pr.portal_metrics_export(token="t", workspace_id="ws_private")
    with pytest.raises(HTTPException) as audit_exc:
        pr.portal_audit_export(token="t", workspace_id="ws_private")

    assert metrics_exc.value.status_code == 403
    assert audit_exc.value.status_code == 403


def test_portal_memory_read_rejects_cross_user_preferences(monkeypatch):
    user = types.SimpleNamespace(sub="alice", tenant_id="tenant_a")

    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: user)
    monkeypatch.setattr(ph, "_role_for_me", lambda _me: "user")
    monkeypatch.setattr(pr, "get_config", lambda: types.SimpleNamespace(memory_service_url="http://mem"))

    req = FileFirstReadProxyRequest(
        tier="preferences",
        user_id="bob",
    )

    with pytest.raises(HTTPException) as exc:
        pr.portal_memory_read(req, token="t", workspace_id="ws_default")

    assert exc.value.status_code == 403


def test_portal_memory_read_defaults_preferences_to_authenticated_user(monkeypatch):
    user = types.SimpleNamespace(sub="alice", tenant_id="tenant_a")
    called = {}

    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: user)
    monkeypatch.setattr(ph, "_role_for_me", lambda _me: "user")
    monkeypatch.setattr(pr, "get_config", lambda: types.SimpleNamespace(memory_service_url="http://mem"))

    class _FakeClient:
        def __init__(self, base_url: str):
            called["base_url"] = base_url

        def with_scope(self, *, tenant_id: str, workspace_id: str):
            called["scope"] = (tenant_id, workspace_id)
            return self

        def with_actor(self, *, actor_user_id: str, actor_role: str):
            called["actor"] = (actor_user_id, actor_role)
            return self

        def memory_read(self, **kwargs):
            called["read"] = kwargs
            return {"status": "success", "data": {}}

    monkeypatch.setattr(pr, "MemoryClient", _FakeClient)

    req = FileFirstReadProxyRequest(tier="preferences")
    res = pr.portal_memory_read(req, token="t", workspace_id="ws_default")

    assert res["status"] == "success"
    assert called["read"]["user_id"] == "alice"
    assert called["actor"] == ("alice", "user")


def test_portal_memory_index_rebuild(monkeypatch):
    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _fake_me())
    monkeypatch.setattr(pr, "get_config", lambda: types.SimpleNamespace(memory_service_url="http://mem"))

    called = {}

    class _FakeClient:
        def __init__(self, base_url: str):
            called["base_url"] = base_url

        def with_scope(self, *, tenant_id: str, workspace_id: str):
            called["tenant_id"] = tenant_id
            called["workspace_id"] = workspace_id
            return self

        def memory_index_rebuild(self, *, tenant_id: str, workspace_id: str):
            called["rebuild_args"] = (tenant_id, workspace_id)
            return {"status": "success", "data": {"rebuilt": True}}

    monkeypatch.setattr(pr, "MemoryClient", _FakeClient)

    res = pr.portal_memory_index_rebuild(token="t", workspace_id="w", req=None)
    assert res["status"] == "success"
    assert called["base_url"] == "http://mem"
    assert called["rebuild_args"] == ("admin_t", "w")


def test_portal_memory_stats_rejects_unlisted_memory_url(monkeypatch):
    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _fake_me())
    monkeypatch.setattr(
        pr,
        "get_config",
        lambda: types.SimpleNamespace(memory_service_url="http://mem"),
    )

    req = pr.PortalMemoryStatsRequest(memory_url="http://169.254.169.254")

    with pytest.raises(HTTPException) as exc:
        pr.portal_memory_stats(req=req, token="t", workspace_id="w")

    assert exc.value.status_code == 400
    assert "memory_url override is not allowed" in exc.value.detail
