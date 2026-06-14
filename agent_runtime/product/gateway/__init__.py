# -*- coding: utf-8 -*-
"""Gateway module package.

This package provides modular route handlers for the Agent Gateway API.
"""
from agent_runtime.product.gateway.deps import (
    get_auth_store,
    get_current_user,
    get_tenant_context,
    require_admin,
)
from agent_runtime.product.gateway.models import (
    WorkspaceConfigRequest,
    PortalMeResponse,
    WorkspaceDetailResponse,
    ToolStatusResponse,
    ToolsStatusResponse,
    MonitoringMetricResponse,
    MonitoringMetricsResponse,
    MonitoringAuditEntryResponse,
    MonitoringAuditResponse,
    FileFirstReadProxyRequest,
    PortalAgentUpsertRequest,
    ToolPolicyRequest,
    WorkspaceMemberRequest,
    FullChainStartRequest,
    WorkspaceListResponse,
    RunListResponse,
    RunTraceResponse,
    AdminUserListResponse,
)

__all__ = [
    # Dependencies
    "get_auth_store",
    "get_current_user",
    "get_tenant_context",
    "require_admin",
    # Models
    "WorkspaceConfigRequest",
    "PortalMeResponse",
    "WorkspaceDetailResponse",
    "ToolStatusResponse",
    "ToolsStatusResponse",
    "MonitoringMetricResponse",
    "MonitoringMetricsResponse",
    "MonitoringAuditEntryResponse",
    "MonitoringAuditResponse",
    "FileFirstReadProxyRequest",
    "PortalAgentUpsertRequest",
    "ToolPolicyRequest",
    "WorkspaceMemberRequest",
    "FullChainStartRequest",
    "WorkspaceListResponse",
    "RunListResponse",
    "RunTraceResponse",
    "AdminUserListResponse",
]
