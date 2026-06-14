# -*- coding: utf-8 -*-
"""Core (non-portal) routes for Agent Gateway."""

from __future__ import annotations

import json
import hashlib
import os
import queue
import sys
import threading
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from agent_memory_framework.llm_clients import LLMProviderConfigurationError
from agent_memory_framework.plugins import discover_tools, register_discovered_tools
from agent_memory_framework.plugins import discover_tools_from_mcp
from agent_memory_framework.tool_intent import (
    should_discover_external_tools,
    should_discover_namespace,
)
from config.agent_config import get_config
from agent_memory_framework.demo_agent import DemoRuntime
from agent_runtime.product.chat_models import ChatMessage, ChatRequest, ChatResponse
from agent_runtime.memory_distill.distill_settings import MemoryDistillSettings
from agent_runtime.memory_distill.job_schema import new_job
from agent_runtime.memory_distill.queue import enqueue_distill_job
from agent_runtime.product.observability import (
    AuditEvent,
    MetricPoint,
    log_structured_event,
    now_s,
    redact,
)
from agent_runtime.product.usage_store import estimate_message_tokens
from agent_runtime.product.gateway.models import (
    FileFirstGetProxyRequest,
    FileFirstReadProxyRequest,
    FileFirstSearchProxyRequest,
    FileFirstWriteProxyRequest,
    FullChainStartRequest,
)
from agent_runtime.product.full_chain_manager import ManagedService
from utils.logging_config import get_logger
from utils.exceptions import MemoryServiceError

from agent_runtime.product.gateway.portal_helpers import (
    PortalCustomAgent,
    _apply_tool_policy,
    _assert_workspace_access,
    _audit_full_chain,
    _bearer_token_from_headers,
    _full_chain_action_dep,
    _full_chain_manager_for_ctx,
    _get_conversation_store,
    _get_custom_agent_spec,
    _iso_ts,
    _load_portal_config,
    _me_from_access_token,
    _obs_store,
    _request_id_from_headers,
    _require_api_key,
    _require_dependency_ok,
    _require_workspace_id,
    _resolve_memory_service_url,
    _scoped_memory_client,
    _tool_policy_for_workspace,
    _trace_id_from_headers,
    _workspace_mcp_cache_key,
    _workspace_mcp_clients,
    _workspace_prompt_for_tenant,
    _llm_call_factory,
    _usage_store,
)
from agent_runtime.product.step_mode import (
    STEP_MODE_DECIDER_SYSTEM_PROMPT,
    build_confirmation_message,
    build_wm_state_for_steps,
    is_cancel,
    is_yes,
    normalize_steps,
    parse_numbered_steps,
    parse_step_mode_decider_json,
)

router = APIRouter()
logger = get_logger(__name__)

CHAT_LLM_NOT_CONFIGURED_MESSAGE = (
    "LLM provider is not configured for this deployment. Ask an administrator "
    "to configure provider credentials and restart the gateway."
)
_MCP_TOOL_DISCOVERY_CACHE: Dict[str, Dict[str, Any]] = {}
_MCP_TOOL_DISCOVERY_CACHE_LOCK = threading.Lock()
_MEMORY_TOOL_NAMES = {
    "retrieve_stm_summaries",
    "retrieve_ltm_preferences",
    "search_semantic_memories",
    "search_graph_memories",
    "manage_working_memory",
}


def _audit_message_summary(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summary: List[Dict[str, Any]] = []
    for msg in messages:
        role = str(msg.get("role") or "")
        content = str(msg.get("content") or "")
        summary.append(
            {
                "role": role,
                "content_len": len(content),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()
                if content
                else "",
            }
        )
    return summary


def _summarize_tool_args(args: Any) -> Dict[str, Any]:
    """Return a non-content summary of tool args for stdout logs."""
    if not isinstance(args, dict):
        return {"type": type(args).__name__}
    summary: Dict[str, Any] = {
        "arg_keys": sorted(str(k) for k in args.keys()),
    }
    query = args.get("query")
    if isinstance(query, str):
        summary["query_len"] = len(query)
        summary["query_sha256"] = hashlib.sha256(query.encode("utf-8")).hexdigest()
    if "top_k" in args:
        summary["top_k"] = args.get("top_k")
    if "last_k" in args:
        summary["last_k"] = args.get("last_k")
    if "limit" in args:
        summary["limit"] = args.get("limit")
    if "key" in args:
        key = args.get("key")
        summary["key_present"] = bool(str(key or "").strip())
    return summary


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _reference_global_tools_enabled() -> bool:
    return _env_bool("AGENT_REFERENCE_RUNTIME_GLOBAL_TOOLS_ENABLED", default=False)


def _mcp_tool_discovery_cache_ttl_s() -> float:
    try:
        return float(os.getenv("AGENT_MCP_TOOL_DISCOVERY_CACHE_TTL_S", "300"))
    except Exception:
        return 300.0


def _discover_tools_from_mcp_cached(
    *,
    client: Any,
    namespace: str,
    cache_key: str,
) -> Dict[str, Any]:
    ttl_s = _mcp_tool_discovery_cache_ttl_s()
    scoped_key = f"{cache_key}:{namespace}"
    if ttl_s > 0:
        now = time.time()
        with _MCP_TOOL_DISCOVERY_CACHE_LOCK:
            cached = _MCP_TOOL_DISCOVERY_CACHE.get(scoped_key)
            cache_age_s = now - float((cached or {}).get("at_s") or 0.0)
            if isinstance(cached, dict) and cache_age_s <= ttl_s:
                tools = cached.get("tools")
                if isinstance(tools, dict):
                    return dict(tools)

    discovered = discover_tools_from_mcp(client, namespace=namespace)
    if ttl_s > 0:
        with _MCP_TOOL_DISCOVERY_CACHE_LOCK:
            _MCP_TOOL_DISCOVERY_CACHE[scoped_key] = {
                "at_s": time.time(),
                "tools": dict(discovered),
            }
    return discovered


def _preference_confirmation_required() -> bool:
    return _env_bool("PREFERENCE_REQUIRE_CONFIRMATION", default=False)


def _distill_every_n_rounds() -> int:
    raw = os.getenv("MEMORY_DISTILL_EVERY_N_ROUNDS")
    if raw is None:
        raw = os.getenv("MEMORY_DISTILL_STM_CHECKPOINT_ROUNDS")
    try:
        return max(1, int(raw or "1"))
    except Exception:
        return 1


def _enqueue_success_chat_distill(
    *,
    settings: MemoryDistillSettings,
    tenant_id: str,
    workspace_id: str,
    user_id: str,
    conversation_id: str,
    merged_messages: List[Dict[str, Any]],
    memory_client,
    last_user: str,
    answer: str,
    trace_id: str,
) -> Dict[str, Any]:
    """Queue all durable memory distillation outside the chat response path."""
    if not settings.enabled:
        return {"status": "skipped", "reason": "disabled"}

    round_id = max(1, len([m for m in merged_messages if m.get("role") == "assistant"]))
    every_n = _distill_every_n_rounds()
    if round_id % every_n != 0:
        return {
            "status": "skipped",
            "reason": "cadence",
            "round_id": round_id,
            "every_n": every_n,
        }

    chunk_messages = merged_messages[-(every_n * 2) :]
    if len(chunk_messages) % 2 != 0:
        chunk_messages = chunk_messages[1:]

    prior_summaries: List[Dict[str, Any]] = []
    try:
        resp = memory_client.retrieve_stm(conversation_id=conversation_id, last_k=2)
        if resp.get("status") == "success" and isinstance(resp.get("data"), list):
            prior_summaries = [x for x in resp["data"] if isinstance(x, dict)]
    except Exception:
        prior_summaries = []

    job = new_job(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        user_id=user_id,
        conversation_id=conversation_id,
        round_id=round_id,
        messages=chunk_messages,
        prior_stm_summaries=prior_summaries,
        chunk_rounds=every_n,
        last_user=last_user,
        assistant_answer=answer,
        trace_id=trace_id,
    )
    result = enqueue_distill_job(settings=settings, job=job)
    if not isinstance(result, dict):
        result = {"status": "unknown"}
    return {
        **result,
        "round_id": round_id,
        "every_n": every_n,
        "chunk_message_count": len(chunk_messages),
        "prior_stm_count": len(prior_summaries),
    }


def _quota_error_detail(decision) -> Dict[str, Any]:
    return {
        "error": "quota_exceeded",
        "message": "Monthly token quota exceeded",
        "month": decision.month,
        "used_tokens": decision.used_tokens,
        "estimated_tokens": decision.estimated_tokens,
        "monthly_token_quota": decision.monthly_token_quota,
        "remaining_tokens": decision.remaining_tokens,
    }


def _raise_if_chat_quota_exceeded(
    *,
    tenant_id: str,
    workspace_id: str,
    user_id: str,
    agent: str,
    trace_id: str,
    estimated_tokens: int,
) -> None:
    decision = _usage_store.check_quota(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        user_id=user_id,
        estimated_tokens=estimated_tokens,
    )
    if decision.allowed:
        return
    detail = _quota_error_detail(decision)
    _obs_store.record_metric(
        MetricPoint(
            ts_s=now_s(),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name="chat.quota_blocked",
            value=1.0,
            tags={"agent": agent, "user_id": user_id},
        )
    )
    _obs_store.record_audit(
        AuditEvent(
            ts_s=now_s(),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor=user_id,
            action="chat.quota_blocked",
            resource=f"agent:{agent}",
            ok=False,
            detail=redact({"trace_id": trace_id, **detail}),
        )
    )
    raise HTTPException(status_code=429, detail=detail)


def _raise_memory_proxy_error(exc: MemoryServiceError) -> None:
    status_code = (
        exc.status_code
        if exc.status_code and 400 <= int(exc.status_code) <= 599
        else 502
    )
    detail: Dict[str, Any] = {"error": "memory_service_error", "message": exc.message}
    response_text = (exc.details or {}).get("response")
    if response_text:
        try:
            detail["upstream"] = json.loads(response_text)
        except Exception:
            detail["upstream_response"] = str(response_text)[:2000]
    logger.warning(
        "Memory proxy request failed",
        extra={"status_code": status_code, "details": exc.details},
    )
    raise HTTPException(status_code=status_code, detail=detail) from exc


class RunRecordResponse(BaseModel):
    id: str
    trace_id: str
    agent: str
    status: str
    created_at: str
    duration_ms: Optional[float] = None


class RunListResponse(BaseModel):
    runs: List[RunRecordResponse]
    total: int


class TraceSpan(BaseModel):
    id: str
    parent_id: Optional[str] = None
    name: str
    start_time: str
    end_time: Optional[str] = None
    duration_ms: Optional[float] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)


class TraceEvent(BaseModel):
    id: str
    ts_s: float
    name: str
    attributes: Dict[str, Any] = Field(default_factory=dict)


class TraceResponse(BaseModel):
    id: str
    trace_id: str
    spans: List[TraceSpan] = Field(default_factory=list)
    events: List[TraceEvent] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RunTraceResponse(BaseModel):
    trace: TraceResponse


def _require_full_chain_control_enabled() -> None:
    if os.getenv("FULL_CHAIN_CONTROL_ENABLED") != "1":
        raise HTTPException(status_code=403, detail="Full-chain control disabled")


def _validate_port(value: int, *, name: str) -> None:
    if int(value) < 1024 or int(value) > 65535:
        raise HTTPException(status_code=400, detail=f"invalid {name} port")


def _wait_http_ok(url: str, *, timeout_s: float = 0.3, attempts: int = 50) -> None:
    import requests

    last_exc: Exception | None = None
    for _ in range(int(attempts)):
        try:
            resp = requests.get(url, timeout=float(timeout_s))
            if 200 <= int(resp.status_code) < 500:
                return
        except Exception as exc:
            last_exc = exc
        time.sleep(0.2)

    if last_exc is not None:
        raise RuntimeError(
            f"service not ready: {url} ({type(last_exc).__name__}: {last_exc})"
        )
    raise RuntimeError(f"service not ready: {url}")


def _tail_lines(path: str, *, tail: int) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        if tail > 0:
            return lines[-tail:]
        return lines
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="log not found")


@router.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True}


@router.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"ok": True}


@router.get("/readyz")
def readyz() -> Dict[str, Any]:
    from agent_runtime.product import agent_gateway as _gateway

    cfg = get_config()
    deps = {
        "redis": _gateway._redis_health(cfg),
        "neo4j": _gateway._neo4j_health(cfg),
        "embedding": _gateway._embedding_service_health(cfg),
        "memory": _gateway._memory_service_health(cfg),
    }
    ok = all(v.get("ok") for v in deps.values())
    if not ok:
        raise HTTPException(status_code=503, detail={"ok": False, "dependencies": deps})
    return {"ok": True, "dependencies": deps}


@router.get("/v1/full-chain/dependencies")
def full_chain_dependencies(
    _: None = Depends(_require_api_key),
    ctx: Dict[str, str] = Depends(_full_chain_action_dep("services")),
) -> Dict[str, Any]:
    _require_full_chain_control_enabled()
    from agent_runtime.product import agent_gateway as _gateway

    cfg = get_config()

    deps = {
        "redis": _gateway._redis_health(cfg),
        "neo4j": _gateway._neo4j_health(cfg),
        "embedding": _gateway._embedding_service_health(cfg),
        "memory": _gateway._memory_service_health(cfg),
    }
    for name, payload in deps.items():
        _require_dependency_ok(name, payload)

    _audit_full_chain(
        ctx=ctx, actor=ctx.get("actor") or "system", resource="full_chain", ok=True
    )
    return {"status": "success", "data": deps}


@router.get("/v1/agents")
def list_agents(_: None = Depends(_require_api_key)) -> Dict[str, Any]:
    from agent_runtime.product.agent_registry import discover_product_agents

    agents = discover_product_agents()
    payload = {key: value.spec for key, value in sorted(agents.items())}
    return {
        "status": "success",
        "data": payload,
        "agents": payload,
    }


@router.get("/v1/full-chain/status")
def full_chain_status(
    _: None = Depends(_require_api_key),
    ctx: Dict[str, str] = Depends(_full_chain_action_dep("status")),
) -> Dict[str, Any]:
    _require_full_chain_control_enabled()
    manager = _full_chain_manager_for_ctx(ctx)
    running = manager.status()
    _audit_full_chain(
        ctx=ctx,
        actor=ctx.get("actor") or "system",
        resource="full_chain",
        ok=True,
        detail={"services": list(running.keys())},
    )
    return {
        "status": "success",
        "data": {
            name: {
                "pid": info.pid,
                "started_at_s": info.started_at_s,
                "log_path": str(info.log_path) if info.log_path else None,
            }
            for name, info in running.items()
        },
    }


@router.get("/v1/full-chain/services")
def full_chain_services(
    _: None = Depends(_require_api_key),
    ctx: Dict[str, str] = Depends(_full_chain_action_dep("services")),
) -> Dict[str, Any]:
    _require_full_chain_control_enabled()
    _audit_full_chain(
        ctx=ctx, actor=ctx.get("actor") or "system", resource="full_chain", ok=True
    )
    manager = _full_chain_manager_for_ctx(ctx)
    return {"status": "success", "data": {"services": manager.known_services()}}


@router.post("/v1/full-chain/stop")
def full_chain_stop(
    _: None = Depends(_require_api_key),
    ctx: Dict[str, str] = Depends(_full_chain_action_dep("stop")),
) -> Dict[str, Any]:
    _require_full_chain_control_enabled()
    manager = _full_chain_manager_for_ctx(ctx)
    manager.stop_all()
    _audit_full_chain(
        ctx=ctx, actor=ctx.get("actor") or "system", resource="full_chain", ok=True
    )
    return {"status": "success"}


@router.get("/v1/full-chain/logs")
def full_chain_logs(
    service: str,
    tail: int = 200,
    _: None = Depends(_require_api_key),
    ctx: Dict[str, str] = Depends(_full_chain_action_dep("logs")),
) -> Dict[str, Any]:
    _require_full_chain_control_enabled()
    if tail < 1:
        tail = 1
    if tail > 2000:
        tail = 2000
    manager = _full_chain_manager_for_ctx(ctx)
    log_path = manager.logs_path(service)
    if log_path is None:
        raise HTTPException(status_code=404, detail="log not found")
    logs = _tail_lines(str(log_path), tail=tail)
    _audit_full_chain(
        ctx=ctx,
        actor=ctx.get("actor") or "system",
        resource=f"full_chain:{service}",
        ok=True,
        detail={"tail": tail},
    )
    return {"status": "success", "data": {"service": service, "logs": logs}}


@router.get("/v1/full-chain/logs/stream")
def full_chain_logs_stream(
    service: str,
    tail: int = 200,
    interval_s: float = 1.0,
    max_events: int = 200,
    _: None = Depends(_require_api_key),
    ctx: Dict[str, str] = Depends(_full_chain_action_dep("logs_stream")),
) -> StreamingResponse:
    _require_full_chain_control_enabled()
    manager = _full_chain_manager_for_ctx(ctx)
    log_path = manager.logs_path(service)
    if log_path is None:
        raise HTTPException(status_code=404, detail="log not found")

    if tail < 0:
        tail = 0
    if max_events < 1:
        max_events = 1

    def _gen() -> Iterator[bytes]:
        lines = _tail_lines(str(log_path), tail=tail)
        emitted = 0
        for line in lines:
            yield f"data: {line}\n\n".encode("utf-8")
            emitted += 1
            if emitted >= max_events:
                return
            if interval_s > 0:
                time.sleep(interval_s)

    _audit_full_chain(
        ctx=ctx,
        actor=ctx.get("actor") or "system",
        resource=f"full_chain:{service}",
        ok=True,
    )
    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.post("/v1/full-chain/start")
def full_chain_start(
    req: FullChainStartRequest,
    _: None = Depends(_require_api_key),
    ctx: Dict[str, str] = Depends(_full_chain_action_dep("start")),
) -> Dict[str, Any]:
    _require_full_chain_control_enabled()
    _validate_port(req.memory_port, name="memory")
    _validate_port(req.gateway_port, name="gateway")

    manager = _full_chain_manager_for_ctx(ctx)
    services = [
        ManagedService(
            name="memory_service",
            cmd=[
                sys.executable,
                "-m",
                "uvicorn",
                "agent_memory_service.app:create_app",
                "--factory",
                "--host",
                "0.0.0.0",
                "--port",
                str(req.memory_port),
            ],
            cwd=manager._repo_root,
            env={},
        ),
        ManagedService(
            name="gateway",
            cmd=[
                sys.executable,
                "-m",
                "uvicorn",
                "agent_memory_service.gateway.app:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(req.gateway_port),
            ],
            cwd=manager._repo_root,
            env={},
        ),
    ]
    if req.start_distill_worker:
        services.append(
            ManagedService(
                name="distill_worker",
                cmd=[sys.executable, "-m", "scripts.memory_distill_worker"],
                cwd=manager._repo_root,
                env={},
            )
        )

    started = manager.start_group(services, quiet=not req.verbose)
    if req.require_dependencies_healthy:
        _wait_http_ok(f"{req.memory_url.rstrip('/')}/health")
        _wait_http_ok(f"http://127.0.0.1:{req.gateway_port}/health")
    _audit_full_chain(
        ctx=ctx,
        actor=ctx.get("actor") or "system",
        resource="full_chain",
        ok=True,
        detail={"services": list(started.keys())},
    )
    return {
        "status": "success",
        "data": {
            name: {
                "pid": info.pid,
                "log_path": str(info.log_path) if info.log_path else None,
            }
            for name, info in started.items()
        },
    }


@router.post("/v1/full-chain/restart")
def full_chain_restart(
    req: FullChainStartRequest,
    _: None = Depends(_require_api_key),
    ctx: Dict[str, str] = Depends(_full_chain_action_dep("restart")),
) -> Dict[str, Any]:
    _require_full_chain_control_enabled()
    payload = req.model_copy(update={"restart": True})
    _audit_full_chain(
        ctx=ctx, actor=ctx.get("actor") or "system", resource="full_chain", ok=True
    )
    return full_chain_start(payload, _, ctx)


def _write_metadata_for_gateway(
    req: FileFirstWriteProxyRequest, *, me, ctx: Dict[str, Any]
) -> Dict[str, Any]:
    metadata = dict(req.metadata or {})
    tier = str(req.tier or "").strip().lower()
    role = str(ctx.get("role") or "user").strip().lower()

    requested_user_id = str(req.user_id or metadata.get("user_id") or "").strip()
    if tier in {"preferences", "stm", "wm"}:
        if requested_user_id and requested_user_id != me.sub and role != "admin":
            raise HTTPException(status_code=403, detail="memory user scope denied")
        metadata["user_id"] = requested_user_id or me.sub

    if req.key is not None:
        metadata["key"] = req.key
    if req.value is not None:
        metadata["value"] = req.value
    if req.subject is not None:
        metadata["subject"] = req.subject
    if req.relation is not None:
        metadata["relation"] = req.relation
    if req.obj is not None:
        metadata["obj"] = req.obj
    if req.state is not None:
        metadata["state"] = req.state
    if req.ttl_s is not None:
        metadata["ttl_s"] = int(req.ttl_s)
    if req.conversation_id:
        metadata.setdefault("conversation_id", req.conversation_id)
    if req.task_id:
        metadata.setdefault("task_id", req.task_id)
    return metadata


def _record_memory_write_proxy_observability(
    *,
    tenant_id: str,
    workspace_id: str,
    actor: str,
    tier: str,
    scope: str,
    content: str,
    metadata: Dict[str, Any],
    result: Dict[str, Any],
    duration_ms: float,
) -> None:
    content_text = str(content or "")
    data = result.get("data") if isinstance(result, dict) else None
    detail = {
        "tier": tier,
        "scope": scope,
        "content_len": len(content_text),
        "content_sha256": hashlib.sha256(content_text.encode("utf-8")).hexdigest()
        if content_text
        else "",
        "metadata_keys": sorted(str(k) for k in metadata.keys()),
        "path": data.get("path") if isinstance(data, dict) else None,
        "duration_ms": round(float(duration_ms), 3),
    }
    try:
        log_structured_event(
            logger,
            "memory.write",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor=actor,
            **detail,
        )
        _obs_store.record_metric(
            MetricPoint(
                ts_s=now_s(),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                name="memory.write.duration_ms",
                value=float(duration_ms),
                tags={"tier": tier},
            )
        )
        _obs_store.record_audit(
            AuditEvent(
                ts_s=now_s(),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                actor=actor,
                action="memory.write",
                resource=f"memory:{tier}",
                ok=True,
                detail=redact(detail),
            )
        )
    except Exception:
        logger.debug("memory write observability failed", exc_info=True)


@router.post("/v1/memory/write")
def memory_write(
    req: FileFirstWriteProxyRequest,
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    """Proxy file-first writes to memory service with auth + server-side scoping."""
    cfg = get_config()
    me = _me_from_access_token(token)
    base_url = _resolve_memory_service_url(
        configured_url=cfg.memory_service_url,
        requested_url=req.memory_url,
    )
    ctx = _assert_workspace_access(me, workspace_id)
    metadata = _write_metadata_for_gateway(req, me=me, ctx=ctx)

    client = _scoped_memory_client(
        base_url=base_url,
        tenant_id=me.tenant_id,
        workspace_id=workspace_id,
        actor_user_id=me.sub,
        actor_role=str(ctx.get("role") or "user"),
    )

    started = time.monotonic()
    try:
        result = client.memory_write(
            tier=req.tier,
            scope=req.scope,
            content=req.content,
            metadata=metadata,
            target=req.target,
            conversation_id=req.conversation_id,
            task_id=req.task_id,
        )
    except MemoryServiceError as exc:
        _raise_memory_proxy_error(exc)

    duration_ms = (time.monotonic() - started) * 1000
    _record_memory_write_proxy_observability(
        tenant_id=me.tenant_id,
        workspace_id=workspace_id,
        actor=me.sub,
        tier=str(req.tier or "").strip().lower(),
        scope=str(req.scope or ""),
        content=req.content,
        metadata=metadata,
        result=result,
        duration_ms=duration_ms,
    )
    return result


@router.post("/v1/memory/search")
def memory_search(
    req: FileFirstSearchProxyRequest,
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    """Proxy file-first search to memory service with auth + scoping."""
    cfg = get_config()
    me = _me_from_access_token(token)
    base_url = _resolve_memory_service_url(
        configured_url=cfg.memory_service_url,
        requested_url=req.memory_url,
    )
    ctx = _assert_workspace_access(me, workspace_id)

    client = _scoped_memory_client(
        base_url=base_url,
        tenant_id=me.tenant_id,
        workspace_id=workspace_id,
        actor_user_id=me.sub,
        actor_role=str(ctx.get("role") or "user"),
    )

    try:
        return client.memory_search(
            query=req.query,
            top_k=int(req.top_k),
            tiers=list(req.tiers) if req.tiers else None,
            scopes=list(req.scopes) if req.scopes else None,
            memory_kinds=list(req.memory_kinds) if req.memory_kinds else None,
            path_prefixes=list(req.path_prefixes) if req.path_prefixes else None,
        )
    except MemoryServiceError as exc:
        _raise_memory_proxy_error(exc)


@router.post("/v1/memory/read")
def memory_read(
    req: FileFirstReadProxyRequest,
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    """Proxy direct memory reads to memory service with auth + scoping."""
    cfg = get_config()
    me = _me_from_access_token(token)
    base_url = _resolve_memory_service_url(
        configured_url=cfg.memory_service_url,
        requested_url=req.memory_url,
    )
    ctx = _assert_workspace_access(me, workspace_id)

    if str(req.tier or "").strip().lower() == "preferences":
        requested_user = str(req.user_id or "").strip()
        if requested_user and requested_user != me.sub and ctx.get("role") != "admin":
            raise HTTPException(status_code=403, detail="preference user scope denied")
        if not requested_user:
            req = req.model_copy(update={"user_id": me.sub})

    client = _scoped_memory_client(
        base_url=base_url,
        tenant_id=me.tenant_id,
        workspace_id=workspace_id,
        actor_user_id=me.sub,
        actor_role=str(ctx.get("role") or "user"),
    )

    try:
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
    except MemoryServiceError as exc:
        _raise_memory_proxy_error(exc)


@router.post("/v1/memory/get")
def memory_get(
    req: FileFirstGetProxyRequest,
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
) -> Dict[str, Any]:
    """Proxy file-first get to memory service with auth + scoping."""
    cfg = get_config()
    me = _me_from_access_token(token)
    base_url = _resolve_memory_service_url(
        configured_url=cfg.memory_service_url,
        requested_url=req.memory_url,
    )
    ctx = _assert_workspace_access(me, workspace_id)

    client = _scoped_memory_client(
        base_url=base_url,
        tenant_id=me.tenant_id,
        workspace_id=workspace_id,
        actor_user_id=me.sub,
        actor_role=str(ctx.get("role") or "user"),
    )

    try:
        return client.memory_get(
            path=req.path,
            start_line=req.start_line,
            max_lines=req.max_lines,
        )
    except MemoryServiceError as exc:
        _raise_memory_proxy_error(exc)


@router.post("/v1/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    request: Request,
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
    store=Depends(_get_conversation_store),
) -> ChatResponse:
    cfg = get_config()

    if not req.messages:
        return ChatResponse(
            status="error",
            conversation_id=req.conversation_id or "",
            error="messages must not be empty",
        )

    request_id = _request_id_from_headers(request)
    trace_id = _trace_id_from_headers(request)
    chat_started_monotonic_s = time.monotonic()

    me = _me_from_access_token(token)
    tenant_id = me.tenant_id
    if req.user_id != me.sub:
        req = req.model_copy(update={"user_id": me.sub})

    portal_cfg = _load_portal_config()
    ctx = _assert_workspace_access(me, workspace_id, cfg=portal_cfg)
    default_system_prompt = _workspace_prompt_for_tenant(
        portal_cfg, tenant_id=tenant_id, workspace_id=workspace_id
    )

    custom_spec = _get_custom_agent_spec(
        tenant_id=tenant_id, agent_id=req.agent, workspace_id=workspace_id
    )
    custom_tools: List[str] = []
    if custom_spec:
        custom_prompt = str(custom_spec.get("system_prompt") or "").strip()
        if custom_prompt:
            default_system_prompt = custom_prompt
        custom_tools = list(custom_spec.get("tools") or [])

    tool_policy = _tool_policy_for_workspace(
        portal_cfg, tenant_id=tenant_id, workspace_id=workspace_id
    )

    if (
        req.system_prompt
        and isinstance(req.system_prompt, str)
        and req.system_prompt.strip()
    ):
        default_system_prompt = req.system_prompt.strip()

    conversation_id = req.conversation_id or f"conv_{uuid.uuid4().hex}"
    store_conversation_id = f"{tenant_id}:{workspace_id}:{conversation_id}"

    try:
        max_rounds = int(os.getenv("AGENT_GATEWAY_HISTORY_ROUNDS", "10") or "10")
    except Exception:
        max_rounds = 10
    max_rounds = max(0, max_rounds)
    history_read_limit = max(1, max_rounds * 2)

    if callable(getattr(type(store), "get_recent", None)):
        persisted = store.get_recent(
            store_conversation_id, max_messages=history_read_limit
        )
    else:
        persisted = store.get(store_conversation_id)
    persisted_raw_messages = getattr(persisted, "messages", None) if persisted else None
    persisted_messages: List[Dict[str, Any]] = (
        list(persisted_raw_messages) if isinstance(persisted_raw_messages, list) else []
    )
    persisted_raw_metadata = getattr(persisted, "metadata", None) if persisted else None
    persisted_metadata: Dict[str, Any] = (
        dict(persisted_raw_metadata) if isinstance(persisted_raw_metadata, dict) else {}
    )

    incoming_messages = [m.model_dump(exclude_none=True) for m in req.messages]
    merged_messages = persisted_messages + incoming_messages

    logger.info(
        "chat request",
        extra={
            "request_id": request_id,
            "trace_id": trace_id,
            "conversation_id": store_conversation_id,
            "user_id": req.user_id,
            "agent": req.agent,
            "incoming_messages": len(incoming_messages),
            "persisted_messages": len(persisted_messages),
        },
    )
    log_structured_event(
        logger,
        "chat.request",
        request_id=request_id,
        trace_id=trace_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        user_id=req.user_id,
        agent=req.agent,
        conversation_id=store_conversation_id,
        incoming_message_count=len(incoming_messages),
        persisted_message_count=len(persisted_messages),
    )

    _obs_store.record_metric(
        MetricPoint(
            ts_s=now_s(),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name="chat.requests",
            value=1.0,
            tags={"agent": req.agent},
        )
    )
    _obs_store.record_audit(
        AuditEvent(
            ts_s=now_s(),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor=req.user_id,
            action="chat.request",
            resource=f"agent:{req.agent}",
            ok=True,
            detail=redact(
                {
                    "trace_id": trace_id,
                    "conversation_id": store_conversation_id,
                    "incoming_messages": _audit_message_summary(incoming_messages),
                }
            ),
        )
    )

    last_user = None
    for msg in reversed(incoming_messages):
        if msg.get("role") == "user":
            last_user = msg.get("content")
            break

    if not last_user:
        _obs_store.record_audit(
            AuditEvent(
                ts_s=now_s(),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                actor=req.user_id,
                action="chat.reject",
                resource=f"agent:{req.agent}",
                ok=False,
                detail=redact(
                    {"trace_id": trace_id, "reason": "last user message not found"}
                ),
            )
        )
        return ChatResponse(
            status="error",
            conversation_id=conversation_id,
            error="last user message not found",
        )

    input_token_estimate = estimate_message_tokens(merged_messages)
    if default_system_prompt:
        input_token_estimate += estimate_message_tokens(
            [{"role": "system", "content": default_system_prompt}]
        )
    _raise_if_chat_quota_exceeded(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        user_id=req.user_id,
        agent=req.agent,
        trace_id=trace_id,
        estimated_tokens=input_token_estimate,
    )

    from agent_runtime.product import agent_gateway as _gateway

    try:
        azure_client, model_name = _gateway.create_azure_openai_client()
    except LLMProviderConfigurationError:
        _obs_store.record_metric(
            MetricPoint(
                ts_s=now_s(),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                name="chat.errors",
                value=1.0,
                tags={"agent": req.agent, "reason": "llm_provider_not_configured"},
            )
        )
        _obs_store.record_audit(
            AuditEvent(
                ts_s=now_s(),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                actor=req.user_id,
                action="chat.error",
                resource=f"agent:{req.agent}",
                ok=False,
                detail=redact(
                    {"trace_id": trace_id, "error": "llm_provider_not_configured"}
                ),
            )
        )
        logger.warning(
            "chat rejected because llm provider is not configured",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "conversation_id": store_conversation_id,
                "user_id": req.user_id,
                "agent": req.agent,
            },
        )
        return ChatResponse(
            status="error",
            conversation_id=conversation_id,
            trace_id=trace_id,
            error=CHAT_LLM_NOT_CONFIGURED_MESSAGE,
        )

    def _record_success_usage(answer_text: str) -> None:
        try:
            output_tokens = estimate_message_tokens(
                [{"role": "assistant", "content": answer_text or ""}]
            )
            event = _usage_store.record_usage(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                user_id=req.user_id,
                agent_id=req.agent,
                model=model_name,
                input_tokens=input_token_estimate,
                output_tokens=output_tokens,
                status="success",
                trace_id=trace_id,
            )
            _obs_store.record_metric(
                MetricPoint(
                    ts_s=now_s(),
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    name="chat.tokens",
                    value=float(event.total_tokens),
                    tags={
                        "agent": req.agent,
                        "model": model_name,
                        "user_id": req.user_id,
                    },
                )
            )
        except Exception:
            logger.debug("usage event write failed", exc_info=True)

    memory_client = _scoped_memory_client(
        base_url=cfg.memory_service_url,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=req.user_id,
        actor_role=str(ctx.get("role") or "user"),
    )

    # ---- Step-mode gating (plan confirmation) ----
    #
    # We persist a pending step-plan draft in the conversation store metadata.
    # The user never sees internal identifiers; the UI prompt asks for `yes` or
    # a numbered `1- ...` list (max 10 steps).
    step_mode_enabled = os.getenv("AGENT_STEP_MODE_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }
    if step_mode_enabled:
        step_mode_meta = persisted_metadata.get("step_mode")
        if not isinstance(step_mode_meta, dict):
            step_mode_meta = {}

        pending_status = str(step_mode_meta.get("status") or "").strip().lower()
        if pending_status == "awaiting_confirmation":
            draft_goal = str(step_mode_meta.get("goal") or "").strip()
            draft_steps = normalize_steps(step_mode_meta.get("steps"), max_steps=10)
            source_query = (
                str(step_mode_meta.get("source_user_query") or "").strip() or last_user
            )

            user_text = str(last_user or "")
            if is_cancel(user_text):
                persisted_metadata.pop("step_mode", None)
                answer = (
                    "好的，已取消按步骤推进。你可以继续描述你想要我直接回答的问题。"
                )
                merged_messages.append({"role": "assistant", "content": answer})
                store.put(
                    conversation_id=store_conversation_id,
                    user_id=req.user_id,
                    messages=merged_messages,
                    metadata=persisted_metadata,
                )
                _record_success_usage(answer)
                return ChatResponse(
                    status="success",
                    conversation_id=conversation_id,
                    trace_id=trace_id,
                    answer=answer,
                    messages=[ChatMessage(**m) for m in merged_messages],
                )

            if is_yes(user_text):
                chosen_steps = draft_steps
                chosen_goal = draft_goal
            else:
                user_steps = parse_numbered_steps(user_text, max_steps=10)
                if user_steps is not None:
                    chosen_steps = user_steps
                    chosen_goal = draft_goal
                elif user_text.strip().lower() in {"no", "n", "否", "不", "不要"}:
                    # User declined step-mode; answer the original request normally.
                    persisted_metadata.pop("step_mode", None)
                    last_user = source_query
                    chosen_steps = []
                    chosen_goal = ""
                else:
                    answer = (
                        "请回复 `yes` 直接开始，或用以下强制格式发送你认可的步骤（最多10条）：\n"
                        "1- ...\n2- ...\n3- ..."
                    )
                    merged_messages.append({"role": "assistant", "content": answer})
                    store.put(
                        conversation_id=store_conversation_id,
                        user_id=req.user_id,
                        messages=merged_messages,
                        metadata=persisted_metadata,
                    )
                    _record_success_usage(answer)
                    return ChatResponse(
                        status="success",
                        conversation_id=conversation_id,
                        trace_id=trace_id,
                        answer=answer,
                        messages=[ChatMessage(**m) for m in merged_messages],
                    )

            if chosen_steps:
                wm_state = build_wm_state_for_steps(
                    conversation_id=conversation_id,
                    user_id=req.user_id,
                    goal=chosen_goal,
                    steps=chosen_steps,
                )
                try:
                    memory_client.store_wm(
                        user_id=req.user_id,
                        task_id=conversation_id,
                        state=wm_state,
                    )
                except Exception:
                    logger.warning(
                        "step-mode wm write failed; continuing without wm",
                        extra={
                            "trace_id": trace_id,
                            "conversation_id": store_conversation_id,
                        },
                        exc_info=True,
                    )
                persisted_metadata.pop("step_mode", None)
                # Use a synthetic prompt so the agent executes the first step, rather
                # than replying to "yes".
                last_user = f"开始执行第1步：{chosen_steps[0]}"

        else:
            # If no active WM exists yet, ask the LLM whether to offer step-mode.
            try:
                wm_resp = memory_client.retrieve_wm(
                    user_id=req.user_id, task_id=conversation_id
                )
                wm_state = wm_resp.get("data") if isinstance(wm_resp, dict) else None
            except Exception:
                wm_state = None
            wm_active = (
                isinstance(wm_state, dict)
                and str(wm_state.get("status") or "").strip().lower() == "active"
            )
            if not wm_active:
                try:
                    llm_call = _llm_call_factory(
                        azure_client, model_name, 0.1, tools=None
                    )
                    raw = llm_call(
                        [
                            {
                                "role": "system",
                                "content": STEP_MODE_DECIDER_SYSTEM_PROMPT,
                            },
                            {"role": "user", "content": str(last_user)},
                        ]
                    )
                    # Normalize OpenAI SDK response to text.
                    text = ""
                    if hasattr(raw, "output_text"):
                        text = str(getattr(raw, "output_text") or "")
                    else:
                        try:
                            choices = getattr(raw, "choices", None)
                            if choices and hasattr(choices[0], "message"):
                                text = str(choices[0].message.content or "")
                        except Exception:
                            text = str(raw)
                    data = parse_step_mode_decider_json(text)
                    offer = bool(isinstance(data, dict) and data.get("offer") is True)
                    goal = (
                        str(data.get("goal") or "").strip()
                        if isinstance(data, dict)
                        else ""
                    )
                    steps = normalize_steps(
                        data.get("steps") if isinstance(data, dict) else None,
                        max_steps=10,
                    )
                    if offer and steps:
                        persisted_metadata["step_mode"] = {
                            "status": "awaiting_confirmation",
                            "goal": goal,
                            "steps": steps,
                            "source_user_query": str(last_user),
                        }
                        answer = build_confirmation_message(
                            goal=goal, steps=steps, max_steps=10
                        )
                        merged_messages.append({"role": "assistant", "content": answer})
                        store.put(
                            conversation_id=store_conversation_id,
                            user_id=req.user_id,
                            messages=merged_messages,
                            metadata=persisted_metadata,
                        )
                        _record_success_usage(answer)
                        return ChatResponse(
                            status="success",
                            conversation_id=conversation_id,
                            trace_id=trace_id,
                            answer=answer,
                            messages=[ChatMessage(**m) for m in merged_messages],
                        )
                except Exception:
                    logger.debug(
                        "step-mode decider skipped",
                        extra={
                            "trace_id": trace_id,
                            "conversation_id": store_conversation_id,
                        },
                        exc_info=True,
                    )

    # ---- Preference confirmation gating ----
    #
    # Optional human-confirmation mode for sensitive deployments. Product default
    # is automatic memory distillation with evidence gates, not per-item prompts.
    pref_require_confirm = _preference_confirmation_required()
    pref_meta = persisted_metadata.get("preference_confirmation")
    if not isinstance(pref_meta, dict):
        pref_meta = {}
    pending_pref_status = str(pref_meta.get("status") or "").strip().lower()
    if pref_require_confirm and pending_pref_status == "awaiting_confirmation":
        pending_items = pref_meta.get("items")
        if not isinstance(pending_items, list):
            pending_items = []

        user_text = str(last_user or "")

        def _is_no(text: str) -> bool:
            return str(text or "").strip().lower() in {
                "no",
                "n",
                "否",
                "不",
                "不要",
                "不用",
                "算了",
            }

        if is_yes(user_text) or _is_no(user_text):
            if is_yes(user_text):
                stored = 0
                for it in pending_items:
                    if not isinstance(it, dict):
                        continue
                    k = str(it.get("key") or "").strip()
                    if not k:
                        continue
                    v = it.get("value")
                    try:
                        memory_client.store_ltm_preference(
                            user_id=req.user_id,
                            key=k,
                            value=v,
                        )
                        stored += 1
                        _obs_store.record_audit(
                            AuditEvent(
                                ts_s=now_s(),
                                tenant_id=tenant_id,
                                workspace_id=workspace_id,
                                actor=req.user_id,
                                action="preference.store",
                                resource=f"ltm_preference:{k}",
                                ok=True,
                                detail=redact(
                                    {
                                        "trace_id": trace_id,
                                        "source": str(
                                            it.get("source") or "pending_confirm"
                                        ),
                                        "confidence": it.get("confidence"),
                                        "confirmed": True,
                                    }
                                ),
                            )
                        )
                    except Exception as exc:
                        logger.warning("preference confirm store failed: %s", exc)

                answer = (
                    "好的，我已记住你的偏好。"
                    if stored
                    else "好的，但这次没有可保存的偏好项。"
                )
            else:
                answer = "好的，我不会保存这条偏好。"

            persisted_metadata.pop("preference_confirmation", None)
            merged_messages.append({"role": "assistant", "content": answer})
            store.put(
                conversation_id=store_conversation_id,
                user_id=req.user_id,
                messages=merged_messages,
                metadata=persisted_metadata,
            )
            _record_success_usage(answer)
            return ChatResponse(
                status="success",
                conversation_id=conversation_id,
                trace_id=trace_id,
                answer=answer,
                messages=[ChatMessage(**m) for m in merged_messages],
            )

    agent_cls = None
    if not custom_spec:
        try:
            agent_cls = _gateway._load_agent_class(req.agent)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"Unknown or unsupported agent: {req.agent!r}"
            ) from exc

    def _tool_call_hook(event_type: str, payload: Dict[str, Any]) -> None:
        try:
            tool_name = str((payload or {}).get("tool_name") or "").strip()
            tool_call_id = str((payload or {}).get("tool_call_id") or "").strip()
            detail = {
                "trace_id": trace_id,
                "conversation_id": store_conversation_id,
                "agent": req.agent,
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "event": event_type,
            }
            if event_type == "tool.start":
                detail["tool_args"] = redact((payload or {}).get("tool_args") or {})
            if event_type == "tool.end":
                detail["ok"] = bool((payload or {}).get("ok", True))
                result_summary = (payload or {}).get("result_summary")
                if isinstance(result_summary, dict):
                    detail["result_summary"] = result_summary

            _obs_store.record_audit(
                AuditEvent(
                    ts_s=now_s(),
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    actor=req.user_id,
                    action=event_type,
                    resource=f"tool:{tool_name}" if tool_name else "tool:unknown",
                    ok=True,
                    detail=detail,
                )
            )
            log_detail = {
                "trace_id": trace_id,
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "user_id": req.user_id,
                "conversation_id": store_conversation_id,
                "agent": req.agent,
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "tool_category": (
                    "memory_recall"
                    if tool_name in _MEMORY_TOOL_NAMES
                    else "external_or_domain"
                ),
            }
            if event_type == "tool.start":
                log_detail["tool_args_summary"] = _summarize_tool_args(
                    (payload or {}).get("tool_args") or {}
                )
            if event_type == "tool.end":
                log_detail["ok"] = bool((payload or {}).get("ok", True))
                result_summary = (payload or {}).get("result_summary")
                if isinstance(result_summary, dict):
                    log_detail["result_summary"] = result_summary
                duration_ms = (payload or {}).get("duration_ms")
                if duration_ms is not None:
                    log_detail["duration_ms"] = duration_ms
            log_structured_event(logger, event_type, **log_detail)
            try:
                cb = getattr(request.state, "agent_sse_event_callback", None)
                if cb:
                    cb(event_type, detail)
            except Exception:
                pass
        except Exception:
            return

    token_callback = getattr(request.state, "agent_token_callback", None)

    base_runtime = DemoRuntime(
        agent_id=cfg.agent_id,
        user_id=req.user_id,
        memory_client=memory_client,
        llm_call_fn=_llm_call_factory(
            azure_client,
            model_name,
            req.temperature,
            token_callback=token_callback,
        ),
        conversation_id=conversation_id,
        trace_id=trace_id,
        config={
            "stm_max_summaries": req.stm_max_summaries,
            "stm_top_k": req.stm_top_k,
            "stm_relevance_threshold": req.stm_relevance_threshold,
            "max_tool_turns": req.max_tool_turns,
            "system_prompt": default_system_prompt,
            "tool_call_hook": _tool_call_hook,
        },
    )

    if custom_spec:
        prompt = default_system_prompt or "You are a helpful assistant."
        agent = PortalCustomAgent(base_runtime, system_prompt=prompt)
    else:
        agent = agent_cls(base_runtime)

    if getattr(cfg, "mcp_tools_enabled", True):
        try:
            mcp_cache_key = _workspace_mcp_cache_key(tenant_id, workspace_id)
            clients = _workspace_mcp_clients().get(mcp_cache_key) or {}
            if clients:
                configured_namespaces = sorted(clients.keys())
                selected_namespaces = [
                    namespace
                    for namespace in configured_namespaces
                    if should_discover_namespace(namespace, last_user)
                ]
                mcp_intent_detail = {
                    "trace_id": trace_id,
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "user_id": req.user_id,
                    "conversation_id": store_conversation_id,
                    "agent": req.agent,
                    "configured_namespaces": configured_namespaces,
                    "selected_namespaces": selected_namespaces,
                    "skipped_namespaces": [
                        n for n in configured_namespaces if n not in selected_namespaces
                    ],
                }
                _obs_store.record_audit(
                    AuditEvent(
                        ts_s=now_s(),
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        actor=req.user_id,
                        action="mcp.intent",
                        resource=f"agent:{req.agent}",
                        ok=True,
                        detail=redact(mcp_intent_detail),
                    )
                )
                log_structured_event(logger, "mcp.intent", **mcp_intent_detail)
                if not selected_namespaces:
                    logger.debug(
                        "Skipping MCP discovery for turn without external tool intent",
                        extra={
                            "trace_id": trace_id,
                            "workspace_id": workspace_id,
                            "mcp_namespaces": configured_namespaces,
                        },
                    )
                for namespace, client in clients.items():
                    if namespace not in selected_namespaces:
                        continue
                    discovered = _discover_tools_from_mcp_cached(
                        client=client,
                        namespace=namespace,
                        cache_key=mcp_cache_key,
                    )
                    discovered = _apply_tool_policy(
                        discovered,
                        policy=tool_policy,
                        extra_allowlist=custom_tools if custom_spec else None,
                    )
                    register_discovered_tools(agent.tool_registry, discovered)
                if selected_namespaces:
                    logger.info(
                        "MCP tools registered",
                        extra={
                            "trace_id": trace_id,
                            "workspace_id": workspace_id,
                            "mcp_namespaces": selected_namespaces,
                        },
                    )
            else:
                global_discovery_allowed = (
                    _reference_global_tools_enabled()
                    and should_discover_external_tools(last_user)
                )
                log_structured_event(
                    logger,
                    "mcp.intent",
                    trace_id=trace_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    user_id=req.user_id,
                    conversation_id=store_conversation_id,
                    agent=req.agent,
                    configured_namespaces=[],
                    selected_namespaces=["global"] if global_discovery_allowed else [],
                    skipped_namespaces=[],
                    global_discovery_allowed=global_discovery_allowed,
                )
                if global_discovery_allowed:
                    discovered = discover_tools()
                    discovered = _apply_tool_policy(
                        discovered,
                        policy=tool_policy,
                        extra_allowlist=custom_tools if custom_spec else None,
                    )
                    register_discovered_tools(agent.tool_registry, discovered)
        except Exception as exc:
            logger.info("MCP tools not enabled/available: %s", exc)

    tools_payload: List[Dict[str, Any]] = []
    visible_tool_names: List[str] = []
    try:
        if hasattr(agent, "tools_for_turn"):
            available_tools = agent.tools_for_turn(last_user)
        else:
            available_tools = agent.tool_registry.list_tools(None)
        for t in available_tools:
            name = t.get("name")
            if not name:
                continue
            visible_tool_names.append(str(name))
            tools_payload.append(
                {
                    "type": "function",
                    "name": name,
                    "description": t.get("description") or "",
                    "parameters": t.get("parameters")
                    or {"type": "object", "properties": {}},
                }
            )
    except Exception:
        tools_payload = []
        visible_tool_names = []

    tool_intent_detail = {
        "trace_id": trace_id,
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "user_id": req.user_id,
        "conversation_id": store_conversation_id,
        "agent": req.agent,
        "visible_tool_count": len(visible_tool_names),
        "visible_tools": visible_tool_names,
        "memory_tools_visible": [
            name for name in visible_tool_names if name in _MEMORY_TOOL_NAMES
        ],
        "external_tools_visible": [
            name
            for name in visible_tool_names
            if "." in name and name not in _MEMORY_TOOL_NAMES
        ],
    }
    _obs_store.record_audit(
        AuditEvent(
            ts_s=now_s(),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor=req.user_id,
            action="tool.intent",
            resource=f"agent:{req.agent}",
            ok=True,
            detail=redact(tool_intent_detail),
        )
    )
    log_structured_event(logger, "tool.intent", **tool_intent_detail)

    if tools_payload:
        agent.runtime = DemoRuntime(
            agent_id=base_runtime.agent_id,
            user_id=base_runtime.user_id,
            memory_client=base_runtime.memory_client,
            llm_call_fn=_llm_call_factory(
                azure_client,
                model_name,
                req.temperature,
                tools=tools_payload,
                token_callback=token_callback,
            ),
            conversation_id=base_runtime.conversation_id,
            trace_id=base_runtime.trace_id,
            config=base_runtime.config,
            request_id=base_runtime.request_id,
            trace=base_runtime.trace,
        )
        try:
            agent.execution_loop.llm_call_fn = agent.runtime.llm_call_fn
        except Exception:
            # Best-effort: some agent implementations may not expose an execution loop.
            logger.debug(
                "Failed to inject llm_call_fn into agent execution_loop", exc_info=True
            )

    store.put(
        conversation_id=store_conversation_id,
        user_id=req.user_id,
        messages=merged_messages,
        metadata=persisted_metadata,
    )

    # Wire persisted conversation history (Redis) into the per-request agent.
    #
    # Important: `DemoAgent.run_turn()` will append the current `last_user` as a
    # fresh user message, so we only pass messages *before* the last user turn
    # to avoid duplicating it in the prompt.
    history_before_last_user: List[Dict[str, Any]] = []
    last_user_idx = None
    for i in range(len(merged_messages) - 1, -1, -1):
        if (merged_messages[i] or {}).get("role") == "user":
            last_user_idx = i
            break

    if last_user_idx is None:
        history_before_last_user = list(merged_messages)
    else:
        if last_user_idx != len(merged_messages) - 1:
            logger.debug(
                "chat history has trailing messages after last user; ignoring tail",
                extra={
                    "trace_id": trace_id,
                    "conversation_id": store_conversation_id,
                    "last_user_idx": int(last_user_idx),
                    "merged_len": len(merged_messages),
                },
            )
        history_before_last_user = list(merged_messages[:last_user_idx])

    if max_rounds <= 0:
        history_trimmed = []
    else:
        max_messages = max_rounds * 2
        history_trimmed = (
            history_before_last_user
            if len(history_before_last_user) <= max_messages
            else history_before_last_user[-max_messages:]
        )
        # Keep user/assistant pairing as best-effort.
        if len(history_trimmed) % 2 != 0:
            history_trimmed = history_trimmed[1:]

    try:
        agent.conversation_history = history_trimmed  # type: ignore[attr-defined]
    except Exception:
        logger.debug(
            "failed to inject conversation_history into agent",
            extra={"trace_id": trace_id, "conversation_id": store_conversation_id},
            exc_info=True,
        )

    try:
        answer = agent.run_turn(last_user)
    except Exception as exc:
        _obs_store.record_metric(
            MetricPoint(
                ts_s=now_s(),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                name="chat.errors",
                value=1.0,
                tags={"agent": req.agent},
            )
        )
        _obs_store.record_audit(
            AuditEvent(
                ts_s=now_s(),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                actor=req.user_id,
                action="chat.error",
                resource=f"agent:{req.agent}",
                ok=False,
                detail=redact({"trace_id": trace_id, "error": str(exc)}),
            )
        )
        logger.exception(
            "chat run failed",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "conversation_id": store_conversation_id,
                "user_id": req.user_id,
                "agent": req.agent,
            },
        )
        log_structured_event(
            logger,
            "chat.error",
            level="error",
            request_id=request_id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            user_id=req.user_id,
            conversation_id=store_conversation_id,
            agent=req.agent,
            duration_ms=round((time.monotonic() - chat_started_monotonic_s) * 1000, 3),
            error_type=type(exc).__name__,
        )
        return ChatResponse(
            status="error",
            conversation_id=conversation_id,
            error=str(exc),
        )

    _obs_store.record_metric(
        MetricPoint(
            ts_s=now_s(),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name="chat.success",
            value=1.0,
            tags={"agent": req.agent},
        )
    )
    log_structured_event(
        logger,
        "chat.success",
        request_id=request_id,
        trace_id=trace_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        user_id=req.user_id,
        conversation_id=store_conversation_id,
        agent=req.agent,
        duration_ms=round((time.monotonic() - chat_started_monotonic_s) * 1000, 3),
    )

    merged_messages.append({"role": "assistant", "content": answer})
    _record_success_usage(answer)
    store.put(
        conversation_id=store_conversation_id,
        user_id=req.user_id,
        messages=merged_messages,
        metadata=persisted_metadata,
    )

    try:
        distill_result = _enqueue_success_chat_distill(
            settings=MemoryDistillSettings.from_env(),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            user_id=req.user_id,
            conversation_id=conversation_id,
            merged_messages=merged_messages,
            memory_client=memory_client,
            last_user=last_user,
            answer=answer,
            trace_id=trace_id,
        )
        distill_detail = {
            "trace_id": trace_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "user_id": req.user_id,
            "conversation_id": store_conversation_id,
            "agent": req.agent,
            **(distill_result if isinstance(distill_result, dict) else {}),
        }
        _obs_store.record_audit(
            AuditEvent(
                ts_s=now_s(),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                actor=req.user_id,
                action="distill.enqueue",
                resource="distill",
                ok=True,
                detail=redact(distill_detail),
            )
        )
        log_structured_event(logger, "distill.enqueue", **distill_detail)
    except Exception as exc:
        logger.warning("distill enqueue failed: %s", exc)
        log_structured_event(
            logger,
            "distill.enqueue.error",
            level="warning",
            trace_id=trace_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            user_id=req.user_id,
            conversation_id=store_conversation_id,
            agent=req.agent,
            error_type=type(exc).__name__,
            error=str(exc),
        )

    return ChatResponse(
        status="success",
        conversation_id=conversation_id,
        trace_id=trace_id,
        answer=answer,
        messages=[ChatMessage(**m) for m in merged_messages],
    )


@router.post("/v1/chat/stream")
def chat_stream(
    req: ChatRequest,
    request: Request,
    token: str = Depends(_bearer_token_from_headers),
    workspace_id: str = Depends(_require_workspace_id),
    store=Depends(_get_conversation_store),
) -> StreamingResponse:
    me = _me_from_access_token(token)
    if req.user_id != me.sub:
        req = req.model_copy(update={"user_id": me.sub})

    portal_cfg = _load_portal_config()
    _assert_workspace_access(me, workspace_id, cfg=portal_cfg)

    stream_req = req
    if not stream_req.conversation_id:
        stream_req = req.model_copy(
            update={"conversation_id": f"conv_{uuid.uuid4().hex}"}
        )

    trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex
    request.state.trace_id_override = trace_id
    tenant_id = me.tenant_id
    _raise_if_chat_quota_exceeded(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        user_id=req.user_id,
        agent=req.agent,
        trace_id=trace_id,
        estimated_tokens=estimate_message_tokens(
            [m.model_dump(exclude_none=True) for m in req.messages]
        ),
    )
    events: "queue.Queue[tuple[str, Dict[str, Any] | None]]" = queue.Queue()
    holder: Dict[str, Any] = {}

    def _token_callback(text: str) -> None:
        if text:
            events.put(("token", {"text": str(text)}))

    def _tool_event_callback(event_type: str, detail: Dict[str, Any]) -> None:
        payload = {
            "event": event_type,
            "tool_name": (detail or {}).get("tool_name"),
            "tool_call_id": (detail or {}).get("tool_call_id"),
            "ts_s": now_s(),
        }
        events.put(("tool", payload))

    request.state.agent_token_callback = _token_callback
    request.state.agent_sse_event_callback = _tool_event_callback

    def _run_chat() -> None:
        try:
            holder["resp"] = chat(
                req=stream_req,
                request=request,
                token=token,
                workspace_id=workspace_id,
                store=store,
            )
        except Exception as exc:
            holder["error"] = exc
        finally:
            events.put(("final", None))

    threading.Thread(
        target=_run_chat, name=f"chat-stream:{trace_id[:8]}", daemon=True
    ).start()

    async def gen() -> Iterator[bytes]:
        import asyncio

        streamed_tokens = 0
        meta = {"conversation_id": stream_req.conversation_id, "trace_id": trace_id}
        yield f"event: meta\ndata: {json.dumps(meta, ensure_ascii=False)}\n\n".encode(
            "utf-8"
        )

        while True:
            try:
                event_name, payload = events.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            if event_name == "final":
                break
            if event_name == "token":
                streamed_tokens += 1
            yield f"event: {event_name}\ndata: {json.dumps(payload or {}, ensure_ascii=False)}\n\n".encode(
                "utf-8"
            )

        if holder.get("error") is not None:
            payload = {"detail": "chat failed", "error": str(holder["error"])}
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode(
                "utf-8"
            )
            yield b"event: done\ndata: {}\n\n"
            return

        resp = holder.get("resp")
        if resp is None:
            payload = {"detail": "chat failed", "error": "missing chat response"}
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode(
                "utf-8"
            )
            yield b"event: done\ndata: {}\n\n"
            return

        if getattr(resp, "status", None) != "success":
            payload = {
                "detail": "chat failed",
                "error": resp.error or "unknown error",
            }
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode(
                "utf-8"
            )
            yield b"event: done\ndata: {}\n\n"
            return

        if streamed_tokens == 0:
            text = resp.answer or ""
            chunk_size = 24
            for i in range(0, len(text), chunk_size):
                payload = {"text": text[i : i + chunk_size]}
                yield f"event: token\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode(
                    "utf-8"
                )
                await asyncio.sleep(0.02)

        yield b"event: done\ndata: {}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/v1/runs", response_model=RunListResponse)
def list_runs(
    token: str = Depends(_bearer_token_from_headers),
    page: int = 1,
    limit: int = 50,
    agent: Optional[str] = None,
    status: Optional[str] = None,
) -> RunListResponse:
    me = _me_from_access_token(token)

    events = _obs_store.query_audit(
        tenant_id=me.tenant_id,
        workspace_id="*",
        limit=limit * page,
    )

    runs_by_trace: Dict[str, RunRecordResponse] = {}
    trace_started: Dict[str, float] = {}
    trace_ended: Dict[str, float] = {}

    for event in events:
        if not event.detail:
            continue

        trace_id = event.detail.get("trace_id")
        if not trace_id:
            continue

        event_agent = event.detail.get("agent")
        if agent and agent != "*" and event_agent != agent:
            continue

        if trace_id not in runs_by_trace:
            runs_by_trace[trace_id] = RunRecordResponse(
                id=trace_id[:8],
                trace_id=trace_id,
                agent=event_agent or "unknown",
                status="running",
                created_at=_iso_ts(event.ts_s) or "",
                duration_ms=None,
            )

        run = runs_by_trace[trace_id]
        trace_started[trace_id] = min(
            trace_started.get(trace_id, event.ts_s), event.ts_s
        )
        trace_ended[trace_id] = max(trace_ended.get(trace_id, event.ts_s), event.ts_s)

        if event.action == "chat.error" or event.action.endswith(".error"):
            run.status = "error"
        elif event.action in {"chat.done", "chat.success"} or event.action.endswith(
            ".complete"
        ):
            if run.status != "error":
                run.status = "success"
        elif event.action == "tool.end":
            if run.status != "error":
                run.status = "success"

        if event.detail and event.detail.get("duration_ms"):
            try:
                run.duration_ms = float(event.detail["duration_ms"])
            except Exception:
                pass

    runs = list(runs_by_trace.values())
    if status and status != "*":
        runs = [r for r in runs if r.status == status]

    for run in runs:
        if run.duration_ms is None:
            start_ts = trace_started.get(run.trace_id)
            end_ts = trace_ended.get(run.trace_id)
            if start_ts is not None and end_ts is not None and end_ts >= start_ts:
                run.duration_ms = (end_ts - start_ts) * 1000

    runs.sort(key=lambda x: x.created_at, reverse=True)
    total = len(runs)
    runs = runs[(page - 1) * limit : page * limit]

    return RunListResponse(runs=runs, total=total)


@router.get("/v1/runs/{trace_id}", response_model=RunTraceResponse)
def get_run_trace(
    trace_id: str,
    token: str = Depends(_bearer_token_from_headers),
) -> RunTraceResponse:
    me = _me_from_access_token(token)

    events = _obs_store.query_audit(
        tenant_id=me.tenant_id,
        workspace_id="*",
        limit=1000,
    )

    trace_events = [
        e for e in events if e.detail and e.detail.get("trace_id") == trace_id
    ]

    if not trace_events:
        raise HTTPException(status_code=404, detail=f"Trace {trace_id} not found")

    spans_by_id: Dict[str, TraceSpan] = {}
    span_started: Dict[str, float] = {}

    for event in trace_events:
        span_id = event.detail.get("span_id")
        parent_id = event.detail.get("parent_span_id")
        span_name = event.detail.get("span_name") or event.action

        if not span_id:
            span_id = f"event-{event.ts_s}"

        if span_id not in spans_by_id:
            spans_by_id[span_id] = TraceSpan(
                id=span_id,
                parent_id=parent_id,
                name=span_name,
                start_time=_iso_ts(event.ts_s) or "",
                end_time=None,
                duration_ms=None,
                attributes=event.detail or {},
            )
            span_started[span_id] = event.ts_s
        else:
            span = spans_by_id[span_id]
            if event.action.endswith(".end") or event.action == "tool.end":
                span.end_time = _iso_ts(event.ts_s) or ""
                start_ts = span_started.get(span_id)
                if start_ts is not None:
                    span.duration_ms = (event.ts_s - start_ts) * 1000

    trace_events_sorted = sorted(trace_events, key=lambda x: x.ts_s)
    events_list = [
        TraceEvent(
            id=f"{int(e.ts_s)}-{i}",
            ts_s=e.ts_s,
            name=e.action,
            attributes=redact(e.detail) if e.detail else {},
        )
        for i, e in enumerate(trace_events_sorted)
    ]

    first_event = trace_events_sorted[0]
    metadata = {
        "tenant_id": me.tenant_id,
        "trace_id": trace_id,
        "agent": first_event.detail.get("agent") if first_event.detail else None,
        "workspace_id": first_event.workspace_id,
        "actor": first_event.actor,
        "started_at": first_event.ts_s,
        "events_count": len(trace_events_sorted),
        "spans_count": len(spans_by_id),
    }

    trace = TraceResponse(
        id=trace_id[:8],
        trace_id=trace_id,
        spans=list(spans_by_id.values()),
        events=events_list,
        metadata=metadata,
    )
    return RunTraceResponse(trace=trace)
