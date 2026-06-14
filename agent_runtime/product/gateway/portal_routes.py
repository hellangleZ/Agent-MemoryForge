# -*- coding: utf-8 -*-
"""Portal (admin/customer) routes for Agent Gateway."""

from __future__ import annotations

import csv
import io
import json
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from agent_memory_lib import MemoryClient
from config.agent_config import get_config
from agent_memory_framework.plugins import discover_tools_grouped
from agent_memory_framework.plugins import discover_tools_from_mcp
from agent_runtime.product.auth_models import (
    LoginRequest,
    LogoutRequest,
    PasswordChangeRequest,
    SignupRequest,
    TokenRefreshRequest,
    TokenResponse,
)
from agent_runtime.product.auth_tokens import create_access_token
from agent_runtime.product.observability import AuditEvent, now_s, redact
from agent_runtime.product.usage_store import current_usage_month
from utils.logging_config import get_logger

from agent_runtime.product.gateway.portal_helpers import (
    _REFRESH_COOKIE,
    _assert_tenant_scope,
    _assert_workspace_access,
    _bearer_token_from_headers,
    _build_mcp_clients_from_workspace_config,
    _clear_auth_cookies,
    _custom_agents_for_tenant,
    _delete_custom_agent,
    _delete_workspace_config_for_tenant,
    _ensure_workspace_record,
    _extract_inline_workspace_mcp_secrets,
    _is_admin_tenant,
    _iso_ts,
    _load_portal_config,
    _me_from_access_token,
    _require_admin,
    _require_tenant_id,
    _require_workspace_id,
    _resolve_memory_service_url,
    _save_custom_agent,
    _save_portal_config,
    _save_tool_policy,
    _save_workspace_config_for_tenant,
    _save_workspace_mcp_secrets_for_tenant,
    _save_workspace_members,
    _set_auth_cookies,
    _tool_policy_for_workspace,
    _workspace_ids_for_tenant,
    _workspace_mcp_cache_key,
    _workspace_mcp_clients,
    _workspace_mcp_for_tenant,
    _workspace_mcp_secret_status_for_tenant,
    _workspace_prompt_for_tenant,
    _workspace_members_for_tenant,
    _workspace_record_for_tenant,
    _obs_store,
    _role_for_me,
    _usage_store,
)
from agent_runtime.product.gateway.models import (
    FileFirstReadProxyRequest,
    MonitoringAuditEntryResponse,
    MonitoringAuditResponse,
    MonitoringMetricResponse,
    MonitoringMetricsResponse,
    PortalMeResponse,
    PortalAgentUpsertRequest,
    ToolPolicyRequest,
    ToolStatusResponse,
    WorkspaceConfigRequest,
    WorkspaceMemberRequest,
    WorkspaceSecretsRequest,
    AdminQuotaRequest,
)

router = APIRouter(prefix="/portal/v1", tags=["portal"])
logger = get_logger(__name__)


def _has_workspace_mcp_connection_config(mcp: Dict[str, Any]) -> bool:
    servers_json = str(mcp.get("mcp_servers_json") or "").strip()
    if servers_json:
        try:
            servers = json.loads(servers_json)
        except Exception:
            return True
        if not isinstance(servers, list):
            return True
        for server in servers:
            if not isinstance(server, dict):
                continue
            if str(server.get("command") or server.get("url") or "").strip():
                return True

    stdio_json = str(mcp.get("mcp_stdio_json") or "").strip()
    if stdio_json:
        try:
            stdio = json.loads(stdio_json)
        except Exception:
            return True
        if not isinstance(stdio, dict):
            return True
        if str(stdio.get("command") or "").strip():
            return True

    return bool(str(mcp.get("mcp_http_url") or "").strip())


def _get_auth_store():
    from agent_runtime.product import agent_gateway as _gateway
    from agent_runtime.product.gateway import portal_helpers as _portal_helpers

    store = getattr(_gateway, "_auth_store", _portal_helpers._auth_store)
    _portal_helpers._auth_store = store
    return store


class PortalMemoryStatsRequest(BaseModel):
    memory_url: Optional[str] = None


class PortalMemoryIndexRebuildRequest(BaseModel):
    memory_url: Optional[str] = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    owner: str
    created_at: str
    status: str


class WorkspaceListResponse(BaseModel):
    workspaces: List[WorkspaceResponse]
    total: int


class WorkspaceDetailResponse(BaseModel):
    id: str
    name: str
    owner: str
    created_at: str
    status: str
    config: Dict[str, Any] = Field(default_factory=dict)
    agents: List[str] = Field(default_factory=list)


class AdminUserResponse(BaseModel):
    id: str
    email: str
    role: str
    created_at: Optional[str] = None
    last_login: Optional[str] = None
    tenant_id: Optional[str] = None


class AdminUserListResponse(BaseModel):
    users: List[AdminUserResponse]
    total: int


class AdminUserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    role: str = "user"
    tenant_id: Optional[str] = None


class AdminUserUpdateRequest(BaseModel):
    role: Optional[str] = None
    tenant_id: Optional[str] = None


class AdminUserPasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=256)


_TOOLS_DISCOVERY_CACHE: Dict[str, Dict[str, Any]] = {}


def _tools_cache_ttl_s() -> float:
    try:
        return float(os.getenv("PORTAL_TOOLS_DISCOVERY_CACHE_TTL_S", "300"))
    except Exception:
        return 300.0


def _tools_cache_entry(cache_key: str) -> Optional[Dict[str, Any]]:
    cached = _TOOLS_DISCOVERY_CACHE.get(cache_key)
    if not isinstance(cached, dict):
        return None
    payload = cached.get("payload")
    if not isinstance(payload, dict):
        return None
    cached_at_s = float(cached.get("cached_at_s") or 0.0)
    ttl_s = _tools_cache_ttl_s()
    stale = bool(ttl_s > 0 and cached_at_s > 0 and now_s() - cached_at_s > ttl_s)
    return {
        "payload": payload,
        "warning": cached.get("warning"),
        "cached_at": _iso_ts(cached_at_s),
        "stale": stale,
    }


def _tools_discovery_meta(cache_key: str) -> Dict[str, Any]:
    cached = _tools_cache_entry(cache_key)
    if not cached:
        return {
            "cached": False,
            "updated_at": None,
            "stale": False,
            "refresh_required": True,
        }
    return {
        "cached": True,
        "updated_at": cached["cached_at"],
        "stale": bool(cached["stale"]),
        "refresh_required": bool(cached["stale"]),
    }


def _discover_tools_payload(*, tenant_id: str, workspace_id: str) -> Dict[str, Any]:
    cache_key = _workspace_mcp_cache_key(tenant_id, workspace_id)
    clients = _workspace_mcp_clients().get(cache_key) or {}
    if not clients:
        try:
            clients = _build_mcp_clients_from_workspace_config(
                workspace_id, tenant_id=tenant_id
            )
            if clients:
                _workspace_mcp_clients()[cache_key] = clients
        except Exception:
            clients = {}

    if clients:
        payload: Dict[str, Any] = {}
        for namespace, client in clients.items():
            discovered = discover_tools_from_mcp(client, namespace=namespace)
            payload[namespace] = [t.to_metadata() for t in discovered.values()]
        return payload

    grouped = discover_tools_grouped()
    return {
        ns: [t.to_metadata() for t in tools.values()]
        for ns, tools in grouped.items()
    }


def _enabled_for_policy(policy: Dict[str, Any], name: str) -> bool:
    allow = {str(t).strip() for t in (policy.get("allowlist") or []) if str(t).strip()}
    deny = {str(t).strip() for t in (policy.get("denylist") or []) if str(t).strip()}
    overrides = policy.get("overrides") or {}
    if name in overrides:
        return bool(overrides.get(name))
    if allow and name not in allow:
        return False
    if name in deny:
        return False
    return True


def _tool_status_list(
    tools_payload: Dict[str, Any], policy: Dict[str, Any]
) -> List[ToolStatusResponse]:
    tools_list: List[ToolStatusResponse] = []
    for namespace, tools in tools_payload.items():
        if not isinstance(tools, list):
            continue
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name") or "")
            if not name:
                continue
            tools_list.append(
                ToolStatusResponse(
                    name=name,
                    enabled=_enabled_for_policy(policy, name),
                    status="available",
                    config={"namespace": namespace},
                )
            )
    return tools_list


def _admin_user_response(user: Any) -> AdminUserResponse:
    email = user.username if "@" in user.username else f"{user.username}@local"
    role = getattr(user, "role", None) or (
        "admin" if _is_admin_tenant(user.tenant_id) else "user"
    )
    return AdminUserResponse(
        id=user.username,
        email=email,
        role=role,
        created_at=_iso_ts(user.created_at),
        last_login=None,
        tenant_id=user.tenant_id,
    )


def _is_admin_user_record(user: Any) -> bool:
    return str(getattr(user, "role", "") or "").strip().lower() == "admin"


def _admin_user_count() -> int:
    try:
        return sum(1 for user in _get_auth_store().list_users() if _is_admin_user_record(user))
    except Exception:
        return 0


def _remove_user_workspace_members(
    cfg: Dict[str, Any], *, tenant_id: str, user_id: str
) -> int:
    members_root = cfg.get("workspace_members")
    if not isinstance(members_root, dict):
        return 0
    tenant_members = members_root.get(tenant_id)
    removed = 0
    if isinstance(tenant_members, list):
        next_members = [m for m in tenant_members if str(m.get("user_id")) != user_id]
        removed = len(tenant_members) - len(next_members)
        members_root[tenant_id] = next_members
        return removed
    if not isinstance(tenant_members, dict):
        return 0
    for workspace_id, members in list(tenant_members.items()):
        if not isinstance(members, list):
            continue
        next_members = [m for m in members if str(m.get("user_id")) != user_id]
        removed += len(members) - len(next_members)
        tenant_members[workspace_id] = next_members
    return removed


@router.post("/signup")
def portal_signup(req: SignupRequest) -> Dict[str, Any]:
    if os.getenv("PORTAL_SIGNUP_ENABLED", "").strip() != "1":
        raise HTTPException(status_code=403, detail="signup disabled")
    try:
        tenant_id = f"t_{req.username}"
        _get_auth_store().create_user(
            username=req.username, password=req.password, tenant_id=tenant_id
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="user already exists")
    return {"status": "success"}


@router.post("/login", response_model=TokenResponse)
def portal_login(req: LoginRequest, response: Response = None) -> TokenResponse:
    user = _get_auth_store().authenticate(username=req.username, password=req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    expires_in = int(os.getenv("AUTH_ACCESS_TOKEN_EXPIRES_IN_S", "3600"))
    access_token = create_access_token(
        sub=user.username, tenant_id=user.tenant_id, expires_in_s=expires_in
    )

    family_id = os.urandom(16).hex()
    refresh_token = _get_auth_store().issue_refresh(
        username=user.username, tenant_id=user.tenant_id, family_id=family_id
    )
    tokens = TokenResponse(
        access_token=access_token, refresh_token=refresh_token, expires_in=expires_in
    )
    if response is not None:
        _set_auth_cookies(
            response,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        )
    return tokens


@router.post("/token/refresh", response_model=TokenResponse)
def portal_refresh(
    req: Optional[TokenRefreshRequest] = None,
    response: Response = None,
    portal_refresh_token: Optional[str] = Cookie(default=None, alias=_REFRESH_COOKIE),
) -> TokenResponse:
    token_value = req.refresh_token if req else None
    refresh_token = token_value or portal_refresh_token
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token")
    try:
        refresh_rec = _get_auth_store().validate_and_rotate_refresh(refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    expires_in = int(os.getenv("AUTH_ACCESS_TOKEN_EXPIRES_IN_S", "3600"))
    access_token = create_access_token(
        sub=refresh_rec.username,
        tenant_id=refresh_rec.tenant_id,
        expires_in_s=expires_in,
    )
    new_refresh = _get_auth_store().issue_refresh(
        username=refresh_rec.username,
        tenant_id=refresh_rec.tenant_id,
        family_id=refresh_rec.family_id,
    )
    tokens = TokenResponse(
        access_token=access_token, refresh_token=new_refresh, expires_in=expires_in
    )
    if response is not None:
        _set_auth_cookies(
            response,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        )
    return tokens


@router.post("/logout")
def portal_logout(
    req: Optional[LogoutRequest] = None,
    response: Response = None,
    portal_refresh_token: Optional[str] = Cookie(default=None, alias=_REFRESH_COOKIE),
) -> Dict[str, Any]:
    refresh_token = req.refresh_token if req else None
    if not isinstance(refresh_token, str):
        refresh_token = None
    cookie_refresh_token = (
        portal_refresh_token if isinstance(portal_refresh_token, str) else None
    )
    refresh_token = refresh_token or cookie_refresh_token
    if refresh_token:
        try:
            refresh_rec = _get_auth_store().validate_and_rotate_refresh(refresh_token)
            _get_auth_store().revoke_refresh_family(refresh_rec.family_id)
        except ValueError:
            pass
    if response is not None:
        _clear_auth_cookies(response)
    return {"status": "success"}


@router.post("/password/change")
def portal_change_password(
    req: PasswordChangeRequest,
    token: str = Depends(_bearer_token_from_headers),
) -> Dict[str, Any]:
    me = _me_from_access_token(token)
    user = _get_auth_store().authenticate(
        username=me.sub, password=req.current_password
    )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid current password")
    _get_auth_store().update_password(username=me.sub, new_password=req.new_password)
    try:
        _get_auth_store().revoke_refresh_tokens_for_user(username=me.sub)
    except AttributeError:
        logger.debug("auth store does not support refresh token user revocation")
    except Exception:
        logger.debug("refresh token revocation after password change failed", exc_info=True)
    return {"status": "success"}


@router.get("/me", response_model=PortalMeResponse)
def portal_me(token: str = Depends(_bearer_token_from_headers)) -> PortalMeResponse:
    me = _me_from_access_token(token)
    user = _get_auth_store().get_user(me.sub)
    created_at = _iso_ts(user.created_at) if user and user.created_at else None
    email = me.sub if "@" in me.sub else f"{me.sub}@local"
    role = _role_for_me(me)
    return PortalMeResponse(
        id=me.sub,
        email=email,
        role=role,
        created_at=created_at,
    )


@router.get("/tools")
def portal_list_tools(
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
    refresh: bool = False,
) -> Dict[str, Any]:
    me = _me_from_access_token(token)
    _assert_workspace_access(me, workspace_id, write=bool(refresh), allow_owner_write=True)
    cache_key = _workspace_mcp_cache_key(me.tenant_id, workspace_id)
    cached = _tools_cache_entry(cache_key)
    if not refresh:
        payload = cached["payload"] if cached else {}
        warning = cached.get("warning") if cached else None
        return {
            "status": "success",
            "data": payload,
            "tools_by_namespace": payload,
            "warning": warning,
            "discovery": _tools_discovery_meta(cache_key),
        }

    try:
        payload = _discover_tools_payload(tenant_id=me.tenant_id, workspace_id=workspace_id)
        warning = None
    except Exception as exc:
        logger.warning("Tool discovery unavailable", extra={"error": str(exc)})
        payload = {}
        warning = f"Tool discovery unavailable: {exc}"
    try:
        _TOOLS_DISCOVERY_CACHE[cache_key] = {
            "payload": payload,
            "warning": warning,
            "cached_at_s": now_s(),
        }
    except Exception:
        logger.debug("Failed to cache tool discovery result", exc_info=True)
    return {
        "status": "success",
        "data": payload,
        "tools_by_namespace": payload,
        "warning": warning,
        "discovery": _tools_discovery_meta(cache_key),
    }


@router.get("/agents")
def portal_list_agents(
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    me = _me_from_access_token(token)
    _assert_workspace_access(me, workspace_id)
    cfg = _load_portal_config()
    custom_agents = _custom_agents_for_tenant(
        cfg, me.tenant_id, workspace_id=workspace_id
    )

    agents_payload: Dict[str, Any] = {}
    try:
        from agent_runtime.product.agent_registry import discover_product_agents

        discovered = discover_product_agents()
        for key, entry in discovered.items():
            agents_payload[key] = {
                "id": key,
                "name": key,
                "description": (entry.cls.__doc__ or "").strip() or None,
                "spec": entry.spec,
                "custom": False,
                "tools": [],
            }
    except Exception:
        agents_payload = {}

    for agent_id, data in custom_agents.items():
        if not isinstance(data, dict):
            continue
        agents_payload[agent_id] = {
            "id": agent_id,
            "name": data.get("name") or agent_id,
            "description": data.get("description"),
            "system_prompt": data.get("system_prompt"),
            "tools": list(data.get("tools") or []),
            "custom": True,
            "workspace_id": data.get("workspace_id"),
        }

    return {"status": "success", "agents": agents_payload}


@router.post("/agents")
def portal_upsert_agent(
    req: PortalAgentUpsertRequest,
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    me = _me_from_access_token(token)
    target_workspace = (req.workspace_id or workspace_id or "").strip()
    if req.workspace_id and target_workspace != workspace_id:
        raise HTTPException(
            status_code=400,
            detail="workspace_id in request body must match x-workspace-id",
        )
    cfg = _load_portal_config()
    _assert_workspace_access(
        me, target_workspace, cfg=cfg, write=True, allow_owner_write=True
    )
    agent_id = (req.id or "").strip()
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent id is required")

    now_iso = _iso_ts(now_s()) or ""
    existing = _custom_agents_for_tenant(
        cfg, me.tenant_id, workspace_id=target_workspace
    ).get(agent_id)
    created_at = None
    if isinstance(existing, dict):
        created_at = existing.get("created_at")

    payload = {
        "id": agent_id,
        "name": req.name or agent_id,
        "description": req.description,
        "system_prompt": req.system_prompt,
        "tools": list(req.tools or []),
        "workspace_id": target_workspace,
        "created_at": created_at or now_iso,
        "updated_at": now_iso,
    }
    _save_custom_agent(
        cfg,
        tenant_id=me.tenant_id,
        workspace_id=target_workspace,
        agent_id=agent_id,
        payload=payload,
    )
    _save_portal_config(cfg)
    return {"status": "success", "data": payload}


@router.delete("/agents/{agent_id}")
def portal_delete_agent(
    agent_id: str,
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    me = _me_from_access_token(token)
    _assert_workspace_access(me, workspace_id, write=True, allow_owner_write=True)
    cfg = _load_portal_config()
    removed = _delete_custom_agent(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id, agent_id=agent_id
    )
    if not removed:
        raise HTTPException(status_code=404, detail="agent not found")
    _save_portal_config(cfg)
    return {"status": "success"}


@router.get("/tools/status")
def portal_tools_status(
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    me = _me_from_access_token(token)
    _assert_workspace_access(me, workspace_id)
    cfg = _load_portal_config()
    policy = _tool_policy_for_workspace(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id
    )

    env = {
        "AGENT_MEMORY_MCP_SERVERS": bool((os.getenv("AGENT_MEMORY_MCP_SERVERS") or "").strip()),
        "AGENT_MEMORY_MCP_STDIO": bool((os.getenv("AGENT_MEMORY_MCP_STDIO") or "").strip()),
        "MCP_STDIO_COMMAND": bool((os.getenv("MCP_STDIO_COMMAND") or "").strip()),
        "MCP_STDIO_ARGS": bool((os.getenv("MCP_STDIO_ARGS") or "").strip()),
        "MCP_NAMESPACE": bool((os.getenv("MCP_NAMESPACE") or "").strip()),
        "MCP_ENABLED": bool((os.getenv("MCP_ENABLED") or "").strip()),
    }
    env_configured = (
        bool((os.getenv("AGENT_MEMORY_MCP_SERVERS") or "").strip())
        or bool((os.getenv("AGENT_MEMORY_MCP_STDIO") or "").strip())
        or bool((os.getenv("MCP_STDIO_COMMAND") or "").strip())
    )

    saved_mcp = _workspace_mcp_for_tenant(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id
    )
    secret_status = _workspace_mcp_secret_status_for_tenant(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id
    )
    workspace_saved = _has_workspace_mcp_connection_config(saved_mcp)
    cache_key = _workspace_mcp_cache_key(me.tenant_id, workspace_id)
    workspace_applied = bool(_workspace_mcp_clients().get(cache_key))

    cached = _tools_cache_entry(cache_key)
    tools_payload = cached["payload"] if cached else {}
    tools_list = _tool_status_list(tools_payload, policy)
    discovery_meta = _tools_discovery_meta(cache_key)

    return {
        "status": "success",
        "data": {
            "workspace_configured": workspace_saved or workspace_applied,
            "workspace_saved": workspace_saved,
            "workspace_applied": workspace_applied,
            "env_configured": env_configured,
            "configured": workspace_saved or workspace_applied or env_configured,
            "env": env,
            "workspace_secrets_configured": any(secret_status.values()),
            "workspace_secrets": secret_status,
            "policy": policy,
            "tool_inventory_cached": discovery_meta["cached"],
            "tool_inventory_updated_at": discovery_meta["updated_at"],
            "tool_inventory_stale": discovery_meta["stale"],
            "tool_inventory_refresh_required": discovery_meta["refresh_required"],
        },
        "tools": [t.model_dump() for t in tools_list],
    }


@router.get("/tools/policy")
def portal_get_tool_policy(
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    me = _me_from_access_token(token)
    _assert_workspace_access(me, workspace_id)
    cfg = _load_portal_config()
    policy = _tool_policy_for_workspace(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id
    )
    return {"status": "success", "data": policy}


@router.post("/tools/policy")
def portal_set_tool_policy(
    req: ToolPolicyRequest,
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    me = _me_from_access_token(token)
    _assert_workspace_access(me, workspace_id, write=True, allow_owner_write=True)
    cfg = _load_portal_config()
    policy = {
        "allowlist": list(req.allowlist or []),
        "denylist": list(req.denylist or []),
        "overrides": dict(req.overrides or {}),
    }
    _save_tool_policy(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id, policy=policy
    )
    _save_portal_config(cfg)
    return {"status": "success", "data": policy}


@router.get("/workspace/config")
def portal_get_workspace_config(
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    me = _me_from_access_token(token)
    cfg = _load_portal_config()
    _assert_workspace_access(me, workspace_id)
    return {
        "status": "success",
        "data": {
            "tenant_id": me.tenant_id,
            "workspace_id": workspace_id,
            "system_prompt": _workspace_prompt_for_tenant(
                cfg, tenant_id=me.tenant_id, workspace_id=workspace_id
            ),
            "mcp": _workspace_mcp_for_tenant(
                cfg, tenant_id=me.tenant_id, workspace_id=workspace_id
            ),
            "mcp_secrets": _workspace_mcp_secret_status_for_tenant(
                cfg, tenant_id=me.tenant_id, workspace_id=workspace_id
            ),
        },
    }


@router.get("/workspace/secrets")
def portal_get_workspace_secrets(
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    me = _me_from_access_token(token)
    cfg = _load_portal_config()
    _assert_workspace_access(me, workspace_id)
    configured = _workspace_mcp_secret_status_for_tenant(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id
    )
    return {
        "status": "success",
        "data": {
            "tenant_id": me.tenant_id,
            "workspace_id": workspace_id,
            "configured": configured,
            "names": sorted(configured.keys()),
        },
    }


@router.post("/workspace/secrets")
def portal_set_workspace_secrets(
    req: WorkspaceSecretsRequest,
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    me = _me_from_access_token(token)
    cfg = _load_portal_config()
    _assert_workspace_access(me, workspace_id, write=True, allow_owner_write=True)
    configured = _save_workspace_mcp_secrets_for_tenant(
        cfg,
        tenant_id=me.tenant_id,
        workspace_id=workspace_id,
        values=dict(req.values or {}),
        clear=list(req.clear or []),
    )
    _save_portal_config(cfg)
    _workspace_mcp_clients().pop(
        _workspace_mcp_cache_key(me.tenant_id, workspace_id), None
    )
    return {
        "status": "success",
        "data": {
            "tenant_id": me.tenant_id,
            "workspace_id": workspace_id,
            "configured": configured,
            "names": sorted(configured.keys()),
        },
    }


@router.post("/workspace/config")
def portal_set_workspace_config(
    req: WorkspaceConfigRequest,
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    me = _me_from_access_token(token)
    cfg = _load_portal_config()
    _assert_workspace_access(me, workspace_id, write=True, allow_owner_write=True)
    mcp_obj = req.mcp if isinstance(req.mcp, dict) else {}
    entry: Dict[str, Any] = {
        "mcp_servers_json": req.mcp_servers_json
        if req.mcp_servers_json is not None
        else mcp_obj.get("mcp_servers_json"),
        "mcp_stdio_json": req.mcp_stdio_json
        if req.mcp_stdio_json is not None
        else mcp_obj.get("mcp_stdio_json"),
        "mcp_http_url": req.mcp_http_url
        if req.mcp_http_url is not None
        else mcp_obj.get("mcp_http_url"),
        "mcp_http_namespace": req.mcp_http_namespace
        if req.mcp_http_namespace is not None
        else mcp_obj.get("mcp_http_namespace"),
        "mcp_http_headers_json": req.mcp_http_headers_json
        if req.mcp_http_headers_json is not None
        else mcp_obj.get("mcp_http_headers_json"),
    }
    entry, inline_secret_values = _extract_inline_workspace_mcp_secrets(entry)
    if inline_secret_values:
        _save_workspace_mcp_secrets_for_tenant(
            cfg,
            tenant_id=me.tenant_id,
            workspace_id=workspace_id,
            values=inline_secret_values,
        )
    _save_workspace_config_for_tenant(
        cfg,
        tenant_id=me.tenant_id,
        workspace_id=workspace_id,
        system_prompt=req.system_prompt,
        mcp=entry,
    )
    _save_portal_config(cfg)

    return {
        "status": "success",
        "data": {
            "tenant_id": me.tenant_id,
            "workspace_id": workspace_id,
            "saved": {"system_prompt": req.system_prompt, "mcp": entry},
            "note": (
                "MCP config saved. Call /portal/v1/workspace/apply to activate "
                "(starts MCP server processes in gateway)."
            ),
        },
    }


@router.post("/workspace/apply")
def portal_apply_workspace_config(
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    me = _me_from_access_token(token)
    cfg = _load_portal_config()
    _assert_workspace_access(me, workspace_id, cfg=cfg, write=True, allow_owner_write=True)
    clients = _build_mcp_clients_from_workspace_config(
        workspace_id, tenant_id=me.tenant_id
    )
    cache_key = _workspace_mcp_cache_key(me.tenant_id, workspace_id)
    _workspace_mcp_clients()[cache_key] = clients
    _TOOLS_DISCOVERY_CACHE.pop(cache_key, None)
    return {
        "status": "success",
        "data": {
            "workspace_id": workspace_id,
            "namespaces": sorted(clients.keys()),
        },
    }


@router.post("/memory/read")
def portal_memory_read(
    req: FileFirstReadProxyRequest,
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    cfg = get_config()
    me = _me_from_access_token(token)
    ctx = _assert_workspace_access(me, workspace_id)
    base_url = _resolve_memory_service_url(
        configured_url=cfg.memory_service_url,
        requested_url=req.memory_url,
    )

    if str(req.tier or "").strip().lower() == "preferences":
        requested_user = str(req.user_id or "").strip()
        if requested_user and requested_user != me.sub and ctx.get("role") != "admin":
            raise HTTPException(status_code=403, detail="preference user scope denied")
        if not requested_user:
            req = req.model_copy(update={"user_id": me.sub})

    client = MemoryClient(base_url=base_url).with_scope(
        tenant_id=me.tenant_id,
        workspace_id=workspace_id,
    ).with_actor(
        actor_user_id=me.sub,
        actor_role=str(ctx.get("role") or "user"),
    )

    return client.memory_read(
        tier=req.tier,
        conversation_id=req.conversation_id,
        task_id=req.task_id,
        user_id=req.user_id,
        key=req.key,
        query=req.query,
        limit=req.limit,
        top_k=req.top_k,
        scopes=list(req.scopes) if req.scopes else None,
    )


@router.post("/memory/stats")
def portal_memory_stats(
    req: Optional[PortalMemoryStatsRequest] = None,
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    cfg = get_config()
    me = _me_from_access_token(token)
    _assert_workspace_access(me, workspace_id)
    base_url = _resolve_memory_service_url(
        configured_url=cfg.memory_service_url,
        requested_url=req.memory_url if req else None,
    )

    client = MemoryClient(base_url=base_url).with_scope(
        tenant_id=me.tenant_id,
        workspace_id=workspace_id,
    )

    return client.stats({"tenant_id": me.tenant_id, "workspace_id": workspace_id})


@router.post("/memory/index/rebuild")
def portal_memory_index_rebuild(
    req: Optional[PortalMemoryIndexRebuildRequest] = None,
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    cfg = get_config()
    me = _me_from_access_token(token)
    _assert_workspace_access(me, workspace_id, write=True, allow_owner_write=True)
    base_url = _resolve_memory_service_url(
        configured_url=cfg.memory_service_url,
        requested_url=req.memory_url if req else None,
    )

    client = MemoryClient(base_url=base_url).with_scope(
        tenant_id=me.tenant_id,
        workspace_id=workspace_id,
    )

    return client.memory_index_rebuild(
        tenant_id=me.tenant_id, workspace_id=workspace_id
    )


@router.get("/monitoring/metrics", response_model=MonitoringMetricsResponse)
def portal_metrics(
    workspace_id: str = Depends(_require_workspace_id),
    metric_type: Optional[str] = None,
    time_range: Optional[str] = None,
    limit: int = 200,
    token: str = Depends(_bearer_token_from_headers),
    tenant_id: Optional[str] = Depends(lambda: None),
) -> MonitoringMetricsResponse:
    me = _me_from_access_token(token)
    _assert_workspace_access(me, workspace_id)
    tenant = _assert_tenant_scope(me, (
        tenant_id
        if isinstance(tenant_id, str) and tenant_id
        else me.tenant_id
    ))
    metric_type = (metric_type or "").strip().lower()
    time_range = (time_range or "").strip().lower()

    name_filter = None
    if metric_type in {"cpu", "memory", "storage"}:
        name_filter = f"system.{metric_type}"

    points = _obs_store.query_metrics(
        tenant_id=tenant,
        workspace_id=workspace_id,
        name=name_filter,
        limit=limit,
    )

    window_s = {
        "1h": 3600,
        "24h": 86400,
        "7d": 604800,
    }.get(time_range)
    if window_s:
        cutoff = now_s() - window_s
        points = [p for p in points if p.ts_s >= cutoff]

    unit = {
        "cpu": "percent",
        "memory": "mb",
        "storage": "gb",
    }.get(metric_type, "unit")

    metrics = [
        MonitoringMetricResponse(
            timestamp=_iso_ts(p.ts_s) or "",
            value=float(p.value),
            unit=unit,
        )
        for p in points
    ]

    return MonitoringMetricsResponse(metrics=metrics, total=len(points))


@router.get("/monitoring/audit", response_model=MonitoringAuditResponse)
def portal_audit(
    workspace_id: str = Depends(_require_workspace_id),
    page: int = 1,
    limit: int = 50,
    action: Optional[str] = None,
    user_id: Optional[str] = None,
    token: str = Depends(_bearer_token_from_headers),
    tenant_id: Optional[str] = Depends(lambda: None),
) -> MonitoringAuditResponse:
    me = _me_from_access_token(token)
    _assert_workspace_access(me, workspace_id)
    tenant = _assert_tenant_scope(me, (
        tenant_id
        if isinstance(tenant_id, str) and tenant_id
        else me.tenant_id
    ))
    page = max(1, int(page))
    limit = max(1, min(int(limit), 500))

    events = _obs_store.query_audit_all(
        tenant_id=tenant,
        workspace_id=workspace_id,
        action=action,
        actor=user_id,
    )

    total = len(events)
    start = (page - 1) * limit
    end = start + limit
    slice_events = events[start:end]

    audits = [
        MonitoringAuditEntryResponse(
            id=f"{int(e.ts_s)}-{i}",
            user_id=e.actor,
            action=e.action,
            resource=e.resource,
            timestamp=_iso_ts(e.ts_s) or "",
            metadata=redact(e.detail) if e.detail else None,
        )
        for i, e in enumerate(slice_events)
    ]

    return MonitoringAuditResponse(audits=audits, total=total)


@router.get("/monitoring/metrics/export")
def portal_metrics_export(
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
    metric_type: Optional[str] = None,
    time_range: Optional[str] = None,
    limit: int = 2000,
    tenant_id: Optional[str] = None,
) -> Response:
    me = _me_from_access_token(token)
    _assert_workspace_access(me, workspace_id)
    tenant = _assert_tenant_scope(me, tenant_id if tenant_id else me.tenant_id)
    metrics = portal_metrics(
        workspace_id=workspace_id,
        metric_type=metric_type,
        time_range=time_range,
        limit=limit,
        token=token,
        tenant_id=tenant,
    ).metrics

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "value", "unit"])
    for m in metrics:
        writer.writerow([m.timestamp, m.value, m.unit])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=metrics.csv"},
    )


@router.get("/monitoring/audit/export")
def portal_audit_export(
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
    action: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 2000,
    tenant_id: Optional[str] = None,
) -> Response:
    me = _me_from_access_token(token)
    _assert_workspace_access(me, workspace_id)
    tenant = _assert_tenant_scope(me, tenant_id if tenant_id else me.tenant_id)
    events = _obs_store.query_audit_all(
        tenant_id=tenant,
        workspace_id=workspace_id,
        action=action,
        actor=user_id,
    )

    if limit > 0:
        events = events[:limit]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "user_id", "action", "resource"])
    for e in events:
        writer.writerow(
            [
                _iso_ts(e.ts_s) or "",
                e.actor,
                e.action,
                e.resource,
            ]
        )

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit.csv"},
    )


@router.get("/admin/usage")
def portal_admin_usage(
    tenant_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    user_id: Optional[str] = None,
    month: Optional[str] = None,
    me: Any = Depends(_require_admin),
) -> Dict[str, Any]:
    target_tenant = str(tenant_id or me.tenant_id or "").strip()
    target_tenant = _assert_tenant_scope(me, target_tenant)
    rows = _usage_store.list_usage_summary(
        tenant_id=target_tenant,
        workspace_id=workspace_id,
        user_id=user_id,
        month=month,
    )
    resolved_month = rows[0].month if rows else (month or current_usage_month())
    return {
        "status": "success",
        "data": {
            "tenant_id": target_tenant,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "month": resolved_month,
            "items": [row.to_dict() for row in rows],
            "total": len(rows),
        },
    }


@router.get("/admin/quotas")
def portal_list_admin_quotas(
    tenant_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    user_id: Optional[str] = None,
    me: Any = Depends(_require_admin),
) -> Dict[str, Any]:
    target_tenant = str(tenant_id or me.tenant_id or "").strip()
    target_tenant = _assert_tenant_scope(me, target_tenant)
    quotas = _usage_store.list_quotas(
        tenant_id=target_tenant,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    return {
        "status": "success",
        "data": {
            "tenant_id": target_tenant,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "items": [quota.to_dict() for quota in quotas],
            "total": len(quotas),
        },
    }


@router.post("/admin/quotas")
def portal_set_admin_quota(
    req: AdminQuotaRequest,
    me: Any = Depends(_require_admin),
) -> Dict[str, Any]:
    target_tenant = str(req.tenant_id or me.tenant_id or "").strip()
    target_tenant = _assert_tenant_scope(me, target_tenant)
    if req.enabled and int(req.monthly_token_quota) <= 0:
        raise HTTPException(
            status_code=400,
            detail="monthly_token_quota must be greater than 0 when quota enforcement is enabled",
        )
    quota = _usage_store.set_quota(
        tenant_id=target_tenant,
        workspace_id=req.workspace_id,
        user_id=req.user_id,
        monthly_token_quota=req.monthly_token_quota,
        enabled=req.enabled,
    )
    try:
        _obs_store.record_audit(
            AuditEvent(
                ts_s=now_s(),
                tenant_id=target_tenant,
                workspace_id=req.workspace_id,
                actor=me.sub,
                action="quota.set",
                resource=f"user:{req.user_id}",
                ok=True,
                detail=redact(
                    {
                        "tenant_id": target_tenant,
                        "monthly_token_quota": quota.monthly_token_quota,
                        "enabled": quota.enabled,
                    }
                ),
            )
        )
    except Exception:
        logger.debug("quota audit write failed", exc_info=True)
    return {"status": "success", "data": {"quota": quota.to_dict()}}


@router.get("/workspaces", response_model=WorkspaceListResponse)
def portal_list_workspaces(
    me: Any = Depends(_require_admin),
) -> WorkspaceListResponse:
    cfg = _load_portal_config()
    created_at_fallback = _iso_ts(now_s()) or ""
    workspaces = []

    for ws_id in _workspace_ids_for_tenant(cfg, tenant_id=me.tenant_id):
        record = _workspace_record_for_tenant(
            cfg, tenant_id=me.tenant_id, workspace_id=ws_id
        )
        configured = bool(
            _workspace_prompt_for_tenant(
                cfg, tenant_id=me.tenant_id, workspace_id=ws_id
            )
            or _workspace_mcp_for_tenant(
                cfg, tenant_id=me.tenant_id, workspace_id=ws_id
            )
        )
        workspaces.append(
            WorkspaceResponse(
                id=ws_id,
                name=str(record.get("name") or f"Workspace {ws_id}"),
                owner=str(record.get("owner") or me.tenant_id),
                created_at=str(record.get("created_at") or created_at_fallback),
                status=str(
                    record.get("status")
                    or ("active" if configured or ws_id == "ws_default" else "inactive")
                ),
            )
        )

    return WorkspaceListResponse(workspaces=workspaces, total=len(workspaces))


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceDetailResponse)
def portal_get_workspace(
    workspace_id: str,
    me: Any = Depends(_require_admin),
) -> WorkspaceDetailResponse:
    cfg = _load_portal_config()
    mcp_config = _workspace_mcp_for_tenant(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id
    )
    system_prompt = _workspace_prompt_for_tenant(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id
    )
    configured = bool(mcp_config or system_prompt)
    status = "active" if configured else "inactive"

    created_at_fallback = _iso_ts(now_s()) or ""
    record = _workspace_record_for_tenant(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id
    )

    return WorkspaceDetailResponse(
        id=workspace_id,
        name=str(record.get("name") or f"Workspace {workspace_id}"),
        owner=str(record.get("owner") or me.tenant_id),
        created_at=str(record.get("created_at") or created_at_fallback),
        status=str(record.get("status") or status),
        config={"system_prompt": system_prompt, "mcp": mcp_config},
        agents=[],
    )


@router.delete("/workspaces/{workspace_id}")
def portal_delete_workspace(
    workspace_id: str,
    me: Any = Depends(_require_admin),
) -> Dict[str, Any]:
    if workspace_id == "ws_default":
        raise HTTPException(status_code=400, detail="Cannot delete default workspace")

    cfg = _load_portal_config()
    if workspace_id not in _workspace_ids_for_tenant(cfg, tenant_id=me.tenant_id):
        raise HTTPException(status_code=404, detail="workspace not found")
    _delete_workspace_config_for_tenant(cfg, tenant_id=me.tenant_id, workspace_id=workspace_id)
    _save_portal_config(cfg)

    return {"status": "success", "message": f"Workspace {workspace_id} deleted"}


@router.get("/workspaces/{workspace_id}/members")
def portal_list_workspace_members(
    workspace_id: str,
    me: Any = Depends(_require_admin),
) -> Dict[str, Any]:
    cfg = _load_portal_config()
    members = _workspace_members_for_tenant(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id
    )
    return {"status": "success", "members": members}


@router.post("/workspaces/{workspace_id}/members")
def portal_add_workspace_member(
    workspace_id: str,
    req: WorkspaceMemberRequest,
    me: Any = Depends(_require_admin),
) -> Dict[str, Any]:
    cfg = _load_portal_config()
    _ensure_workspace_record(cfg, tenant_id=me.tenant_id, workspace_id=workspace_id)
    members = _workspace_members_for_tenant(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id
    )
    user_id = (req.user_id or "").strip()
    role = req.role or "member"
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    updated = False
    for entry in members:
        if str(entry.get("user_id")) == user_id:
            entry["role"] = role
            entry["updated_at"] = _iso_ts(now_s()) or ""
            updated = True
            break
    if not updated:
        members.append(
            {
                "user_id": user_id,
                "role": role,
                "added_at": _iso_ts(now_s()) or "",
            }
        )

    _save_workspace_members(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id, members=members
    )
    _save_portal_config(cfg)
    return {"status": "success", "members": members}


@router.delete("/workspaces/{workspace_id}/members/{user_id}")
def portal_delete_workspace_member(
    workspace_id: str,
    user_id: str,
    me: Any = Depends(_require_admin),
) -> Dict[str, Any]:
    cfg = _load_portal_config()
    members = _workspace_members_for_tenant(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id
    )
    next_members = [m for m in members if str(m.get("user_id")) != user_id]
    if len(next_members) == len(members):
        raise HTTPException(status_code=404, detail="member not found")
    _save_workspace_members(
        cfg, tenant_id=me.tenant_id, workspace_id=workspace_id, members=next_members
    )
    _save_portal_config(cfg)
    return {"status": "success", "members": next_members}


@router.get("/admin/users", response_model=AdminUserListResponse)
def portal_list_admin_users(
    me: Any = Depends(_require_admin),
) -> AdminUserListResponse:
    users = []
    try:
        all_users = _get_auth_store().list_users()
        for user in all_users:
            if user.tenant_id != me.tenant_id:
                try:
                    _assert_tenant_scope(me, user.tenant_id)
                except HTTPException:
                    continue
            users.append(_admin_user_response(user))
    except Exception as exc:
        logger.warning("Failed to list users: %s", exc)

    return AdminUserListResponse(users=users, total=len(users))


@router.post("/admin/users")
def portal_create_admin_user(
    req: AdminUserCreateRequest,
    me: Any = Depends(_require_admin),
) -> Dict[str, Any]:
    username = str(req.username or "").strip()
    password = str(req.password or "")
    role = str(req.role or "user").strip().lower()
    tenant_id = str(req.tenant_id or me.tenant_id or "").strip()

    if not username:
        raise HTTPException(status_code=400, detail="username required")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")
    if role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="role must be admin or user")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id required")
    tenant_id = _assert_tenant_scope(me, tenant_id)

    try:
        user = _get_auth_store().create_user(
            username=username,
            password=password,
            tenant_id=tenant_id,
            role=role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="user already exists") from exc

    try:
        _obs_store.record_audit(
            AuditEvent(
                ts_s=now_s(),
                tenant_id=me.tenant_id,
                workspace_id="admin",
                actor=me.sub,
                action="admin.user.create",
                resource=f"user:{username}",
                ok=True,
                detail=redact({"tenant_id": tenant_id, "role": role}),
            )
        )
    except Exception:
        logger.debug("admin user create audit write failed", exc_info=True)

    return {"status": "success", "data": _admin_user_response(user)}


@router.patch("/admin/users/{username}")
def portal_update_admin_user(
    username: str,
    req: AdminUserUpdateRequest,
    me: Any = Depends(_require_admin),
) -> Dict[str, Any]:
    target_username = str(username or "").strip()
    if not target_username:
        raise HTTPException(status_code=400, detail="username required")

    auth_store = _get_auth_store()
    current = auth_store.get_user(target_username)
    if not current:
        raise HTTPException(status_code=404, detail="user not found")
    _assert_tenant_scope(me, current.tenant_id)

    role = None if req.role is None else str(req.role or "").strip().lower()
    tenant_id = None if req.tenant_id is None else str(req.tenant_id or "").strip()
    if role is not None and role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="role must be admin or user")
    if tenant_id is not None and not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id required")
    if tenant_id is not None:
        tenant_id = _assert_tenant_scope(me, tenant_id)
    if role is None and tenant_id is None:
        raise HTTPException(status_code=400, detail="no changes provided")

    if target_username == me.sub:
        current_role = str(getattr(current, "role", "") or "").strip().lower()
        if role is not None and role != current_role:
            raise HTTPException(status_code=400, detail="cannot change your own role")
        if tenant_id is not None and tenant_id != current.tenant_id:
            raise HTTPException(status_code=400, detail="cannot change your own tenant")

    if _is_admin_user_record(current) and role == "user" and _admin_user_count() <= 1:
        raise HTTPException(status_code=400, detail="cannot demote the last admin")

    try:
        updated = auth_store.update_user(
            username=target_username,
            tenant_id=tenant_id,
            role=role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        _obs_store.record_audit(
            AuditEvent(
                ts_s=now_s(),
                tenant_id=me.tenant_id,
                workspace_id="admin",
                actor=me.sub,
                action="admin.user.update",
                resource=f"user:{target_username}",
                ok=True,
                detail=redact(
                    {
                        "tenant_id": updated.tenant_id,
                        "role": updated.role,
                    }
                ),
            )
        )
    except Exception:
        logger.debug("admin user update audit write failed", exc_info=True)

    return {"status": "success", "data": _admin_user_response(updated)}


@router.post("/admin/users/{username}/password")
def portal_reset_admin_user_password(
    username: str,
    req: AdminUserPasswordResetRequest,
    me: Any = Depends(_require_admin),
) -> Dict[str, Any]:
    target_username = str(username or "").strip()
    if not target_username:
        raise HTTPException(status_code=400, detail="username required")
    if target_username == me.sub:
        raise HTTPException(
            status_code=400,
            detail="use profile password change for your own account",
        )

    auth_store = _get_auth_store()
    user = auth_store.get_user(target_username)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    _assert_tenant_scope(me, user.tenant_id)

    try:
        auth_store.update_password(
            username=target_username,
            new_password=req.new_password,
        )
        revoked_refresh_tokens = auth_store.revoke_refresh_tokens_for_user(
            username=target_username
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        _obs_store.record_audit(
            AuditEvent(
                ts_s=now_s(),
                tenant_id=me.tenant_id,
                workspace_id="admin",
                actor=me.sub,
                action="admin.user.password_reset",
                resource=f"user:{target_username}",
                ok=True,
                detail=redact({"tenant_id": user.tenant_id, "role": user.role}),
            )
        )
    except Exception:
        logger.debug("admin user password reset audit write failed", exc_info=True)

    return {"status": "success", "data": {"id": target_username, "revoked_refresh_tokens": revoked_refresh_tokens}}


@router.delete("/admin/users/{username}")
def portal_delete_admin_user(
    username: str,
    me: Any = Depends(_require_admin),
) -> Dict[str, Any]:
    target_username = str(username or "").strip()
    if not target_username:
        raise HTTPException(status_code=400, detail="username required")
    if target_username == me.sub:
        raise HTTPException(status_code=400, detail="cannot delete your own account")

    auth_store = _get_auth_store()
    user = auth_store.get_user(target_username)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    _assert_tenant_scope(me, user.tenant_id)
    if _is_admin_user_record(user) and _admin_user_count() <= 1:
        raise HTTPException(status_code=400, detail="cannot delete the last admin")

    auth_store.delete_user(username=target_username)
    removed_quotas = 0
    try:
        removed_quotas = _usage_store.delete_quotas_for_user(
            tenant_id=user.tenant_id,
            user_id=target_username,
        )
    except Exception:
        logger.debug("admin user quota cleanup failed", exc_info=True)

    removed_members = 0
    try:
        cfg = _load_portal_config()
        removed_members = _remove_user_workspace_members(
            cfg, tenant_id=user.tenant_id, user_id=target_username
        )
        if removed_members:
            _save_portal_config(cfg)
    except Exception:
        logger.debug("admin user workspace membership cleanup failed", exc_info=True)

    try:
        _obs_store.record_audit(
            AuditEvent(
                ts_s=now_s(),
                tenant_id=me.tenant_id,
                workspace_id="admin",
                actor=me.sub,
                action="admin.user.delete",
                resource=f"user:{target_username}",
                ok=True,
                detail=redact(
                    {
                        "tenant_id": user.tenant_id,
                        "role": user.role,
                        "removed_quotas": removed_quotas,
                        "removed_members": removed_members,
                    }
                ),
            )
        )
    except Exception:
        logger.debug("admin user delete audit write failed", exc_info=True)

    return {
        "status": "success",
        "data": {
            "id": target_username,
            "tenant_id": user.tenant_id,
            "removed_quotas": removed_quotas,
            "removed_members": removed_members,
        },
    }
