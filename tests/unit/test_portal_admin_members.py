"""Tests for admin / workspace-member portal endpoints.

These endpoints gate admin RBAC and multi-tenant isolation.
"""
import types

import pytest
from fastapi import HTTPException

from agent_runtime.product.auth_store import InMemoryAuthStore
from agent_runtime.product.usage_store import SQLiteUsageStore
from agent_runtime.product.gateway import portal_routes as pr
from agent_runtime.product.gateway.models import AdminQuotaRequest, WorkspaceMemberRequest


def _admin_me():
    return types.SimpleNamespace(sub="admin", tenant_id="admin_t")


def _user_me(username="employee1", tenant_id="admin_t"):
    return types.SimpleNamespace(sub=username, tenant_id=tenant_id)


def _portal_store():
    """In-memory portal config store usable as load/save target."""
    return {"workspace_members": {}}


# ---------------------------------------------------------------------------
# delete_workspace: ws_default must be protected
# ---------------------------------------------------------------------------


def test_delete_default_workspace_is_rejected(monkeypatch):
    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _admin_me())

    with pytest.raises(HTTPException) as exc:
        pr.portal_delete_workspace("ws_default", me=_admin_me())
    assert exc.value.status_code == 400


def test_delete_non_default_workspace_removes_config(monkeypatch):
    tenant_id = _admin_me().tenant_id
    store = {
        "workspaces": {tenant_id: {"ws_x": {"id": "ws_x", "name": "DW Ops"}}},
        "tenant_workspace_mcp": {tenant_id: {"ws_x": {"some": "cfg"}}},
        "tenant_workspace_system_prompts": {tenant_id: {"ws_x": "prompt"}},
        "tenant_workspace_mcp_secrets": {tenant_id: {"ws_x": {"NEON_API_KEY": "x"}}},
        "workspace_tool_policies": {tenant_id: {"ws_x": {"allowlist": ["a"]}}},
        "custom_agents": {tenant_id: {"ws_x": {"a1": {"id": "a1"}}}},
        "workspace_members": {tenant_id: {"ws_x": [{"user_id": "employee1"}]}},
    }
    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _admin_me())
    monkeypatch.setattr(pr, "_load_portal_config", lambda: store)
    monkeypatch.setattr(pr, "_save_portal_config", lambda cfg: store.update(cfg))

    res = pr.portal_delete_workspace("ws_x", me=_admin_me())
    assert res["status"] == "success"
    assert "ws_x" not in store["workspaces"][tenant_id]
    assert "ws_x" not in store["tenant_workspace_mcp"][tenant_id]
    assert "ws_x" not in store["tenant_workspace_system_prompts"][tenant_id]
    assert "ws_x" not in store["tenant_workspace_mcp_secrets"][tenant_id]
    assert "ws_x" not in store["workspace_tool_policies"][tenant_id]
    assert "ws_x" not in store["custom_agents"][tenant_id]
    assert "ws_x" not in store["workspace_members"][tenant_id]


def test_workspace_config_ignores_root_level_workspace_fallbacks():
    cfg = {
        "workspace_mcp": {"ws_x": {"some": "cfg"}},
        "workspace_system_prompts": {"ws_x": "prompt"},
    }
    assert pr._workspace_mcp_for_tenant(cfg, tenant_id="admin_t", workspace_id="ws_x") == {}
    assert pr._workspace_prompt_for_tenant(cfg, tenant_id="admin_t", workspace_id="ws_x") is None


def test_tools_status_does_not_trigger_discovery(monkeypatch):
    store = {"tenant_workspace_mcp": {"admin_t": {"ws_x": {"mcp_http_url": "http://mcp.local"}}}}
    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _admin_me())
    monkeypatch.setattr(pr, "_load_portal_config", lambda: store)
    monkeypatch.setattr(pr, "_workspace_mcp_clients", lambda: {})
    monkeypatch.setattr(pr, "discover_tools_grouped", lambda: pytest.fail("discovery should be manual"))
    monkeypatch.setattr(pr, "discover_tools_from_mcp", lambda *_args, **_kwargs: pytest.fail("discovery should be manual"))

    res = pr.portal_tools_status(token="tok", workspace_id="ws_x")

    assert res["status"] == "success"
    assert res["tools"] == []
    assert res["data"]["workspace_saved"] is True
    assert res["data"]["tool_inventory_refresh_required"] is True


def test_tools_endpoint_uses_cache_until_refresh(monkeypatch):
    calls = {"count": 0}

    class _Tool:
        def to_metadata(self):
            return {
                "name": "local.echo",
                "category": "local",
                "schema": {"description": "Echo"},
                "spec": "test:echo",
            }

    def _discover():
        calls["count"] += 1
        return {"local": {"local.echo": _Tool()}}

    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: _admin_me())
    monkeypatch.setattr(pr, "_load_portal_config", lambda: {})
    monkeypatch.setattr(pr, "_workspace_mcp_clients", lambda: {})
    monkeypatch.setattr(pr, "_build_mcp_clients_from_workspace_config", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pr, "discover_tools_grouped", _discover)
    pr._TOOLS_DISCOVERY_CACHE.clear()

    cold = pr.portal_list_tools(token="tok", workspace_id="ws_x", refresh=False)
    assert cold["data"] == {}
    assert cold["discovery"]["refresh_required"] is True
    assert calls["count"] == 0

    refreshed = pr.portal_list_tools(token="tok", workspace_id="ws_x", refresh=True)
    assert "local" in refreshed["data"]
    assert calls["count"] == 1

    cached = pr.portal_list_tools(token="tok", workspace_id="ws_x", refresh=False)
    assert "local" in cached["data"]
    assert cached["discovery"]["cached"] is True
    assert calls["count"] == 1


def test_workspace_access_allows_default_workspace_for_same_tenant(monkeypatch):
    from agent_runtime.product.gateway import portal_helpers as ph

    monkeypatch.setattr(ph, "_role_for_me", lambda _me: "user")
    ctx = ph._assert_workspace_access(
        _user_me(username="alice", tenant_id="tenant_a"),
        "ws_default",
        cfg={},
    )
    assert ctx["workspace_id"] == "ws_default"
    assert ctx["role"] == "user"


def test_workspace_access_rejects_non_member_workspace(monkeypatch):
    from agent_runtime.product.gateway import portal_helpers as ph

    monkeypatch.setattr(ph, "_role_for_me", lambda _me: "user")
    cfg = {"workspace_members": {"tenant_a": {"ws_private": []}}}

    with pytest.raises(HTTPException) as exc:
        ph._assert_workspace_access(
            _user_me(username="alice", tenant_id="tenant_a"),
            "ws_private",
            cfg=cfg,
        )

    assert exc.value.status_code == 403


def test_workspace_access_allows_explicit_member(monkeypatch):
    from agent_runtime.product.gateway import portal_helpers as ph

    monkeypatch.setattr(ph, "_role_for_me", lambda _me: "user")
    cfg = {
        "workspace_members": {
            "tenant_a": {
                "ws_private": [{"user_id": "alice", "role": "member"}]
            }
        }
    }

    ctx = ph._assert_workspace_access(
        _user_me(username="alice", tenant_id="tenant_a"),
        "ws_private",
        cfg=cfg,
    )
    assert ctx["member_role"] == "member"


def test_workspace_owner_can_apply_mcp_but_plain_member_cannot(monkeypatch):
    from agent_runtime.product.gateway import portal_helpers as ph

    monkeypatch.setattr(ph, "_role_for_me", lambda _me: "user")
    cfg = {
        "workspace_members": {
            "tenant_a": {
                "ws_private": [
                    {"user_id": "owner1", "role": "owner"},
                    {"user_id": "member1", "role": "member"},
                ]
            }
        }
    }

    owner_ctx = ph._assert_workspace_access(
        _user_me(username="owner1", tenant_id="tenant_a"),
        "ws_private",
        cfg=cfg,
        write=True,
        allow_owner_write=True,
    )
    assert owner_ctx["member_role"] == "owner"

    with pytest.raises(HTTPException) as exc:
        ph._assert_workspace_access(
            _user_me(username="member1", tenant_id="tenant_a"),
            "ws_private",
            cfg=cfg,
            write=True,
            allow_owner_write=True,
        )
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# workspace members: add (insert + update), list, delete (incl. 404)
# ---------------------------------------------------------------------------


def test_add_member_then_list(monkeypatch):
    store = _portal_store()
    monkeypatch.setattr(pr, "_load_portal_config", lambda: store)
    monkeypatch.setattr(pr, "_save_portal_config", lambda cfg: store.update(cfg))
    monkeypatch.setattr(
        pr, "_workspace_members_for_tenant", pr._workspace_members_for_tenant
    )
    monkeypatch.setattr(pr, "_save_workspace_members", pr._save_workspace_members)

    added = pr.portal_add_workspace_member(
        "ws_x",
        WorkspaceMemberRequest(user_id="u1", role="member"),
        me=_admin_me(),
    )
    assert added["status"] == "success"
    assert any(m["user_id"] == "u1" for m in added["members"])

    listed = pr.portal_list_workspace_members("ws_x", me=_admin_me())
    assert listed["status"] == "success"
    assert any(m["user_id"] == "u1" for m in listed["members"])
    assert store["workspaces"][_admin_me().tenant_id]["ws_x"]["id"] == "ws_x"


def test_add_member_updates_existing_role(monkeypatch):
    store = _portal_store()
    monkeypatch.setattr(pr, "_load_portal_config", lambda: store)
    monkeypatch.setattr(pr, "_save_portal_config", lambda cfg: store.update(cfg))
    monkeypatch.setattr(
        pr, "_workspace_members_for_tenant", pr._workspace_members_for_tenant
    )
    monkeypatch.setattr(pr, "_save_workspace_members", pr._save_workspace_members)

    pr.portal_add_workspace_member(
        "ws_x", WorkspaceMemberRequest(user_id="u1", role="member"), me=_admin_me()
    )
    res = pr.portal_add_workspace_member(
        "ws_x", WorkspaceMemberRequest(user_id="u1", role="admin"), me=_admin_me()
    )
    matches = [m for m in res["members"] if m["user_id"] == "u1"]
    assert len(matches) == 1  # no duplicate
    assert matches[0]["role"] == "admin"  # role updated in place


def test_add_member_requires_user_id(monkeypatch):
    store = _portal_store()
    monkeypatch.setattr(pr, "_load_portal_config", lambda: store)
    monkeypatch.setattr(
        pr, "_workspace_members_for_tenant", pr._workspace_members_for_tenant
    )

    with pytest.raises(HTTPException) as exc:
        pr.portal_add_workspace_member(
            "ws_x", WorkspaceMemberRequest(user_id="  ", role="member"), me=_admin_me()
        )
    assert exc.value.status_code == 400


def test_delete_member_removes_and_404_on_missing(monkeypatch):
    store = _portal_store()
    monkeypatch.setattr(pr, "_load_portal_config", lambda: store)
    monkeypatch.setattr(pr, "_save_portal_config", lambda cfg: store.update(cfg))
    monkeypatch.setattr(
        pr, "_workspace_members_for_tenant", pr._workspace_members_for_tenant
    )
    monkeypatch.setattr(pr, "_save_workspace_members", pr._save_workspace_members)

    pr.portal_add_workspace_member(
        "ws_x", WorkspaceMemberRequest(user_id="u1", role="member"), me=_admin_me()
    )

    res = pr.portal_delete_workspace_member("ws_x", "u1", me=_admin_me())
    assert res["status"] == "success"
    assert all(m["user_id"] != "u1" for m in res["members"])

    with pytest.raises(HTTPException) as exc:
        pr.portal_delete_workspace_member("ws_x", "nope", me=_admin_me())
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# admin user management: create employees/admins inside tenant scope
# ---------------------------------------------------------------------------


def test_admin_create_user_defaults_to_current_tenant(monkeypatch):
    auth_store = InMemoryAuthStore()
    monkeypatch.setattr(pr, "_get_auth_store", lambda: auth_store)
    monkeypatch.setattr(pr._obs_store, "record_audit", lambda *_args, **_kwargs: None)

    res = pr.portal_create_admin_user(
        pr.AdminUserCreateRequest(username="employee1", password="password123", role="user"),
        me=_admin_me(),
    )

    assert res["status"] == "success"
    assert res["data"].id == "employee1"
    assert res["data"].tenant_id == _admin_me().tenant_id
    assert res["data"].role == "user"
    assert auth_store.authenticate(username="employee1", password="password123")


def test_admin_create_user_rejects_duplicate_and_bad_role(monkeypatch):
    auth_store = InMemoryAuthStore()
    auth_store.create_user(
        username="employee1",
        password="password123",
        tenant_id=_admin_me().tenant_id,
        role="user",
    )
    monkeypatch.setattr(pr, "_get_auth_store", lambda: auth_store)

    with pytest.raises(HTTPException) as duplicate:
        pr.portal_create_admin_user(
            pr.AdminUserCreateRequest(username="employee1", password="password123", role="user"),
            me=_admin_me(),
        )
    assert duplicate.value.status_code == 400

    with pytest.raises(HTTPException) as bad_role:
        pr.portal_create_admin_user(
            pr.AdminUserCreateRequest(username="employee2", password="password123", role="owner"),
            me=_admin_me(),
        )
    assert bad_role.value.status_code == 400


def test_tenant_admin_update_user_role_same_tenant(monkeypatch):
    auth_store = InMemoryAuthStore()
    auth_store.create_user(
        username="employee1",
        password="password123",
        tenant_id=_admin_me().tenant_id,
        role="user",
    )
    monkeypatch.setattr(pr, "_get_auth_store", lambda: auth_store)
    monkeypatch.setattr(pr._obs_store, "record_audit", lambda *_args, **_kwargs: None)

    res = pr.portal_update_admin_user(
        "employee1",
        pr.AdminUserUpdateRequest(role="admin"),
        me=_admin_me(),
    )

    assert res["status"] == "success"
    assert res["data"].role == "admin"
    assert res["data"].tenant_id == _admin_me().tenant_id
    assert auth_store.get_user("employee1").role == "admin"


def test_tenant_admin_cannot_move_user_to_other_tenant(monkeypatch):
    auth_store = InMemoryAuthStore()
    auth_store.create_user(
        username="employee1",
        password="password123",
        tenant_id=_admin_me().tenant_id,
        role="user",
    )
    monkeypatch.setattr(pr, "_get_auth_store", lambda: auth_store)

    with pytest.raises(HTTPException) as exc:
        pr.portal_update_admin_user(
            "employee1",
            pr.AdminUserUpdateRequest(tenant_id="tenant_other"),
            me=_admin_me(),
        )

    assert exc.value.status_code == 403


def test_admin_update_user_protects_current_admin(monkeypatch):
    auth_store = InMemoryAuthStore()
    auth_store.create_user(
        username="admin",
        password="password123",
        tenant_id=_admin_me().tenant_id,
        role="admin",
    )
    monkeypatch.setattr(pr, "_get_auth_store", lambda: auth_store)

    with pytest.raises(HTTPException) as exc:
        pr.portal_update_admin_user(
            "admin",
            pr.AdminUserUpdateRequest(role="user"),
            me=_admin_me(),
        )

    assert exc.value.status_code == 400


def test_admin_reset_user_password_updates_login_and_revokes_refresh(monkeypatch):
    auth_store = InMemoryAuthStore()
    auth_store.create_user(
        username="employee1",
        password="password123",
        tenant_id=_admin_me().tenant_id,
        role="user",
    )
    refresh_token = auth_store.issue_refresh(
        username="employee1",
        tenant_id=_admin_me().tenant_id,
        family_id="family1",
    )
    monkeypatch.setattr(pr, "_get_auth_store", lambda: auth_store)
    monkeypatch.setattr(pr._obs_store, "record_audit", lambda *_args, **_kwargs: None)

    res = pr.portal_reset_admin_user_password(
        "employee1",
        pr.AdminUserPasswordResetRequest(new_password="newpw123"),
        me=_admin_me(),
    )

    assert res["status"] == "success"
    assert res["data"]["revoked_refresh_tokens"] == 1
    assert not auth_store.authenticate(username="employee1", password="password123")
    assert auth_store.authenticate(username="employee1", password="newpw123")
    with pytest.raises(ValueError):
        auth_store.validate_and_rotate_refresh(refresh_token)


def test_admin_reset_user_password_rejects_self(monkeypatch):
    auth_store = InMemoryAuthStore()
    auth_store.create_user(
        username="admin",
        password="password123",
        tenant_id=_admin_me().tenant_id,
        role="admin",
    )
    monkeypatch.setattr(pr, "_get_auth_store", lambda: auth_store)

    with pytest.raises(HTTPException) as exc:
        pr.portal_reset_admin_user_password(
            "admin",
            pr.AdminUserPasswordResetRequest(new_password="newpw123"),
            me=_admin_me(),
        )

    assert exc.value.status_code == 400


def test_admin_delete_user_removes_login_and_quotas(monkeypatch, tmp_path):
    auth_store = InMemoryAuthStore()
    auth_store.create_user(
        username="admin2",
        password="password123",
        tenant_id=_admin_me().tenant_id,
        role="admin",
    )
    auth_store.create_user(
        username="employee1",
        password="password123",
        tenant_id=_admin_me().tenant_id,
        role="user",
    )
    usage_store = SQLiteUsageStore(db_path=str(tmp_path / "usage.db"))
    usage_store.set_quota(
        tenant_id=_admin_me().tenant_id,
        workspace_id="ws_default",
        user_id="employee1",
        monthly_token_quota=100,
        enabled=True,
    )
    cfg = {
        "workspace_members": {
            _admin_me().tenant_id: {
                "ws_default": [{"user_id": "employee1", "role": "member"}]
            }
        }
    }
    monkeypatch.setattr(pr, "_get_auth_store", lambda: auth_store)
    monkeypatch.setattr(pr, "_usage_store", usage_store)
    monkeypatch.setattr(pr, "_load_portal_config", lambda: cfg)
    monkeypatch.setattr(pr, "_save_portal_config", lambda updated: cfg.update(updated))
    monkeypatch.setattr(pr._obs_store, "record_audit", lambda *_args, **_kwargs: None)

    res = pr.portal_delete_admin_user("employee1", me=_admin_me())

    assert res["status"] == "success"
    assert auth_store.get_user("employee1") is None
    assert usage_store.list_quotas(tenant_id=_admin_me().tenant_id, user_id="employee1") == []
    assert cfg["workspace_members"][_admin_me().tenant_id]["ws_default"] == []


def test_admin_delete_user_rejects_self(monkeypatch):
    auth_store = InMemoryAuthStore()
    auth_store.create_user(
        username="admin",
        password="password123",
        tenant_id=_admin_me().tenant_id,
        role="admin",
    )
    monkeypatch.setattr(pr, "_get_auth_store", lambda: auth_store)

    with pytest.raises(HTTPException) as exc:
        pr.portal_delete_admin_user("admin", me=_admin_me())

    assert exc.value.status_code == 400


def test_tenant_admin_quota_is_limited_to_own_tenant(monkeypatch, tmp_path):
    usage_store = SQLiteUsageStore(db_path=str(tmp_path / "usage.db"))
    monkeypatch.setattr(pr, "_usage_store", usage_store)
    monkeypatch.setattr(pr._obs_store, "record_audit", lambda *_args, **_kwargs: None)

    res = pr.portal_set_admin_quota(
        AdminQuotaRequest(
            tenant_id=_admin_me().tenant_id,
            workspace_id="ws_default",
            user_id="employee1",
            monthly_token_quota=100,
            enabled=True,
        ),
        me=_admin_me(),
    )

    assert res["status"] == "success"
    assert res["data"]["quota"]["tenant_id"] == _admin_me().tenant_id
    listed = pr.portal_list_admin_quotas(
        tenant_id=_admin_me().tenant_id,
        workspace_id="ws_default",
        user_id="employee1",
        me=_admin_me(),
    )
    assert listed["data"]["total"] == 1

    with pytest.raises(HTTPException) as exc:
        pr.portal_set_admin_quota(
            AdminQuotaRequest(
                tenant_id="tenant_other",
                workspace_id="ws_default",
                user_id="employee1",
                monthly_token_quota=100,
                enabled=True,
            ),
            me=_admin_me(),
        )
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# admin RBAC: _require_admin rejects non-admin tenants
# ---------------------------------------------------------------------------


def test_require_admin_rejects_non_admin(monkeypatch):
    from agent_runtime.product.gateway import portal_helpers as ph

    monkeypatch.setattr(
        ph,
        "_me_from_access_token",
        lambda *_: types.SimpleNamespace(sub="bob", tenant_id="t_bob"),
    )
    with pytest.raises(HTTPException) as exc:
        ph._require_admin(token="t")
    assert exc.value.status_code == 403


def test_require_admin_accepts_admin(monkeypatch):
    from agent_runtime.product.gateway import portal_helpers as ph

    monkeypatch.setattr(
        ph,
        "_me_from_access_token",
        lambda *_: types.SimpleNamespace(sub="root", tenant_id="admin_root"),
    )
    me = ph._require_admin(token="t")
    assert me.tenant_id == "admin_root"
