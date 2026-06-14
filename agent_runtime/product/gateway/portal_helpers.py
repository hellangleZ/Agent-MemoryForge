# -*- coding: utf-8 -*-
"""Shared helpers and state for Agent Gateway routes."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from fastapi import Cookie, Depends, Header, HTTPException, Request, Response

from config.agent_config import get_config
from agent_runtime.product.auth_models import MeResponse
from agent_runtime.product.auth_store import SQLiteAuthStore
from agent_runtime.product.auth_tokens import decode_access_token
from agent_runtime.product.conversation_store import RedisConversationStore
from agent_runtime.product.usage_store import SQLiteUsageStore
from agent_memory_framework.demo_agent import DemoAgent, DemoRuntime
from agent_memory_framework.tools import ToolRegistry
from agent_runtime.product.observability import (
    AuditEvent,
    InMemoryObservabilityStore,
    RedisObservabilityStore,
    now_s,
    redact,
)
from agent_runtime.product.full_chain_manager import FullChainManager
from utils.logging_config import get_logger
from utils.redis_helper import RedisHelper

logger = get_logger(__name__)

if TYPE_CHECKING:
    pass

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME_DIR = _REPO_ROOT / ".runtime"
_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
_PORTAL_CONFIG_PATH = _RUNTIME_DIR / "portal_config.json"

_PORTAL_AUTH_DB = str((_REPO_ROOT / ".runtime" / "portal_auth.db").resolve())
_USAGE_DB = str((_REPO_ROOT / ".runtime" / "usage.db").resolve())
try:
    _auth_store = SQLiteAuthStore(db_path=_PORTAL_AUTH_DB)
except Exception:  # pragma: no cover
    from agent_runtime.product.auth_store import InMemoryAuthStore

    _auth_store = InMemoryAuthStore()
_usage_store = SQLiteUsageStore(db_path=_USAGE_DB)
def _make_observability_store():
    if os.getenv("AGENT_OBSERVABILITY_REDIS_ENABLED", "0").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return InMemoryObservabilityStore()
    try:
        cfg = get_config()
        redis_client = RedisHelper.get_redis_client(
            host=cfg.redis_host,
            port=cfg.redis_port,
            db=cfg.redis_db,
            max_connections=20,
        )
        return RedisObservabilityStore(
            redis_client=redis_client,
            audit_key=os.getenv("AGENT_OBSERVABILITY_AUDIT_KEY")
            or "agent_gateway:audit",
            metric_key=os.getenv("AGENT_OBSERVABILITY_METRIC_KEY")
            or "agent_gateway:metrics",
            max_events=int(os.getenv("AGENT_OBSERVABILITY_MAX_EVENTS") or "50000"),
            max_metrics=int(os.getenv("AGENT_OBSERVABILITY_MAX_METRICS") or "50000"),
        )
    except Exception:
        logger.exception("Redis observability init failed; falling back to in-memory store")
        return InMemoryObservabilityStore()


_obs_store = _make_observability_store()

_ACCESS_COOKIE = "portal_access_token"
_REFRESH_COOKIE = "portal_refresh_token"

_WORKSPACE_MCP_CLIENTS: Dict[str, Any] = {}
_WORKSPACE_SECRET_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_INLINE_WORKSPACE_SECRET_NAME_RE = re.compile(
    r"(^|_)(API_KEY|ACCESS_TOKEN|TOKEN|SECRET|PASSWORD|PRIVATE_KEY|ACCESS_KEY)$",
    re.IGNORECASE,
)
_WORKSPACE_SECRET_PLACEHOLDER_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]{0,127}\}$")
_DEFAULT_WORKSPACE_MCP_HTTP_ALLOWED_HOSTS = {
    "mcp.context7.com",
    "mcp.neon.tech",
    "mcp.supabase.com",
    "supabase.com",
}
_DEFAULT_WORKSPACE_ID = "ws_default"


class PortalCustomAgent(DemoAgent):
    def __init__(self, runtime: DemoRuntime, *, system_prompt: str):
        self._custom_system_prompt = system_prompt
        super().__init__(runtime)

    def get_system_prompt(self) -> str:
        return self._custom_system_prompt

    def register_domain_tools(self, registry: ToolRegistry) -> None:
        return None


def _safe_scope_fragment(value: str) -> str:
    out = []
    for ch in str(value):
        if ch.isalnum() or ch in {"-", "_", "."}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)[:128] or "unknown"


def _full_chain_manager_for_ctx(ctx: Dict[str, str]) -> FullChainManager:
    tenant = _safe_scope_fragment(ctx.get("tenant_id", "unknown"))
    workspace = _safe_scope_fragment(ctx.get("workspace_id", "unknown"))
    scope = f"t_{tenant}__ws_{workspace}"
    return FullChainManager(
        repo_root=_REPO_ROOT,
        logs_dir=_REPO_ROOT / "logs" / "full_chain" / scope,
        pid_dir=_REPO_ROOT / ".runtime" / "full_chain" / scope,
    )


def _require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv("AGENT_GATEWAY_API_KEY")
    if not expected:
        return
    if not x_api_key or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _request_id_from_headers(request: Request) -> str:
    return request.headers.get("x-request-id") or uuid.uuid4().hex


def _trace_id_from_headers(request: Request) -> str:
    try:
        state_trace = getattr(request.state, "trace_id_override", None)
        if isinstance(state_trace, str) and state_trace.strip():
            return state_trace
    except Exception:
        pass
    return request.headers.get("x-trace-id") or uuid.uuid4().hex


def _require_workspace_id(x_workspace_id: Optional[str] = Header(default=None)) -> str:
    if not x_workspace_id:
        raise HTTPException(status_code=400, detail="Missing x-workspace-id")
    return x_workspace_id


def _normalize_memory_base_url(value: str, *, field_name: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise HTTPException(status_code=500, detail=f"{field_name} is not configured")

    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")

    normalized_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), normalized_path, "", ""))


def _memory_url_allowlist() -> set[str]:
    values = os.getenv("AGENT_GATEWAY_MEMORY_URL_ALLOWLIST", "")
    allowed: set[str] = set()
    for item in values.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        allowed.add(_normalize_memory_base_url(candidate, field_name="AGENT_GATEWAY_MEMORY_URL_ALLOWLIST"))
    return allowed


def _resolve_memory_service_url(*, configured_url: str, requested_url: Optional[str] = None) -> str:
    configured = _normalize_memory_base_url(configured_url, field_name="MEMORY_SERVICE_URL")
    requested_raw = str(requested_url or "").strip()
    if not requested_raw:
        return configured

    requested = _normalize_memory_base_url(requested_raw, field_name="memory_url")
    if requested == configured or requested in _memory_url_allowlist():
        return requested

    raise HTTPException(
        status_code=400,
        detail=(
            "memory_url override is not allowed. Configure MEMORY_SERVICE_URL on "
            "the gateway or add the exact URL to AGENT_GATEWAY_MEMORY_URL_ALLOWLIST."
        ),
    )


def _cookie_secure_flag() -> bool:
    raw = os.getenv("AUTH_COOKIE_SECURE")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    env = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    return env in {"prod", "production"}


def _set_auth_cookies(
    response: Response, *, access_token: str, refresh_token: str, expires_in: int
) -> None:
    refresh_ttl = int(os.getenv("AUTH_REFRESH_TOKEN_TTL_S", "2592000"))
    response.set_cookie(
        _ACCESS_COOKIE,
        access_token,
        httponly=True,
        secure=_cookie_secure_flag(),
        samesite="lax",
        max_age=expires_in,
        path="/",
    )
    response.set_cookie(
        _REFRESH_COOKIE,
        refresh_token,
        httponly=True,
        secure=_cookie_secure_flag(),
        samesite="lax",
        max_age=refresh_ttl,
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(_ACCESS_COOKIE, path="/")
    response.delete_cookie(_REFRESH_COOKIE, path="/")


def _bearer_token_from_headers(
    authorization: Optional[str] = Header(default=None),
    portal_access_token: Optional[str] = Cookie(default=None, alias=_ACCESS_COOKIE),
) -> str:
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
            raise HTTPException(
                status_code=401,
                detail=(
                    "Invalid Authorization header (expected: "
                    "'Authorization: Bearer <access_token>')"
                ),
            )
        return parts[1]
    if portal_access_token:
        return portal_access_token
    raise HTTPException(
        status_code=401,
        detail="Missing Authorization header or portal_access_token cookie",
    )


def _me_from_access_token(token: str) -> MeResponse:
    try:
        payload = decode_access_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid access token")
    sub = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    if not sub or not tenant_id:
        raise HTTPException(status_code=401, detail="Invalid access token")
    return MeResponse(sub=sub, tenant_id=tenant_id)


def _iso_ts(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _require_tenant_id(token: str = Depends(_bearer_token_from_headers)) -> str:
    return _me_from_access_token(token).tenant_id


def _is_admin_tenant(tenant_id: str) -> bool:
    tenant = str(tenant_id or "").strip()
    return (
        tenant == "admin" or tenant.startswith("admin_") or tenant.startswith("admin:")
    )


def _role_for_me(me: MeResponse) -> str:
    try:
        user = _auth_store.get_user(me.sub)
    except Exception:
        user = None
    if user is not None:
        role = str(getattr(user, "role", "") or "").strip().lower()
        if role:
            return "admin" if role == "admin" else "user"
    return "admin" if _is_admin_tenant(me.tenant_id) else "user"


def _require_admin(token: str = Depends(_bearer_token_from_headers)) -> MeResponse:
    me = _me_from_access_token(token)
    if _role_for_me(me) != "admin":
        raise HTTPException(status_code=403, detail="admin required")
    return me


def _platform_admin_tenants() -> set[str]:
    raw = os.getenv("PLATFORM_ADMIN_TENANTS") or os.getenv(
        "PORTAL_PLATFORM_ADMIN_TENANTS"
    )
    values = {"admin"}
    if raw:
        values.update(x.strip() for x in raw.split(",") if x.strip())
    return values


def _is_platform_admin(me: MeResponse) -> bool:
    return _role_for_me(me) == "admin" and str(me.tenant_id) in _platform_admin_tenants()


def _assert_tenant_scope(me: MeResponse, target_tenant: str) -> str:
    tenant = str(target_tenant or "").strip()
    if not tenant:
        raise HTTPException(status_code=400, detail="tenant_id required")
    if tenant == me.tenant_id or _is_platform_admin(me):
        return tenant
    raise HTTPException(status_code=403, detail="tenant scope denied")


def _workspace_member_role(
    cfg: Dict[str, Any], *, tenant_id: str, workspace_id: str, user_id: str
) -> Optional[str]:
    for member in _workspace_members_for_tenant(
        cfg, tenant_id=tenant_id, workspace_id=workspace_id
    ):
        if not isinstance(member, dict):
            continue
        candidate = str(member.get("user_id") or member.get("id") or "").strip()
        if candidate != user_id:
            continue
        role = str(member.get("role") or "member").strip().lower()
        return role or "member"
    return None


def _workspace_rbac_strict() -> bool:
    raw = os.getenv("PORTAL_WORKSPACE_RBAC_STRICT")
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _workspace_members_registry_has(
    cfg: Dict[str, Any], *, tenant_id: str, workspace_id: str
) -> bool:
    if workspace_id == _DEFAULT_WORKSPACE_ID:
        return True
    if workspace_id in _workspace_registry_for_tenant(cfg, tenant_id=tenant_id):
        return True
    members = cfg.get("workspace_members")
    if not isinstance(members, dict):
        return False
    tenant_members = members.get(tenant_id)
    if isinstance(tenant_members, list):
        return workspace_id == "default"
    return isinstance(tenant_members, dict) and workspace_id in tenant_members


def _assert_workspace_access(
    me: MeResponse,
    workspace_id: str,
    *,
    cfg: Optional[Dict[str, Any]] = None,
    write: bool = False,
    allow_owner_write: bool = False,
) -> Dict[str, Any]:
    workspace = str(workspace_id or "").strip()
    if not workspace:
        raise HTTPException(status_code=400, detail="Missing x-workspace-id")

    portal_cfg = _load_portal_config() if cfg is None else cfg
    role = _role_for_me(me)
    is_admin = role == "admin"
    member_role = _workspace_member_role(
        portal_cfg,
        tenant_id=me.tenant_id,
        workspace_id=workspace,
        user_id=me.sub,
    )

    if is_admin:
        return {
            "tenant_id": me.tenant_id,
            "workspace_id": workspace,
            "user_id": me.sub,
            "role": role,
            "member_role": member_role or "admin",
        }

    if workspace == _DEFAULT_WORKSPACE_ID and (not write or allow_owner_write):
        return {
            "tenant_id": me.tenant_id,
            "workspace_id": workspace,
            "user_id": me.sub,
            "role": role,
            "member_role": member_role or "owner",
        }

    if member_role is None:
        has_workspace_registry = bool(
            _workspace_members_registry_has(
                portal_cfg, tenant_id=me.tenant_id, workspace_id=workspace
            )
            or _workspace_mcp_for_tenant(
                portal_cfg, tenant_id=me.tenant_id, workspace_id=workspace
            )
            or _workspace_prompt_for_tenant(
                portal_cfg, tenant_id=me.tenant_id, workspace_id=workspace
            )
        )
        if has_workspace_registry or _workspace_rbac_strict():
            raise HTTPException(status_code=403, detail="workspace access denied")
        raise HTTPException(status_code=403, detail="workspace access denied")

    if write and member_role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="workspace owner required")

    return {
        "tenant_id": me.tenant_id,
        "workspace_id": workspace,
        "user_id": me.sub,
        "role": role,
        "member_role": member_role,
    }


def _require_workspace_access(
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    return _assert_workspace_access(_me_from_access_token(token), workspace_id)


def _require_full_chain_rbac(
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, str]:
    me = _me_from_access_token(token)
    if not _is_platform_admin(me):
        raise HTTPException(status_code=403, detail="platform admin required")

    tenant_id = me.tenant_id
    allowed_tenants = os.getenv("FULL_CHAIN_CONTROL_ALLOWED_TENANTS")
    if allowed_tenants:
        allow = {x.strip() for x in allowed_tenants.split(",") if x.strip()}
        if allow and tenant_id not in allow:
            raise HTTPException(status_code=403, detail="tenant not allowed")

    allowed_workspaces = os.getenv("FULL_CHAIN_CONTROL_ALLOWED_WORKSPACES")
    if allowed_workspaces:
        allow = {x.strip() for x in allowed_workspaces.split(",") if x.strip()}
        if allow and workspace_id not in allow:
            raise HTTPException(status_code=403, detail="workspace not allowed")

    return {"tenant_id": tenant_id, "workspace_id": workspace_id, "actor": me.sub}


def _require_full_chain_action(
    action: str,
    ctx: Dict[str, str] = Depends(_require_full_chain_rbac),
) -> Dict[str, str]:
    allowed_actions = os.getenv("FULL_CHAIN_CONTROL_ALLOWED_ACTIONS")
    if allowed_actions:
        allow = {x.strip() for x in allowed_actions.split(",") if x.strip()}
        if allow and action not in allow:
            raise HTTPException(status_code=403, detail="action not allowed")
    out = dict(ctx)
    out["action"] = action
    return out


def _full_chain_action_dep(action: str):
    def _dep(ctx: Dict[str, str] = Depends(_require_full_chain_rbac)) -> Dict[str, str]:
        return _require_full_chain_action(action, ctx)

    return _dep


def _audit_full_chain(
    *,
    ctx: Dict[str, str],
    actor: str,
    resource: str,
    ok: bool,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    _obs_store.record_audit(
        AuditEvent(
            ts_s=now_s(),
            tenant_id=ctx["tenant_id"],
            workspace_id=ctx["workspace_id"],
            actor=actor,
            action=f"full_chain.{ctx.get('action', 'unknown')}",
            resource=resource,
            ok=ok,
            detail=redact(detail) if detail else None,
        )
    )


def _scoped_memory_client(
    *,
    base_url: str,
    tenant_id: str,
    workspace_id: str,
    actor_user_id: Optional[str] = None,
    actor_role: Optional[str] = None,
):
    from agent_runtime.product import agent_gateway as _gateway

    client = _gateway.MemoryClient(base_url, shared_pool=True).with_scope(
        tenant_id=tenant_id, workspace_id=workspace_id
    )
    if actor_user_id:
        client = client.with_actor(
            actor_user_id=actor_user_id,
            actor_role=actor_role or "user",
        )
    return client


def _portal_config_path() -> Path:
    from agent_runtime.product import agent_gateway as _gateway

    return getattr(_gateway, "_PORTAL_CONFIG_PATH", _PORTAL_CONFIG_PATH)


def _load_portal_config() -> Dict[str, Any]:
    path = _portal_config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_portal_config(cfg: Dict[str, Any]) -> None:
    path = _portal_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(payload)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _custom_agents_for_tenant(
    cfg: Dict[str, Any], tenant_id: str, workspace_id: Optional[str] = None
) -> Dict[str, Any]:
    custom_agents = cfg.get("custom_agents")
    if not isinstance(custom_agents, dict):
        return {}
    tenant_agents = custom_agents.get(tenant_id)
    if not isinstance(tenant_agents, dict):
        return {}
    if workspace_id is not None:
        workspace_agents = tenant_agents.get(workspace_id)
        if isinstance(workspace_agents, dict):
            return workspace_agents
        return {
            agent_id: spec
            for agent_id, spec in tenant_agents.items()
            if isinstance(spec, dict)
            and (not spec.get("workspace_id") or spec.get("workspace_id") == workspace_id)
            and not any(isinstance(v, dict) for v in spec.values())
        }
    flattened: Dict[str, Any] = {}
    for key, value in tenant_agents.items():
        if not isinstance(value, dict):
            continue
        if any(isinstance(v, dict) for v in value.values()) and "id" not in value:
            flattened.update(value)
        else:
            flattened[key] = value
    return flattened


def _save_custom_agent(
    cfg: Dict[str, Any],
    *,
    tenant_id: str,
    workspace_id: str = "default",
    agent_id: str,
    payload: Dict[str, Any],
) -> None:
    _ensure_workspace_record(cfg, tenant_id=tenant_id, workspace_id=workspace_id)
    cfg.setdefault("custom_agents", {})
    cfg["custom_agents"].setdefault(tenant_id, {})
    cfg["custom_agents"][tenant_id].setdefault(workspace_id, {})
    cfg["custom_agents"][tenant_id][workspace_id][agent_id] = payload


def _delete_custom_agent(
    cfg: Dict[str, Any], *, tenant_id: str, workspace_id: str, agent_id: str
) -> bool:
    custom_agents = cfg.get("custom_agents")
    if not isinstance(custom_agents, dict):
        return False
    tenant_agents = custom_agents.get(tenant_id)
    if not isinstance(tenant_agents, dict):
        return False
    workspace_agents = tenant_agents.get(workspace_id)
    if isinstance(workspace_agents, dict) and agent_id in workspace_agents:
        del workspace_agents[agent_id]
        return True
    if agent_id in tenant_agents and isinstance(tenant_agents.get(agent_id), dict):
        del tenant_agents[agent_id]
        return True
    return False


def _tool_policy_for_workspace(
    cfg: Dict[str, Any], *, tenant_id: str, workspace_id: str
) -> Dict[str, Any]:
    policies = cfg.get("workspace_tool_policies")
    if not isinstance(policies, dict):
        return {"allowlist": [], "denylist": [], "overrides": {}}
    tenant_policies = policies.get(tenant_id)
    if not isinstance(tenant_policies, dict):
        return {"allowlist": [], "denylist": [], "overrides": {}}
    policy = tenant_policies.get(workspace_id)
    if not isinstance(policy, dict):
        return {"allowlist": [], "denylist": [], "overrides": {}}
    return {
        "allowlist": list(policy.get("allowlist") or []),
        "denylist": list(policy.get("denylist") or []),
        "overrides": dict(policy.get("overrides") or {}),
    }


def _save_tool_policy(
    cfg: Dict[str, Any], *, tenant_id: str, workspace_id: str, policy: Dict[str, Any]
) -> None:
    _ensure_workspace_record(cfg, tenant_id=tenant_id, workspace_id=workspace_id)
    cfg.setdefault("workspace_tool_policies", {})
    cfg["workspace_tool_policies"].setdefault(tenant_id, {})
    cfg["workspace_tool_policies"][tenant_id][workspace_id] = {
        "allowlist": list(policy.get("allowlist") or []),
        "denylist": list(policy.get("denylist") or []),
        "overrides": dict(policy.get("overrides") or {}),
    }


def _apply_tool_policy(
    tools: Dict[str, Any],
    *,
    policy: Dict[str, Any],
    extra_allowlist: Optional[List[str]] = None,
) -> Dict[str, Any]:
    allow = {str(t).strip() for t in (policy.get("allowlist") or []) if str(t).strip()}
    deny = {str(t).strip() for t in (policy.get("denylist") or []) if str(t).strip()}
    overrides = policy.get("overrides") or {}
    if extra_allowlist:
        extra = {str(t).strip() for t in extra_allowlist if str(t).strip()}
        allow = allow.intersection(extra) if allow else extra

    def _enabled(name: str) -> bool:
        if name in overrides:
            return bool(overrides.get(name))
        if allow and name not in allow:
            return False
        if name in deny:
            return False
        return True

    return {name: tool for name, tool in tools.items() if _enabled(name)}


def _workspace_registry_for_tenant(cfg: Dict[str, Any], *, tenant_id: str) -> Dict[str, Any]:
    workspaces = cfg.get("workspaces")
    if not isinstance(workspaces, dict):
        return {}
    tenant_workspaces = workspaces.get(tenant_id)
    return tenant_workspaces if isinstance(tenant_workspaces, dict) else {}


def _workspace_record_for_tenant(
    cfg: Dict[str, Any], *, tenant_id: str, workspace_id: str
) -> Dict[str, Any]:
    ws_id = str(workspace_id or "").strip()
    record = _workspace_registry_for_tenant(cfg, tenant_id=tenant_id).get(ws_id)
    if isinstance(record, dict):
        out = dict(record)
    elif ws_id == _DEFAULT_WORKSPACE_ID:
        out = {
            "id": _DEFAULT_WORKSPACE_ID,
            "name": "Default Workspace",
            "owner": tenant_id,
            "created_at": _iso_ts(now_s()) or "",
            "status": "active",
        }
    else:
        out = {
            "id": ws_id,
            "name": f"Workspace {ws_id}",
            "owner": tenant_id,
            "created_at": _iso_ts(now_s()) or "",
            "status": "active",
        }
    out["id"] = str(out.get("id") or ws_id)
    out.setdefault("name", "Default Workspace" if ws_id == _DEFAULT_WORKSPACE_ID else f"Workspace {ws_id}")
    out.setdefault("owner", tenant_id)
    out.setdefault("created_at", _iso_ts(now_s()) or "")
    out.setdefault("status", "active")
    return out


def _ensure_workspace_record(
    cfg: Dict[str, Any],
    *,
    tenant_id: str,
    workspace_id: str,
    name: Optional[str] = None,
    owner: Optional[str] = None,
    status: str = "active",
) -> Dict[str, Any]:
    ws_id = str(workspace_id or "").strip()
    if not ws_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    cfg.setdefault("workspaces", {})
    cfg["workspaces"].setdefault(tenant_id, {})
    if not isinstance(cfg["workspaces"][tenant_id], dict):
        cfg["workspaces"][tenant_id] = {}
    existing = cfg["workspaces"][tenant_id].get(ws_id)
    record = dict(existing) if isinstance(existing, dict) else {}
    record["id"] = ws_id
    record["name"] = str(name or record.get("name") or ("Default Workspace" if ws_id == _DEFAULT_WORKSPACE_ID else f"Workspace {ws_id}"))
    record["owner"] = str(owner or record.get("owner") or tenant_id)
    record["created_at"] = str(record.get("created_at") or _iso_ts(now_s()) or "")
    record["status"] = str(status or record.get("status") or "active")
    cfg["workspaces"][tenant_id][ws_id] = record
    return record


def _workspace_members_for_tenant(
    cfg: Dict[str, Any],
    tenant_id: str,
    workspace_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    members = cfg.get("workspace_members")
    if not isinstance(members, dict):
        return []
    tenant_members = members.get(tenant_id)
    # Back-compat: older config stored a per-tenant list (no workspace nesting).
    if isinstance(tenant_members, list):
        return tenant_members
    if not isinstance(tenant_members, dict):
        return []

    if workspace_id is None:
        # Back-compat: prefer "default" if present, otherwise return first list-like value.
        default_members = tenant_members.get("default")
        if isinstance(default_members, list):
            return default_members
        for value in tenant_members.values():
            if isinstance(value, list):
                return value
        return []

    workspace_members = tenant_members.get(workspace_id)
    if not isinstance(workspace_members, list):
        return []
    return workspace_members


def _save_workspace_members(
    cfg: Dict[str, Any],
    *,
    tenant_id: str,
    members: List[Dict[str, Any]],
    workspace_id: str = "default",
) -> None:
    _ensure_workspace_record(cfg, tenant_id=tenant_id, workspace_id=workspace_id)
    cfg.setdefault("workspace_members", {})
    existing = cfg["workspace_members"].get(tenant_id)
    if isinstance(existing, list):
        # Migrate old shape to new nested mapping.
        cfg["workspace_members"][tenant_id] = {"default": existing}
    cfg["workspace_members"].setdefault(tenant_id, {})
    if not isinstance(cfg["workspace_members"][tenant_id], dict):
        cfg["workspace_members"][tenant_id] = {}
    cfg["workspace_members"][tenant_id][workspace_id] = members


def _get_custom_agent_spec(
    *, tenant_id: str, agent_id: str, workspace_id: str
) -> Optional[Dict[str, Any]]:
    cfg = _load_portal_config()
    custom_agents = _custom_agents_for_tenant(
        cfg, tenant_id, workspace_id=workspace_id
    )
    spec = custom_agents.get(agent_id)
    if not isinstance(spec, dict):
        return None
    scoped_ws = spec.get("workspace_id")
    if scoped_ws and scoped_ws != workspace_id:
        return None
    return spec


def _streaming_enabled_for_call(*, token_callback, tools) -> bool:
    if token_callback is None:
        return False
    enabled = os.getenv("AGENT_GATEWAY_LLM_STREAMING", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled:
        return False
    if tools is not None:
        return os.getenv("AGENT_GATEWAY_STREAM_WITH_TOOLS", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    return True


def _extract_stream_delta(event) -> str:
    event_type = str(getattr(event, "type", "") or "")
    if event_type in {"response.output_text.delta", "response.text.delta"}:
        return str(getattr(event, "delta", "") or "")
    try:
        choices = getattr(event, "choices", None)
        if choices:
            delta = getattr(choices[0], "delta", None)
            if delta is not None:
                return str(getattr(delta, "content", "") or "")
    except Exception:
        return ""
    if isinstance(event, dict):
        if event.get("type") in {"response.output_text.delta", "response.text.delta"}:
            return str(event.get("delta") or "")
        choices = event.get("choices")
        if choices and isinstance(choices, list):
            delta = (choices[0] or {}).get("delta") or {}
            return str(delta.get("content") or "")
    return ""


def _normalize_openai_api_style(value: str | None = None) -> str:
    style = (
        value
        or os.getenv("OPENAI_API_STYLE")
        or os.getenv("AZURE_OPENAI_API_STYLE")
        or os.getenv("LLM_API_STYLE")
        or "auto"
    )
    normalized = str(style).strip().lower().replace("_", "-")
    aliases = {
        "chat-completions": "chat",
        "chat-completion": "chat",
        "completions": "chat",
        "response": "responses",
        "response-api": "responses",
        "responses-api": "responses",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"auto", "responses", "chat"}:
        raise RuntimeError(
            f"Unsupported LLM API style {style!r}. Use auto, responses, or chat."
        )
    return normalized


def _responses_api_unavailable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in {404, 405, 501}:
        return True
    msg = str(exc).lower()
    return any(
        marker in msg
        for marker in [
            "not supported",
            "unsupported",
            "unknown endpoint",
            "not found",
            "no route",
            "404",
            "405",
            "501",
        ]
    )


def _chat_completion_tools(tools) -> list[dict[str, Any]] | None:
    if tools is None:
        return None
    cc_tools = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        fn = {
            "name": tool.get("name"),
            "description": tool.get("description") or "",
            "parameters": tool.get("parameters")
            or {"type": "object", "properties": {}},
        }
        cc_tools.append({"type": "function", "function": fn})
    return cc_tools


def _llm_call_factory(
    azure_client, model_name: str, temperature: float, tools=None, token_callback=None
):
    def call(messages, previous_response_id: str | None = None):
        api_style = _normalize_openai_api_style()
        kwargs = {"model": model_name}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if api_style == "chat":
            if tools is not None:
                kwargs["tools"] = _chat_completion_tools(tools)
                kwargs["tool_choice"] = "auto"
        else:
            if tools is not None:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
        if previous_response_id and api_style != "chat":
            kwargs["previous_response_id"] = previous_response_id

        def _call_chat():
            chat_kwargs = dict(kwargs)
            chat_kwargs.pop("previous_response_id", None)
            if tools is not None:
                chat_kwargs["tools"] = _chat_completion_tools(tools)
                chat_kwargs["tool_choice"] = "auto"
            if _streaming_enabled_for_call(token_callback=token_callback, tools=tools):
                stream = azure_client.chat.completions.create(
                    **chat_kwargs, messages=messages, stream=True
                )
                parts = []
                for event in stream:
                    delta = _extract_stream_delta(event)
                    if not delta:
                        continue
                    parts.append(delta)
                    try:
                        token_callback(delta)
                    except Exception:
                        pass
                return {"choices": [{"message": {"content": "".join(parts)}}]}
            return azure_client.chat.completions.create(**chat_kwargs, messages=messages)

        def _call_responses():
            if _streaming_enabled_for_call(token_callback=token_callback, tools=tools):
                stream = azure_client.responses.create(
                    **kwargs, input=messages, stream=True
                )
                parts = []
                for event in stream:
                    delta = _extract_stream_delta(event)
                    if not delta:
                        continue
                    parts.append(delta)
                    try:
                        token_callback(delta)
                    except Exception:
                        pass
                return {"choices": [{"message": {"content": "".join(parts)}}]}
            return azure_client.responses.create(**kwargs, input=messages)

        if api_style == "chat":
            return _call_chat()

        try:
            return _call_responses()
        except AttributeError:
            if api_style == "responses":
                raise
            return _call_chat()
        except Exception as exc:
            msg = str(exc).lower()
            if (
                "temperature" in msg
                and "not supported" in msg
                and "temperature" in kwargs
            ):
                kwargs.pop("temperature", None)
                return _call_responses() if api_style != "chat" else _call_chat()
            if api_style == "auto" and _responses_api_unavailable(exc):
                return _call_chat()
            raise

    return call


def _get_conversation_store() -> RedisConversationStore:
    cfg = get_config()
    redis_client = RedisHelper.get_redis_client(
        host=cfg.redis_host,
        port=cfg.redis_port,
        db=cfg.redis_db,
        max_connections=20,
    )
    ttl = int(os.getenv("AGENT_CONVERSATION_TTL_SECONDS", "86400"))
    return RedisConversationStore(redis_client=redis_client, ttl_seconds=ttl)


def _dependency_status(ok: bool, *, detail: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ok": bool(ok)}
    if detail:
        payload["detail"] = detail
    return payload


def _require_dependency_ok(name: str, payload: Dict[str, Any]) -> None:
    if payload.get("ok") is True:
        return
    detail = payload.get("detail")
    raise HTTPException(
        status_code=503, detail=f"dependency {name} not ready: {detail}"
    )


def _redis_health(cfg) -> Dict[str, Any]:
    try:
        redis = RedisHelper.get_redis_client(
            host=cfg.redis_host, port=cfg.redis_port, db=cfg.redis_db
        )
        redis.ping()
        return _dependency_status(True)
    except Exception as exc:
        return _dependency_status(False, detail=str(exc))


def _memory_service_health(cfg) -> Dict[str, Any]:
    try:
        from agent_runtime.product import agent_gateway as _gateway

        client = _gateway.MemoryClient(base_url=cfg.memory_service_url)
        client.health()
        return _dependency_status(True)
    except Exception as exc:
        return _dependency_status(False, detail=str(exc))


def _embedding_service_health(cfg) -> Dict[str, Any]:
    try:
        from agent_memory_lib.embedding_client import (
            embedding_client_from_env_like_config,
        )

        embedding_client_from_env_like_config().health()
        return _dependency_status(True)
    except Exception as exc:
        return _dependency_status(False, detail=str(exc))


def _neo4j_health(cfg) -> Dict[str, Any]:
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            cfg.neo4j_uri, auth=(cfg.neo4j_user, cfg.neo4j_password)
        )
        with driver.session() as session:
            session.run("RETURN 1")
        driver.close()
        return _dependency_status(True)
    except Exception as exc:
        return _dependency_status(False, detail=str(exc))


def _workspace_mcp_cache_key(tenant_id: str, workspace_id: str) -> str:
    return f"{_safe_scope_fragment(tenant_id)}:{_safe_scope_fragment(workspace_id)}"


def _tenant_mapping(cfg: Dict[str, Any], key: str, tenant_id: str) -> Dict[str, Any]:
    outer = cfg.get(key)
    if not isinstance(outer, dict):
        return {}
    inner = outer.get(tenant_id)
    return inner if isinstance(inner, dict) else {}



def _workspace_prompt_for_tenant(
    cfg: Dict[str, Any], *, tenant_id: str, workspace_id: str
) -> Optional[str]:
    prompts = _tenant_mapping(cfg, "tenant_workspace_system_prompts", tenant_id)
    if workspace_id in prompts:
        value = prompts.get(workspace_id)
        return str(value) if value is not None else None
    return None


def _workspace_mcp_for_tenant(
    cfg: Dict[str, Any], *, tenant_id: str, workspace_id: str
) -> Dict[str, Any]:
    mcp = _tenant_mapping(cfg, "tenant_workspace_mcp", tenant_id)
    if workspace_id in mcp and isinstance(mcp.get(workspace_id), dict):
        return dict(mcp.get(workspace_id) or {})
    return {}


def _normalize_workspace_secret_name(name: str) -> str:
    value = str(name or "").strip()
    if not _WORKSPACE_SECRET_NAME_RE.fullmatch(value):
        raise HTTPException(
            status_code=400,
            detail=(
                "secret names must be environment-style identifiers "
                "such as NEON_API_KEY"
            ),
        )
    return value


def _workspace_secret_fernet():
    try:
        from cryptography.fernet import Fernet
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="cryptography is required for workspace secret storage",
        ) from exc

    material = os.getenv("PORTAL_SECRETS_KEY")
    jwt_secret = os.getenv("AUTH_JWT_SECRET")
    env = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    if not material:
        if env in {"prod", "production"}:
            raise HTTPException(
                status_code=500,
                detail="PORTAL_SECRETS_KEY must be configured in production",
            )
        material = "dev-secret"
    if material == "dev-secret" and env in {"prod", "production"}:
        raise HTTPException(
            status_code=500,
            detail="PORTAL_SECRETS_KEY must not use the development default",
        )
    if jwt_secret and material == jwt_secret and env in {"prod", "production"}:
        raise HTTPException(
            status_code=500,
            detail="PORTAL_SECRETS_KEY must be distinct from AUTH_JWT_SECRET",
        )
    digest = hashlib.sha256(str(material).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_workspace_secret(value: str) -> Dict[str, str]:
    token = _workspace_secret_fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return {"v": "1", "alg": "fernet-sha256", "ciphertext": token}


def _decrypt_workspace_secret(value: Any) -> str:
    if isinstance(value, dict):
        if str(value.get("alg") or "") != "fernet-sha256":
            return ""
        ciphertext = str(value.get("ciphertext") or "")
        if not ciphertext:
            return ""
        try:
            return (
                _workspace_secret_fernet()
                .decrypt(ciphertext.encode("utf-8"))
                .decode("utf-8")
            )
        except Exception:
            logger.warning("workspace MCP secret could not be decrypted")
            return ""
    if value is None:
        return ""
    # Back-compat for runtime configs written before encrypted secret storage.
    return str(value)


def _workspace_mcp_secrets_for_tenant(
    cfg: Dict[str, Any], *, tenant_id: str, workspace_id: str
) -> Dict[str, str]:
    secrets = _tenant_mapping(cfg, "tenant_workspace_mcp_secrets", tenant_id)
    raw = secrets.get(workspace_id)
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not _WORKSPACE_SECRET_NAME_RE.fullmatch(name):
            continue
        secret_value = _decrypt_workspace_secret(value)
        if not secret_value:
            continue
        out[name] = secret_value
    return out


def _workspace_mcp_secret_status_for_tenant(
    cfg: Dict[str, Any], *, tenant_id: str, workspace_id: str
) -> Dict[str, bool]:
    secrets = _workspace_mcp_secrets_for_tenant(
        cfg, tenant_id=tenant_id, workspace_id=workspace_id
    )
    return {name: bool(value) for name, value in sorted(secrets.items())}


def _save_workspace_mcp_secrets_for_tenant(
    cfg: Dict[str, Any],
    *,
    tenant_id: str,
    workspace_id: str,
    values: Dict[str, str],
    clear: Optional[List[str]] = None,
) -> Dict[str, bool]:
    _ensure_workspace_record(cfg, tenant_id=tenant_id, workspace_id=workspace_id)
    cfg.setdefault("tenant_workspace_mcp_secrets", {})
    cfg["tenant_workspace_mcp_secrets"].setdefault(tenant_id, {})
    tenant_secrets = cfg["tenant_workspace_mcp_secrets"][tenant_id]
    if not isinstance(tenant_secrets, dict):
        tenant_secrets = {}
        cfg["tenant_workspace_mcp_secrets"][tenant_id] = tenant_secrets

    current = tenant_secrets.get(workspace_id)
    if not isinstance(current, dict):
        current = {}

    for name in clear or []:
        current.pop(_normalize_workspace_secret_name(name), None)

    for name, value in (values or {}).items():
        secret_name = _normalize_workspace_secret_name(name)
        secret_value = str(value or "")
        if len(secret_value) > 8192:
            raise HTTPException(
                status_code=400,
                detail=f"secret {secret_name} is too large",
            )
        if secret_value:
            current[secret_name] = _encrypt_workspace_secret(secret_value)

    if current:
        tenant_secrets[workspace_id] = current
    else:
        tenant_secrets.pop(workspace_id, None)

    return {name: bool(value) for name, value in sorted(current.items())}


def _extract_inline_workspace_mcp_secrets(
    mcp: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, str]]:
    """Move env-style inline secret values from MCP JSON into secret storage."""

    values: Dict[str, str] = {}

    def should_extract(name: str, value: str) -> bool:
        secret_name = str(name or "").strip().upper()
        secret_value = str(value or "").strip()
        secret_like_value = bool(
            re.search(
                r"(?i)\b(Bearer\s+)?(sk-[A-Za-z0-9_-]{8,}|[A-Za-z0-9_-]{24,})\b",
                secret_value,
            )
        )
        return (
            bool(secret_value)
            and bool(_WORKSPACE_SECRET_NAME_RE.fullmatch(secret_name))
            and (
                bool(_INLINE_WORKSPACE_SECRET_NAME_RE.search(secret_name))
                or secret_name in {"AUTHORIZATION", "X_API_KEY", "API_KEY"}
                or secret_like_value
            )
            and not _WORKSPACE_SECRET_PLACEHOLDER_RE.fullmatch(secret_value)
        )

    def visit(node: Any) -> tuple[Any, bool]:
        if isinstance(node, list):
            changed = False
            next_items: List[Any] = []
            for item in node:
                next_item, item_changed = visit(item)
                next_items.append(next_item)
                changed = changed or item_changed
            return (next_items, changed) if changed else (node, False)

        if isinstance(node, dict):
            changed = False
            next_obj: Dict[str, Any] = {}
            for key, raw_value in node.items():
                if isinstance(raw_value, str) and should_extract(str(key), raw_value):
                    secret_name = str(key).strip().upper()
                    values[secret_name] = raw_value.strip()
                    next_obj[key] = f"${{{secret_name}}}"
                    changed = True
                    continue

                next_value, value_changed = visit(raw_value)
                next_obj[key] = next_value
                changed = changed or value_changed
            return (next_obj, True) if changed else (node, False)

        return node, False

    sanitized = dict(mcp or {})
    for field in ("mcp_servers_json", "mcp_stdio_json", "mcp_http_headers_json"):
        raw = str(sanitized.get(field) or "").strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        next_value, changed = visit(parsed)
        if changed:
            sanitized[field] = json.dumps(next_value, ensure_ascii=False, indent=2)

    return sanitized, values


def _workspace_mcp_http_allowed_hosts() -> set[str]:
    raw = os.getenv("AGENT_WORKSPACE_MCP_HTTP_ALLOWED_HOSTS")
    if raw is None:
        return set(_DEFAULT_WORKSPACE_MCP_HTTP_ALLOWED_HOSTS)
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _host_matches_allowlist(host: str, allowlist: set[str]) -> bool:
    value = str(host or "").strip().lower().strip(".")
    if not value:
        return False
    for allowed in allowlist:
        entry = allowed.strip().lower().strip(".")
        if not entry:
            continue
        if value == entry:
            return True
        if entry.startswith("*.") and value.endswith("." + entry[2:]):
            return True
        if entry.startswith(".") and value.endswith(entry):
            return True
    return False


def _is_private_mcp_host(host: str) -> bool:
    value = str(host or "").strip().lower().strip("[]")
    if not value:
        return True
    if value in {"localhost", "localhost.localdomain"}:
        return True
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def _validate_workspace_mcp_http_url(url: str) -> str:
    raw = str(url or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="invalid MCP HTTP URL")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="MCP HTTP URL must not include credentials")

    host = str(parsed.hostname or "").strip().lower()
    if not os.getenv("AGENT_WORKSPACE_MCP_HTTP_ALLOW_PRIVATE", "").strip() == "1":
        if parsed.scheme != "https" or _is_private_mcp_host(host):
            raise HTTPException(
                status_code=400,
                detail="MCP HTTP URL must be public HTTPS unless explicitly allowed by the operator",
            )

    if not _host_matches_allowlist(host, _workspace_mcp_http_allowed_hosts()):
        raise HTTPException(
            status_code=400,
            detail="MCP HTTP host is not in AGENT_WORKSPACE_MCP_HTTP_ALLOWED_HOSTS",
        )
    return raw


def _validate_workspace_mcp_stdio_command(command: str) -> None:
    enabled = os.getenv("AGENT_WORKSPACE_MCP_STDIO_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled:
        raise HTTPException(
            status_code=400,
            detail="Workspace stdio MCP is disabled; use HTTP MCP or operator-registered MCP servers",
        )

    raw_allow = os.getenv("AGENT_WORKSPACE_MCP_STDIO_ALLOWED_COMMANDS", "")
    allowlist = {item.strip() for item in raw_allow.split(",") if item.strip()}
    if not allowlist:
        raise HTTPException(
            status_code=400,
            detail="Workspace stdio MCP requires AGENT_WORKSPACE_MCP_STDIO_ALLOWED_COMMANDS",
        )

    cmd = str(command or "").strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Workspace stdio MCP command is required")

    path_allowlist: set[str] = set()
    name_allowlist: set[str] = set()
    for entry in allowlist:
        if "/" in entry or "\\" in entry:
            path_allowlist.add(os.path.realpath(entry))
            continue
        name_allowlist.add(entry)
        resolved = shutil.which(entry)
        if resolved:
            path_allowlist.add(os.path.realpath(resolved))

    command_has_path = "/" in cmd or "\\" in cmd
    if command_has_path:
        if os.path.realpath(cmd) in path_allowlist:
            return
        raise HTTPException(status_code=400, detail="Workspace stdio MCP command is not allowed")

    if cmd in name_allowlist:
        return
    resolved = shutil.which(cmd)
    if resolved and os.path.realpath(resolved) in path_allowlist:
        return
    raise HTTPException(status_code=400, detail="Workspace stdio MCP command is not allowed")


def _workspace_mcp_operator_fallback_enabled() -> bool:
    return os.getenv("AGENT_WORKSPACE_MCP_USE_OPERATOR_FALLBACK", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _reject_workspace_secret_args(server: Dict[str, Any], secret_env: Dict[str, str]) -> None:
    args = server.get("args") or []
    if isinstance(args, str):
        args = [args]
    for arg in args:
        text = str(arg or "")
        for match in re.finditer(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", text):
            name = match.group(1).strip()
            if name in secret_env or _INLINE_WORKSPACE_SECRET_NAME_RE.search(name):
                raise HTTPException(
                    status_code=400,
                    detail="Workspace MCP secrets must be passed through env or headers, not command args",
                )


def _workspace_ids_for_tenant(cfg: Dict[str, Any], *, tenant_id: str) -> List[str]:
    ids = {_DEFAULT_WORKSPACE_ID}
    ids.update(_workspace_registry_for_tenant(cfg, tenant_id=tenant_id).keys())
    ids.update(
        _tenant_mapping(cfg, "tenant_workspace_system_prompts", tenant_id).keys()
    )
    ids.update(_tenant_mapping(cfg, "tenant_workspace_mcp", tenant_id).keys())
    ids.update(_tenant_mapping(cfg, "tenant_workspace_mcp_secrets", tenant_id).keys())
    members = cfg.get("workspace_members")
    tenant_members = members.get(tenant_id) if isinstance(members, dict) else None
    if isinstance(tenant_members, dict):
        ids.update(tenant_members.keys())
    return sorted(str(x) for x in ids if str(x).strip())


def _save_workspace_config_for_tenant(
    cfg: Dict[str, Any],
    *,
    tenant_id: str,
    workspace_id: str,
    system_prompt: Optional[str],
    mcp: Dict[str, Any],
) -> None:
    _ensure_workspace_record(cfg, tenant_id=tenant_id, workspace_id=workspace_id)
    cfg.setdefault("tenant_workspace_system_prompts", {})
    cfg.setdefault("tenant_workspace_mcp", {})
    cfg["tenant_workspace_system_prompts"].setdefault(tenant_id, {})
    cfg["tenant_workspace_mcp"].setdefault(tenant_id, {})
    if system_prompt is not None:
        cfg["tenant_workspace_system_prompts"][tenant_id][workspace_id] = system_prompt
    cfg["tenant_workspace_mcp"][tenant_id][workspace_id] = dict(mcp or {})


def _delete_workspace_config_for_tenant(
    cfg: Dict[str, Any], *, tenant_id: str, workspace_id: str
) -> bool:
    removed = False
    for key in (
        "workspaces",
        "tenant_workspace_system_prompts",
        "tenant_workspace_mcp",
        "tenant_workspace_mcp_secrets",
        "workspace_tool_policies",
        "custom_agents",
        "workspace_members",
    ):
        outer = cfg.get(key)
        if not isinstance(outer, dict):
            continue
        tenant_cfg = outer.get(tenant_id)
        if isinstance(tenant_cfg, dict) and workspace_id in tenant_cfg:
            del tenant_cfg[workspace_id]
            removed = True
    return removed


def _workspace_mcp_clients() -> Dict[str, Any]:
    return _WORKSPACE_MCP_CLIENTS


def _build_mcp_clients_from_workspace_config(
    workspace_id: str, *, tenant_id: str
) -> Dict[str, Any]:
    try:
        from agent_memory_framework.mcp_http_client import (
            HttpMCPServerConfig,
            StreamableHttpMCPClient,
        )
        from agent_memory_framework.mcp_stdio_client import (
            StdioMCPClient,
            StdioMCPServerConfig,
            mcp_servers_from_env,
            resolve_mcp_server_args,
            resolve_mcp_server_env,
            resolve_mcp_server_headers,
        )
    except Exception as exc:
        logger.info(
            "MCP client imports failed; using config-only MCP clients",
            extra={"error": str(exc)},
        )

        @dataclass(frozen=True)
        class HttpMCPServerConfig:  # type: ignore[no-redef]
            url: str
            headers: Optional[Dict[str, str]] = None
            timeout_s: float = 30.0

        class StreamableHttpMCPClient:  # type: ignore[no-redef]
            def __init__(self, server: HttpMCPServerConfig):
                self._server = server

        @dataclass(frozen=True)
        class StdioMCPServerConfig:  # type: ignore[no-redef]
            command: str
            args: List[str]
            env: Optional[Dict[str, str]] = None
            cwd: Optional[str] = None

        class StdioMCPClient:  # type: ignore[no-redef]
            def __init__(self, server: StdioMCPServerConfig):
                self._server = server

        def _expand(value: str, *, environ: Dict[str, str], missing: List[str]) -> str:
            def _replace(match: re.Match[str]) -> str:
                key = match.group(1).strip()
                found = environ.get(key, "")
                if found:
                    return found
                missing.append(key)
                return ""

            return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", _replace, value)

        def resolve_mcp_server_args(server, *, environ=None):  # type: ignore[no-redef]
            source = dict(environ or {})
            missing: List[str] = []
            args = server.get("args") or []
            if isinstance(args, str):
                args = [args]
            return [
                _expand(str(item), environ=source, missing=missing)
                for item in list(args or [])
            ], missing

        def resolve_mcp_server_env(server, *, environ=None):  # type: ignore[no-redef]
            source = dict(environ or {})
            missing: List[str] = []
            env_obj = server.get("env") or {}
            out: Dict[str, str] = {}
            if isinstance(env_obj, dict):
                for key, value in env_obj.items():
                    out[str(key)] = _expand(str(value), environ=source, missing=missing)
            for key in server.get("required_env") or []:
                name = str(key).strip()
                if source.get(name):
                    out[name] = source[name]
                else:
                    missing.append(name)
            return (out or None), missing

        def resolve_mcp_server_headers(server, *, environ=None):  # type: ignore[no-redef]
            source = dict(environ or {})
            missing: List[str] = []
            headers_obj = server.get("headers") or {}
            out: Dict[str, str] = {}
            if isinstance(headers_obj, dict):
                for key, value in headers_obj.items():
                    out[str(key)] = _expand(str(value), environ=source, missing=missing)
            return (out or None), missing

        def mcp_servers_from_env():  # type: ignore[no-redef]
            raw = (os.getenv("AGENT_MEMORY_MCP_SERVERS") or "").strip()
            if not raw:
                return []
            try:
                parsed = json.loads(raw)
            except Exception:
                return []
            return parsed if isinstance(parsed, list) else []

    portal_cfg = _load_portal_config()
    raw = _workspace_mcp_for_tenant(
        portal_cfg, tenant_id=tenant_id, workspace_id=workspace_id
    )
    has_workspace_mcp_config = bool(raw)
    secret_env = _workspace_mcp_secrets_for_tenant(
        portal_cfg, tenant_id=tenant_id, workspace_id=workspace_id
    )
    clients: Dict[str, Any] = {}

    servers_json = (raw.get("mcp_servers_json") or "").strip()
    if servers_json:
        servers = json.loads(servers_json)
        if isinstance(servers, list):
            for server in servers:
                if not isinstance(server, dict):
                    continue
                transport = str(server.get("transport") or "").strip().lower()
                namespace = str(server.get("namespace") or "mcp").strip() or "mcp"
                if transport == "stdio":
                    cmd = str(server.get("command") or "").strip()
                    if not cmd:
                        continue
                    _reject_workspace_secret_args(server, secret_env)
                    args, missing_args = resolve_mcp_server_args(
                        server, environ=secret_env
                    )
                    env, missing_env = resolve_mcp_server_env(
                        server, environ=secret_env
                    )
                    missing = sorted(set(missing_args + missing_env))
                    if missing:
                        logger.info(
                            "Skipping MCP stdio server with missing env",
                            extra={
                                "namespace": namespace,
                                "missing_env": missing,
                            },
                        )
                        continue
                    _validate_workspace_mcp_stdio_command(cmd)
                    clients[namespace] = StdioMCPClient(
                        StdioMCPServerConfig(
                            command=cmd,
                            args=args,
                            env=env,
                            cwd=str(server.get("cwd")).strip()
                            if server.get("cwd")
                            else None,
                        )
                    )
                elif transport in {"http", "streamable-http", "streamable_http"}:
                    url = str(server.get("url") or "").strip()
                    if not url:
                        continue
                    url = _validate_workspace_mcp_http_url(url)
                    headers, missing_headers = resolve_mcp_server_headers(
                        server, environ=secret_env
                    )
                    if missing_headers:
                        logger.info(
                            "Skipping MCP HTTP server with missing env",
                            extra={
                                "namespace": namespace,
                                "missing_env": missing_headers,
                            },
                        )
                        continue
                    timeout_s = server.get("timeout_s")
                    clients[namespace] = StreamableHttpMCPClient(
                        HttpMCPServerConfig(
                            url=url,
                            headers=headers,
                            timeout_s=float(timeout_s)
                            if timeout_s is not None
                            else 30.0,
                        )
                    )

    stdio_json = (raw.get("mcp_stdio_json") or "").strip()
    if stdio_json and "mcp" not in clients:
        obj = json.loads(stdio_json)
        if isinstance(obj, dict):
            cmd = str(obj.get("command") or "").strip()
            if cmd:
                _reject_workspace_secret_args(obj, secret_env)
                args, missing_args = resolve_mcp_server_args(obj, environ=secret_env)
                env, missing_env = resolve_mcp_server_env(obj, environ=secret_env)
                missing = sorted(set(missing_args + missing_env))
                if missing:
                    logger.info(
                        "Skipping workspace MCP stdio server with missing env",
                        extra={"namespace": "mcp", "missing_env": missing},
                    )
                else:
                    _validate_workspace_mcp_stdio_command(cmd)
                    clients["mcp"] = StdioMCPClient(
                        StdioMCPServerConfig(command=cmd, args=args, env=env, cwd=None)
                    )

    http_url = (raw.get("mcp_http_url") or "").strip()
    if http_url:
        http_url = _validate_workspace_mcp_http_url(http_url)
        namespace = str(raw.get("mcp_http_namespace") or "mcp").strip() or "mcp"
        if namespace not in clients:
            headers = None
            headers_json = (raw.get("mcp_http_headers_json") or "").strip()
            if headers_json:
                obj = json.loads(headers_json)
                if isinstance(obj, dict):
                    headers, missing_headers = resolve_mcp_server_headers(
                        {"headers": obj}, environ=secret_env
                    )
                    if missing_headers:
                        logger.info(
                            "Skipping workspace MCP HTTP server with missing env",
                            extra={
                                "namespace": namespace,
                                "missing_env": missing_headers,
                            },
                        )
                        headers = None
                        http_url = ""
            if http_url:
                clients[namespace] = StreamableHttpMCPClient(
                    HttpMCPServerConfig(url=http_url, headers=headers, timeout_s=30.0)
                )

    if (
        not clients
        and not has_workspace_mcp_config
        and _workspace_mcp_operator_fallback_enabled()
    ):
        operator_env = dict(os.environ)
        for server in mcp_servers_from_env():
            if not isinstance(server, dict):
                continue
            namespace = str(server.get("namespace") or "mcp").strip() or "mcp"
            transport = str(server.get("transport") or "").strip().lower()
            if transport == "stdio":
                cmd = str(server.get("command") or "").strip()
                if cmd:
                    args, missing_args = resolve_mcp_server_args(
                        server, environ=operator_env
                    )
                    env, missing_env = resolve_mcp_server_env(
                        server, environ=operator_env
                    )
                    missing = sorted(set(missing_args + missing_env))
                    if missing:
                        logger.info(
                            "Skipping env MCP stdio server with missing env",
                            extra={
                                "namespace": namespace,
                                "missing_env": missing,
                            },
                        )
                        continue
                    clients[namespace] = StdioMCPClient(
                        StdioMCPServerConfig(
                            command=cmd, args=args, env=env, cwd=None
                        )
                    )
            elif transport in {"http", "streamable-http", "streamable_http"}:
                url = str(server.get("url") or "").strip()
                if url:
                    headers, missing_headers = resolve_mcp_server_headers(
                        server, environ=operator_env
                    )
                    if missing_headers:
                        logger.info(
                            "Skipping env MCP HTTP server with missing env",
                            extra={
                                "namespace": namespace,
                                "missing_env": missing_headers,
                            },
                        )
                        continue
                    clients[namespace] = StreamableHttpMCPClient(
                        HttpMCPServerConfig(
                            url=url, headers=headers, timeout_s=30.0
                        )
                    )

    return clients


__all__ = [
    "PortalCustomAgent",
    "_ACCESS_COOKIE",
    "_REFRESH_COOKIE",
    "_auth_store",
    "_usage_store",
    "_PORTAL_CONFIG_PATH",
    "_obs_store",
    "_full_chain_manager_for_ctx",
    "_request_id_from_headers",
    "_trace_id_from_headers",
    "_require_api_key",
    "_require_workspace_id",
    "_bearer_token_from_headers",
    "_me_from_access_token",
    "_iso_ts",
    "_require_tenant_id",
    "_is_admin_tenant",
    "_role_for_me",
    "_is_platform_admin",
    "_assert_tenant_scope",
    "_assert_workspace_access",
    "_require_workspace_access",
    "_require_admin",
    "_require_full_chain_rbac",
    "_require_full_chain_action",
    "_full_chain_action_dep",
    "_audit_full_chain",
    "_scoped_memory_client",
    "_load_portal_config",
    "_save_portal_config",
    "_custom_agents_for_tenant",
    "_save_custom_agent",
    "_delete_custom_agent",
    "_tool_policy_for_workspace",
    "_save_tool_policy",
    "_apply_tool_policy",
    "_workspace_members_for_tenant",
    "_save_workspace_members",
    "_workspace_registry_for_tenant",
    "_workspace_record_for_tenant",
    "_ensure_workspace_record",
    "_workspace_mcp_cache_key",
    "_workspace_prompt_for_tenant",
    "_workspace_mcp_for_tenant",
    "_workspace_mcp_secrets_for_tenant",
    "_workspace_mcp_secret_status_for_tenant",
    "_save_workspace_mcp_secrets_for_tenant",
    "_extract_inline_workspace_mcp_secrets",
    "_workspace_ids_for_tenant",
    "_save_workspace_config_for_tenant",
    "_delete_workspace_config_for_tenant",
    "_get_custom_agent_spec",
    "_llm_call_factory",
    "_get_conversation_store",
    "_dependency_status",
    "_require_dependency_ok",
    "_redis_health",
    "_memory_service_health",
    "_embedding_service_health",
    "_neo4j_health",
    "_workspace_mcp_clients",
    "_build_mcp_clients_from_workspace_config",
]
