"""Memory service orchestration (backend router).

This module is intentionally import-safe: it does not connect to external
services at import time.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import HTTPException

from agent_memory_service.backends.base import MemoryBackend
from config.agent_config import get_config
from utils.logging_config import get_logger


logger = get_logger(__name__)


def _backend_name() -> str:
    return (os.getenv("AGENT_MEMORY_BACKEND") or "file_first").strip().lower()


def _cfg_dict() -> Dict[str, Any]:
    cfg = get_config()
    # AgentConfig is a dataclass; vars(cfg) is stable enough for our uses.
    return dict(vars(cfg))


class MemoryOrchestrator:
    """Routes calls to the active backend.

    Backends:
    - file_first (default): Markdown truth + SQLite FTS index

    This service runs file-first only. Redis remains optional for queues/caching
    outside the memory backend.
    """

    @staticmethod
    def _parse_ttl_seconds(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("ttl_s must be an integer number of seconds")
        if isinstance(value, (int, float)):
            ttl_s = int(value)
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            ttl_s = int(text)
        else:
            raise ValueError(f"ttl_s must be int/str/None, got {type(value).__name__}")

        if ttl_s <= 0:
            raise ValueError("ttl_s must be a positive integer")
        return ttl_s

    def __init__(self) -> None:
        self._name = _backend_name()
        self._backend: MemoryBackend | None = None
        logger.info("MemoryOrchestrator configured backend=%s", self._name)

    def _get_backend(self) -> MemoryBackend:
        if self._backend is not None:
            return self._backend

        name = self._name
        if name in {"file_first", "file-first", "file"}:
            from agent_memory_service.backends.file_first import FileFirstBackend

            self._backend = FileFirstBackend(service_config=_cfg_dict())
            return self._backend


        raise HTTPException(status_code=422, detail=f"Unsupported AGENT_MEMORY_BACKEND={name!r}")

    def stats(self, *, tenant_id: str, workspace_id: str) -> Dict[str, Any]:
        backend = self._get_backend()
        return backend.stats(tenant_id=tenant_id, workspace_id=workspace_id)

    # ---- Canonical file-first API surface ----

    def write_memory(self, *, tenant_id: str, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._get_backend().write_memory(tenant_id=tenant_id, workspace_id=workspace_id, payload=payload)

    def search_memory(self, *, tenant_id: str, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._get_backend().search_memory(tenant_id=tenant_id, workspace_id=workspace_id, payload=payload)

    def read_memory(self, *, tenant_id: str, workspace_id: str, payload: Dict[str, Any]) -> Any:
        return self._get_backend().read_memory(tenant_id=tenant_id, workspace_id=workspace_id, payload=payload)

    def get_memory(self, *, tenant_id: str, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._get_backend().get_memory(tenant_id=tenant_id, workspace_id=workspace_id, payload=payload)

    def rebuild_index(self, *, tenant_id: str, workspace_id: str) -> Dict[str, Any]:
        return self._get_backend().rebuild_index(tenant_id=tenant_id, workspace_id=workspace_id)

    def status(self) -> Dict[str, Any]:
        return self._get_backend().status()
