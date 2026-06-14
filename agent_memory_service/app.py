from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from agent_memory_service.orchestrator import MemoryOrchestrator

from utils.logging_config import get_logger


logger = get_logger(__name__)


class StatsRequest(BaseModel):
    tenant_id: str
    workspace_id: str


class FileFirstWriteRequest(BaseModel):
    tenant_id: str
    workspace_id: str
    tier: str
    scope: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    target: str | None = None
    conversation_id: str | None = None
    task_id: str | None = None
    actor_user_id: str | None = None
    actor_role: str | None = None


class FileFirstSearchRequest(BaseModel):
    tenant_id: str
    workspace_id: str
    query: str
    top_k: int = 5
    tiers: List[str] | None = None
    scopes: List[str] | None = None
    memory_kinds: List[str] | None = None
    path_prefixes: List[str] | None = None
    actor_user_id: str | None = None
    actor_role: str | None = None


class FileFirstReadRequest(BaseModel):
    tenant_id: str
    workspace_id: str
    tier: str
    conversation_id: str | None = None
    task_id: str | None = None
    user_id: str | None = None
    key: str | None = None
    query: str | None = None
    limit: int | None = None
    top_k: int | None = None
    scopes: List[str] | None = None
    actor_user_id: str | None = None
    actor_role: str | None = None


class FileFirstGetRequest(BaseModel):
    tenant_id: str
    workspace_id: str
    path: str
    start_line: int | None = None
    max_lines: int | None = None
    actor_user_id: str | None = None
    actor_role: str | None = None


class FileFirstRebuildRequest(BaseModel):
    tenant_id: str
    workspace_id: str


def _configured_internal_api_key() -> str:
    return (
        os.getenv("MEMORY_SERVICE_API_KEY")
        or os.getenv("AGENT_MEMORY_SERVICE_API_KEY")
        or ""
    ).strip()


def _is_production() -> bool:
    env = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    return env in {"prod", "production"}


def _require_internal_api_key(
    x_agent_memory_service_key: str | None = Header(default=None),
) -> None:
    expected = _configured_internal_api_key()
    if not expected:
        local_dev_allowed = (
            os.getenv("AGENT_MEMORY_SERVICE_ALLOW_UNAUTHENTICATED_LOCAL_DEV", "")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"}
        )
        if _is_production() or not local_dev_allowed:
            raise HTTPException(
                status_code=500,
                detail="AGENT_MEMORY_SERVICE_API_KEY must be configured",
            )
        return
    supplied = str(x_agent_memory_service_key or "")
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def create_app(
    *, title: str = "Agent-MemoryForge API", version: str = "1.4"
) -> FastAPI:
    """Create the FastAPI application.

    This avoids import-time side effects (connecting Redis/Neo4j/Faiss) and makes
    the service more testable and embeddable.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Avoid heavy initialization work if the request is scope-invalid.
        app.state.orchestrator = None
        logger.info("Memory service started")
        yield
        logger.info("Memory service shutting down")

    fastapi_app = FastAPI(title=title, version=version, lifespan=lifespan)
    # Ensure direct route calls in unit tests can access state without running lifespan.
    fastapi_app.state.orchestrator = None

    def _require_minimal_scope(request: BaseModel) -> None:
        params = getattr(request, "params", {}) or {}
        if not params.get("tenant_id"):
            raise HTTPException(status_code=400, detail="Missing tenant_id")
        if not params.get("workspace_id"):
            raise HTTPException(status_code=400, detail="Missing workspace_id")

    def _raise_internal_error() -> None:
        raise HTTPException(status_code=500, detail="Internal server error")

    @fastapi_app.get("/health")
    def health_check():
        return {"status": "healthy", "message": "Memory service is running"}

    @fastapi_app.post("/v1/memory/stats")
    def memory_stats(request: StatsRequest, _: None = Depends(_require_internal_api_key)):
        try:
            if fastapi_app.state.orchestrator is None:
                fastapi_app.state.orchestrator = MemoryOrchestrator()
            orchestrator: MemoryOrchestrator = fastapi_app.state.orchestrator
            result = orchestrator.stats(
                tenant_id=request.tenant_id, workspace_id=request.workspace_id
            )
            return {"status": "success", "data": result}
        except HTTPException:
            raise
        except Exception:
            logger.exception("API stats failed tenant=%s workspace=%s", request.tenant_id, request.workspace_id)
            _raise_internal_error()

    # ---- File-first native APIs ----

    @fastapi_app.post("/v1/memory/write")
    def file_first_write(
        request: FileFirstWriteRequest,
        _: None = Depends(_require_internal_api_key),
    ):
        try:
            if fastapi_app.state.orchestrator is None:
                fastapi_app.state.orchestrator = MemoryOrchestrator()
            orchestrator: MemoryOrchestrator = fastapi_app.state.orchestrator
            payload = {
                "tier": request.tier,
                "scope": request.scope,
                "content": request.content,
                "metadata": dict(request.metadata or {}),
                "target": request.target,
                "actor_user_id": request.actor_user_id,
                "actor_role": request.actor_role,
            }
            if request.conversation_id:
                payload["conversation_id"] = request.conversation_id
                payload["metadata"]["conversation_id"] = request.conversation_id
            if request.task_id:
                payload["task_id"] = request.task_id
                payload["metadata"]["task_id"] = request.task_id
            result = orchestrator.write_memory(
                tenant_id=request.tenant_id,
                workspace_id=request.workspace_id,
                payload=payload,
            )
            return {"status": "success", "data": result}
        except HTTPException:
            raise
        except Exception:
            logger.exception("API file-first write failed")
            _raise_internal_error()

    @fastapi_app.post("/v1/memory/search")
    def file_first_search(
        request: FileFirstSearchRequest,
        _: None = Depends(_require_internal_api_key),
    ):
        try:
            if fastapi_app.state.orchestrator is None:
                fastapi_app.state.orchestrator = MemoryOrchestrator()
            orchestrator: MemoryOrchestrator = fastapi_app.state.orchestrator
            result = orchestrator.search_memory(
                tenant_id=request.tenant_id,
                workspace_id=request.workspace_id,
                payload={
                    "query": request.query,
                    "top_k": int(request.top_k),
                    "tiers": request.tiers,
                    "scopes": request.scopes,
                    "memory_kinds": request.memory_kinds,
                    "path_prefixes": request.path_prefixes,
                    "actor_user_id": request.actor_user_id,
                    "actor_role": request.actor_role,
                },
            )
            return {"status": "success", "data": result}
        except HTTPException:
            raise
        except Exception:
            logger.exception("API file-first search failed")
            _raise_internal_error()

    @fastapi_app.post("/v1/memory/read")
    def file_first_read(
        request: FileFirstReadRequest,
        _: None = Depends(_require_internal_api_key),
    ):
        try:
            if fastapi_app.state.orchestrator is None:
                fastapi_app.state.orchestrator = MemoryOrchestrator()
            orchestrator: MemoryOrchestrator = fastapi_app.state.orchestrator
            result = orchestrator.read_memory(
                tenant_id=request.tenant_id,
                workspace_id=request.workspace_id,
                payload={
                    "tier": request.tier,
                    "conversation_id": request.conversation_id,
                    "task_id": request.task_id,
                    "user_id": request.user_id,
                    "key": request.key,
                    "query": request.query,
                    "limit": request.limit,
                    "top_k": request.top_k,
                    "scopes": request.scopes,
                    "actor_user_id": request.actor_user_id,
                    "actor_role": request.actor_role,
                },
            )
            return {"status": "success", "data": result}
        except HTTPException:
            raise
        except Exception:
            logger.exception("API file-first read failed")
            _raise_internal_error()

    @fastapi_app.post("/v1/memory/get")
    def file_first_get(
        request: FileFirstGetRequest,
        _: None = Depends(_require_internal_api_key),
    ):
        try:
            if fastapi_app.state.orchestrator is None:
                fastapi_app.state.orchestrator = MemoryOrchestrator()
            orchestrator: MemoryOrchestrator = fastapi_app.state.orchestrator
            result = orchestrator.get_memory(
                tenant_id=request.tenant_id,
                workspace_id=request.workspace_id,
                payload={
                    "path": request.path,
                    "start_line": request.start_line,
                    "max_lines": request.max_lines,
                    "actor_user_id": request.actor_user_id,
                    "actor_role": request.actor_role,
                },
            )
            return {"status": "success", "data": result}
        except HTTPException:
            raise
        except Exception:
            logger.exception("API file-first get failed")
            _raise_internal_error()

    @fastapi_app.post("/v1/memory/index/rebuild")
    def file_first_rebuild(
        request: FileFirstRebuildRequest,
        _: None = Depends(_require_internal_api_key),
    ):
        try:
            if fastapi_app.state.orchestrator is None:
                fastapi_app.state.orchestrator = MemoryOrchestrator()
            orchestrator: MemoryOrchestrator = fastapi_app.state.orchestrator
            result = orchestrator.rebuild_index(
                tenant_id=request.tenant_id, workspace_id=request.workspace_id
            )
            return {"status": "success", "data": result}
        except HTTPException:
            raise
        except Exception:
            logger.exception("API file-first rebuild failed")
            _raise_internal_error()

    @fastapi_app.get("/v1/memory/status")
    def file_first_status(_: None = Depends(_require_internal_api_key)) -> Dict[str, Any]:
        if fastapi_app.state.orchestrator is None:
            fastapi_app.state.orchestrator = MemoryOrchestrator()
        orchestrator: MemoryOrchestrator = fastapi_app.state.orchestrator
        return {"status": "success", "data": orchestrator.status()}

    return fastapi_app
