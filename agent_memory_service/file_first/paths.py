from __future__ import annotations

import os
import re
import hashlib
from pathlib import Path


_SCOPE_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _safe_scope_part(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "unknown"
    safe = _SCOPE_RE.sub("_", text).strip("._-") or "unknown"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    prefix = safe[:80]
    return f"{prefix}--{digest}"


def default_file_root() -> Path:
    root = (os.getenv("AGENT_MEMORY_FILE_ROOT") or "").strip()
    if root:
        return Path(root).expanduser()
    return Path("~/.agent_memory_service/workspaces").expanduser()


def workspace_root(*, tenant_id: str, workspace_id: str) -> Path:
    t = _safe_scope_part(tenant_id)
    ws = _safe_scope_part(workspace_id)
    return default_file_root() / f"t_{t}__ws_{ws}"


def safe_workspace_path(
    *, root: Path, relative_path: str, require_md: bool = True
) -> Path:
    rel = (relative_path or "").strip().lstrip("/").replace("\\", "/")
    if not rel or rel.startswith("../") or "/../" in rel:
        raise ValueError("Invalid path")
    if require_md and not rel.lower().endswith(".md"):
        raise ValueError("Only .md files are allowed")

    candidate = (root / rel).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("Path escapes workspace root") from exc
    return candidate
