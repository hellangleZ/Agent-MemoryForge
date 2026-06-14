# -*- coding: utf-8 -*-
"""Gateway Pydantic models.

Request and response models for the Agent Gateway API.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WorkspaceConfigRequest(BaseModel):
    """Workspace configuration request."""
    system_prompt: Optional[str] = None
    mcp_servers_json: Optional[str] = None
    mcp_stdio_json: Optional[str] = None
    mcp_http_url: Optional[str] = None
    mcp_http_namespace: Optional[str] = None
    mcp_http_headers_json: Optional[str] = None
    mcp: Optional[Dict[str, Any]] = None


class WorkspaceSecretsRequest(BaseModel):
    """Workspace-scoped secret update request."""

    values: Dict[str, str] = Field(default_factory=dict)
    clear: List[str] = Field(default_factory=list)


class AdminQuotaRequest(BaseModel):
    """Admin token quota update request."""

    tenant_id: Optional[str] = None
    workspace_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    monthly_token_quota: int = Field(ge=0)
    enabled: bool = True


class PortalMeResponse(BaseModel):
    """Current user profile response."""
    id: str
    email: str
    role: str
    created_at: Optional[str] = None


class WorkspaceDetailResponse(BaseModel):
    """Workspace detail response."""
    id: str
    name: str
    owner: str
    created_at: str
    status: str
    config: Dict[str, Any] = Field(default_factory=dict)
    agents: List[str] = Field(default_factory=list)


class ToolStatusResponse(BaseModel):
    """Tool status response."""
    name: str
    enabled: bool
    status: str
    config: Dict[str, Any] = Field(default_factory=dict)


class ToolsStatusResponse(BaseModel):
    """Tools status list response."""
    tools: List[ToolStatusResponse]


class MonitoringMetricResponse(BaseModel):
    """Single monitoring metric."""
    timestamp: str
    value: float
    unit: str


class MonitoringMetricsResponse(BaseModel):
    """Monitoring metrics list response."""
    metrics: List[MonitoringMetricResponse]
    total: int = 0

    # Direct handler tests access responses as a dict-like shape:
    # {"status": "...", "data": {"total": ..., "items": [...]}}.
    def __getitem__(self, key: str) -> Any:  # pragma: no cover - exercised indirectly
        if key == "status":
            return "success"
        if key == "data":
            return {
                "total": int(self.total or len(self.metrics)),
                "items": [m.model_dump() for m in self.metrics],
            }
        raise KeyError(key)


class MonitoringAuditEntryResponse(BaseModel):
    """Single audit log entry."""
    id: str
    user_id: str
    action: str
    resource: str
    timestamp: str
    metadata: Optional[Dict[str, Any]] = None


class MonitoringAuditResponse(BaseModel):
    """Audit log list response."""
    audits: List[MonitoringAuditEntryResponse]
    total: int

    def __getitem__(self, key: str) -> Any:  # pragma: no cover - exercised indirectly
        if key == "status":
            return "success"
        if key == "data":
            return {
                "total": int(self.total),
                "items": [a.model_dump() for a in self.audits],
            }
        raise KeyError(key)


class FileFirstWriteProxyRequest(BaseModel):
    """File-first write proxy request.

    Gateway callers are authenticated by bearer token. Tenant, workspace, actor
    user, and actor role are always derived server-side; client-supplied values
    for those fields are intentionally ignored by the route.
    """

    tier: str
    scope: str = "project"
    content: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    target: Optional[str] = None
    conversation_id: Optional[str] = None
    task_id: Optional[str] = None
    user_id: Optional[str] = None
    key: Optional[str] = None
    value: Optional[Any] = None
    subject: Optional[str] = None
    relation: Optional[str] = None
    obj: Optional[str] = None
    state: Optional[Any] = None
    ttl_s: Optional[int] = None
    memory_url: Optional[str] = Field(
        default=None,
        description="Must match the configured Memory Service URL or an exact gateway allowlist entry.",
    )


class FileFirstSearchProxyRequest(BaseModel):
    """File-first search proxy request."""

    query: str
    top_k: int = 20
    tiers: Optional[List[str]] = None
    scopes: Optional[List[str]] = None
    memory_kinds: Optional[List[str]] = None
    path_prefixes: Optional[List[str]] = None
    memory_url: Optional[str] = Field(
        default=None,
        description="Must match the configured Memory Service URL or an exact gateway allowlist entry.",
    )


class FileFirstReadProxyRequest(BaseModel):
    """File-first direct read proxy request."""

    tier: str
    conversation_id: Optional[str] = None
    task_id: Optional[str] = None
    user_id: Optional[str] = None
    key: Optional[str] = None
    query: Optional[str] = None
    limit: Optional[int] = None
    top_k: Optional[int] = None
    scopes: Optional[List[str]] = None
    memory_url: Optional[str] = Field(
        default=None,
        description="Must match the configured Memory Service URL or an exact gateway allowlist entry.",
    )


class FileFirstGetProxyRequest(BaseModel):
    """File-first get proxy request."""

    path: str
    start_line: Optional[int] = None
    max_lines: Optional[int] = None
    memory_url: Optional[str] = Field(
        default=None,
        description="Must match the configured Memory Service URL or an exact gateway allowlist entry.",
    )


class PortalAgentUpsertRequest(BaseModel):
    """Agent create/update request."""
    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    tools: List[str] = Field(default_factory=list)
    workspace_id: Optional[str] = None


class ToolPolicyRequest(BaseModel):
    """Tool policy configuration request."""
    allowlist: List[str] = Field(default_factory=list)
    denylist: List[str] = Field(default_factory=list)
    overrides: Dict[str, bool] = Field(default_factory=dict)


class WorkspaceMemberRequest(BaseModel):
    """Workspace member add request."""
    user_id: str
    role: str = "member"


class FullChainStartRequest(BaseModel):
    """Full-chain service start request."""
    memory_port: int = 8001
    gateway_port: int = 8080
    memory_url: str = "http://127.0.0.1:8001"
    verbose: bool = False
    start_distill_worker: bool = False
    restart: bool = False
    require_dependencies_healthy: bool = True


class WorkspaceListItem(BaseModel):
    """Single workspace list item."""
    id: str
    name: str
    owner: str
    created_at: str
    status: str
    member_count: int


class WorkspaceListResponse(BaseModel):
    """Workspace list response."""
    workspaces: List[WorkspaceListItem]
    total: int


class RunListItem(BaseModel):
    """Single run list item."""
    trace_id: str
    agent_id: str
    status: str
    started_at: str
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None


class RunListResponse(BaseModel):
    """Run list response."""
    runs: List[RunListItem]
    total: int


class RunTraceSpan(BaseModel):
    """Single trace span."""
    name: str
    started_at_s: float
    ended_at_s: float
    ok: bool
    attributes: Dict[str, Any] = Field(default_factory=dict)


class RunTraceResponse(BaseModel):
    """Run trace detail response."""
    trace_id: str
    agent_id: str
    status: str
    started_at: str
    finished_at: Optional[str] = None
    spans: List[RunTraceSpan] = Field(default_factory=list)
    artifacts: Dict[str, Any] = Field(default_factory=dict)


class AdminUserItem(BaseModel):
    """Single admin user item."""
    id: str
    email: str
    role: str
    created_at: str
    last_login: Optional[str] = None


class AdminUserListResponse(BaseModel):
    """Admin user list response."""
    users: List[AdminUserItem]
    total: int
