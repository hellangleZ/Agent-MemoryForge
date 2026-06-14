from __future__ import annotations

from typing import Any, Dict, Protocol


class MemoryBackend(Protocol):
    """Backend interface for the memory service.

    Backends MUST enforce tenant/workspace scoping.
    """

    def stats(self, *, tenant_id: str, workspace_id: str) -> Dict[str, Any]: ...

    # Canonical file-first APIs
    def write_memory(self, *, tenant_id: str, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]: ...

    def search_memory(self, *, tenant_id: str, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]: ...

    def read_memory(self, *, tenant_id: str, workspace_id: str, payload: Dict[str, Any]) -> Any: ...

    def get_memory(self, *, tenant_id: str, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]: ...

    def rebuild_index(self, *, tenant_id: str, workspace_id: str) -> Dict[str, Any]: ...

    def status(self) -> Dict[str, Any]: ...

