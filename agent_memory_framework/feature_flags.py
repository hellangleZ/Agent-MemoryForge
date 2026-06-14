from __future__ import annotations

import os


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def enable_parallel(default: bool = True) -> bool:
    return _env_flag("AGENT_MEMORY_ENABLE_PARALLEL", default)


def enable_scoping(default: bool = True) -> bool:
    return _env_flag("AGENT_MEMORY_ENABLE_SCOPING", default)


def parallel_workers(default: int | None = None) -> int | None:
    value = os.getenv("AGENT_MEMORY_PARALLEL_WORKERS")
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value.strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default
