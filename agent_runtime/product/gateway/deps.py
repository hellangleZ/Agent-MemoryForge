# -*- coding: utf-8 -*-
"""Gateway dependencies.

Common FastAPI dependencies for authentication, authorization, and context.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from fastapi import Cookie, Depends, Header, HTTPException

from agent_runtime.product.auth_store import SQLiteAuthStore
from agent_runtime.product.auth_tokens import decode_access_token
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Singleton auth store
_auth_store: Optional[SQLiteAuthStore] = None


def get_auth_store() -> SQLiteAuthStore:
    """Get or create the auth store singleton."""
    global _auth_store
    if _auth_store is None:
        _auth_store = SQLiteAuthStore()
    return _auth_store


def get_current_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    portal_access_token: Optional[str] = Cookie(None),
) -> Dict:
    """Extract and validate current user from token.

    Args:
        authorization: Bearer token in Authorization header.
        portal_access_token: Token in cookie.

    Returns:
        User info dict with id, email, role.

    Raises:
        HTTPException: If token is missing or invalid.
    """
    token = None

    # Check Authorization header first
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    # Fall back to cookie
    elif portal_access_token:
        token = portal_access_token

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    auth_store = get_auth_store()
    user = auth_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
    }


def get_tenant_context(
    user: Dict = Depends(get_current_user),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-ID"),
) -> Tuple[str, str, Dict]:
    """Get tenant context from headers or user defaults.

    Args:
        user: Current user from get_current_user.
        x_tenant_id: Tenant ID header.
        x_workspace_id: Workspace ID header.

    Returns:
        Tuple of (tenant_id, workspace_id, user_info).
    """
    # Default tenant to user ID for single-tenant mode
    tenant_id = x_tenant_id or f"tenant_{user['id']}"
    workspace_id = x_workspace_id or "default"

    return tenant_id, workspace_id, user


def require_admin(
    user: Dict = Depends(get_current_user),
) -> Dict:
    """Require admin role.

    Args:
        user: Current user from get_current_user.

    Returns:
        User info dict.

    Raises:
        HTTPException: If user is not admin.
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def optional_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    portal_access_token: Optional[str] = Cookie(None),
) -> Optional[Dict]:
    """Get current user if authenticated, otherwise return None.

    Args:
        authorization: Bearer token in Authorization header.
        portal_access_token: Token in cookie.

    Returns:
        User info dict or None.
    """
    try:
        return get_current_user(authorization, portal_access_token)
    except HTTPException:
        return None
