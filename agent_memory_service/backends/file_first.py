from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from agent_memory_service.derived.graph_neo4j import GraphEdge, best_effort_upsert
from agent_memory_service.file_first.entries import (
    first_json_code_block,
    format_entry,
    iter_entries,
    split_chunks_with_line_numbers,
)
from agent_memory_service.file_first.index_sqlite import SqliteFtsIndex
from agent_memory_service.file_first.index_pgvector import PgVectorIndex
from agent_memory_service.file_first.paths import safe_workspace_path, workspace_root
from utils.logging_config import get_logger


logger = get_logger(__name__)
_VECTOR_EXECUTOR: ThreadPoolExecutor | None = None
_VECTOR_EXECUTOR_LOCK = threading.Lock()


def _utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _count_lines(path: Path) -> int:
    try:
        data = path.read_bytes()
        return int(data.count(b"\n")) + 1 if data else 1
    except FileNotFoundError:
        return 1


def _normalize_pref_key(key: str) -> str:
    """Normalize preference keys to reduce duplicate/variant keys.
    Lowercase, snake_case, strip non [a-z0-9_], and drop trailing
    *_preference / *_pref / *_setting suffixes. No hard enum / synonym map."""
    s = (key or "").strip().lower()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    for suf in (
        "_preferences",
        "_preference",
        "_prefs",
        "_pref",
        "_settings",
        "_setting",
    ):
        if s.endswith(suf) and len(s) > len(suf):
            s = s[: -len(suf)]
            break
    return s


def _safe_pref_path_part(value: str, *, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return (text[:96] if text else fallback) or fallback


_CANONICAL_TIERS = {"stm", "wm", "preferences", "semantic", "graph"}
_DEFAULT_MEMORY_KIND = {
    "stm": "stm_summary",
    "wm": "working_state",
    "preferences": "preference",
    "semantic": "semantic_fact",
    "graph": "kg_relation",
}
_TIER_TARGET = {
    "stm": "stm",
    "wm": "wm",
    "preferences": "preferences",
    "semantic": "daily",
    "graph": "graph",
}
_PRIVATE_TIERS = {"stm", "wm", "preferences"}
_PRIVILEGED_ACTOR_ROLES = {"admin", "system", "service"}


def _actor_user_id(payload: Dict[str, Any]) -> str:
    return str(payload.get("actor_user_id") or "").strip()


def _actor_role(payload: Dict[str, Any]) -> str:
    return str(payload.get("actor_role") or "system").strip().lower() or "system"


def _actor_can_read_private(payload: Dict[str, Any], owner_user_id: str) -> bool:
    role = _actor_role(payload)
    if role in _PRIVILEGED_ACTOR_ROLES:
        return True
    actor = _actor_user_id(payload)
    owner = str(owner_user_id or "").strip()
    return bool(actor and owner and actor == owner)


def _owner_from_hit_path(path: str, *, tier: str) -> str:
    rel = str(path or "").replace("\\", "/").lstrip("/")
    parts = [p for p in rel.split("/") if p]
    if tier == "preferences" and len(parts) >= 2 and parts[0] == "preferences":
        return parts[1]
    return ""


def _hit_is_visible_to_actor(hit: Any, payload: Dict[str, Any]) -> bool:
    tier = str(getattr(hit, "tier", "") or "").strip().lower()
    if tier not in _PRIVATE_TIERS:
        return True
    role = _actor_role(payload)
    if role in _PRIVILEGED_ACTOR_ROLES:
        return True

    actor = _actor_user_id(payload)
    if not actor:
        return False
    metadata = getattr(hit, "metadata", None) or {}
    owner = str(metadata.get("user_id") or "").strip()
    if owner:
        return owner == actor
    return _owner_from_hit_path(
        str(getattr(hit, "path", "") or ""), tier=tier
    ) == _safe_pref_path_part(actor, fallback="_global")


def _entries_visible_to_actor(text: str, payload: Dict[str, Any]) -> bool:
    role = _actor_role(payload)
    if role in _PRIVILEGED_ACTOR_ROLES:
        return True
    actor = _actor_user_id(payload)
    if not actor:
        return False
    saw_owner = False
    for entry in iter_entries(text):
        owner = str((entry.metadata or {}).get("user_id") or "").strip()
        if not owner:
            continue
        saw_owner = True
        if owner != actor:
            return False
    return saw_owner


def _clean_filter_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if not isinstance(value, list):
        raise HTTPException(status_code=422, detail="filter fields must be lists")
    out = [str(x).strip() for x in value if str(x).strip()]
    return out or None


def _clean_path_prefixes(value: Any) -> Optional[List[str]]:
    prefixes = _clean_filter_list(value)
    if not prefixes:
        return None
    out: List[str] = []
    for prefix in prefixes:
        normalized = prefix.replace("\\", "/").lstrip("/")
        if ".." in normalized.split("/"):
            raise HTTPException(
                status_code=422, detail="path_prefixes must stay inside the workspace"
            )
        if normalized and not normalized.endswith("/"):
            normalized += "/"
        out.append(normalized)
    return out or None


def _positive_int_or_none(value: Any, *, field_name: str) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        out = int(value)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"{field_name} must be a positive integer"
        ) from exc
    if out <= 0:
        raise HTTPException(
            status_code=422, detail=f"{field_name} must be a positive integer"
        )
    return out


def _memory_kind_for(tier: str, metadata: Dict[str, Any]) -> str:
    kind = str(metadata.get("memory_kind") or "").strip().lower()
    return kind or _DEFAULT_MEMORY_KIND.get(tier, tier)


def _vector_executor() -> ThreadPoolExecutor:
    global _VECTOR_EXECUTOR
    with _VECTOR_EXECUTOR_LOCK:
        if _VECTOR_EXECUTOR is None:
            try:
                max_workers = int(os.getenv("AGENT_MEMORY_VECTOR_INDEX_WORKERS") or "2")
            except Exception:
                max_workers = 2
            _VECTOR_EXECUTOR = ThreadPoolExecutor(
                max_workers=max(1, min(16, max_workers)),
                thread_name_prefix="am-vector-index",
            )
        return _VECTOR_EXECUTOR


def _append_text(path: Path, text: str) -> int:
    """Append text and return the start line number (1-based) where this text begins."""
    _ensure_dir(path)
    payload = text if text.endswith("\n") else (text + "\n")
    with open(path, "a", encoding="utf-8") as f:
        start_line = _count_lines(path)
        f.write(payload)
    return start_line


@contextmanager
def _file_lock(path: Path):
    _ensure_dir(path)
    lock_path = path.with_name(path.name + ".lock")
    with open(lock_path, "a", encoding="utf-8") as lock_file:
        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_text_atomic(path: Path, text: str) -> None:
    _ensure_dir(path)
    tmp = path.with_suffix(path.suffix + f".tmp.{uuid.uuid4().hex[:8]}")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


_GENERIC_SEARCH_TERMS = {
    "answer",
    "memory",
    "memories",
    "metadata",
    "path",
    "score",
    "source",
    "what",
    "when",
    "where",
    "which",
    "the",
    "and",
    "for",
    "from",
    "about",
    "不要",
    "那个",
    "这个",
    "什么",
    "长期记忆",
    "记忆",
}
_SEARCH_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{2,}")


def _query_digest(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _search_query_candidates(query: str, *, max_candidates: int = 8) -> List[str]:
    original = str(query or "").strip()
    candidates: List[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        value = str(candidate or "").strip()
        if value and value not in seen:
            seen.add(value)
            candidates.append(value)

    add(original)
    raw_tokens: List[str] = []
    for token in _SEARCH_TOKEN_RE.findall(original):
        normalized = token.strip(".-_")
        if not normalized or normalized.lower() in _GENERIC_SEARCH_TERMS:
            continue
        if normalized not in raw_tokens:
            raw_tokens.append(normalized)

    tokens = sorted(
        raw_tokens,
        key=lambda token: (
            0 if ("_" in token or "." in token) else 1,
            raw_tokens.index(token),
        ),
    )
    for token in tokens:
        add(token)
        if "_" in token or "." in token:
            add(re.sub(r"[_.]+", " ", token))
        if len(candidates) >= max_candidates:
            return candidates[:max_candidates]

    for i in range(len(tokens) - 1):
        add(f"{tokens[i]} {tokens[i + 1]}")
        if len(candidates) >= max_candidates:
            break
    return candidates[:max_candidates]


def _search_index_with_fallback(
    index: SqliteFtsIndex,
    *,
    query: str,
    top_k: int,
    tiers: Optional[List[str]],
    scopes: Optional[List[str]],
    memory_kinds: Optional[List[str]],
    path_prefixes: Optional[List[str]],
) -> tuple[List[Any], Dict[str, Any]]:
    hits: List[Any] = []
    seen: set[tuple[str, int, str]] = set()
    candidate_summaries: List[Dict[str, Any]] = []
    first_hit_candidate_index: Optional[int] = None

    candidates = _search_query_candidates(query)
    for idx, candidate in enumerate(candidates):
        batch = index.search(
            query=candidate,
            top_k=top_k,
            tiers=tiers,
            scopes=scopes,
            memory_kinds=memory_kinds,
            path_prefixes=path_prefixes,
        )
        candidate_summaries.append(
            {
                "query_len": len(candidate),
                "query_sha256": _query_digest(candidate),
                "hit_count": len(batch),
            }
        )
        if batch and first_hit_candidate_index is None:
            first_hit_candidate_index = idx
        for hit in batch:
            key = (str(hit.path), int(hit.line or 0), str(hit.entry_id or ""))
            if key in seen:
                continue
            seen.add(key)
            hits.append(hit)
        if len(hits) >= int(top_k):
            break

    return hits[: int(top_k)], {
        "candidate_count": len(candidate_summaries),
        "candidate_summaries": candidate_summaries,
        "fallback_used": first_hit_candidate_index not in (None, 0),
        "first_hit_candidate_index": first_hit_candidate_index,
    }


def _log_memory_search_event(
    *,
    tenant_id: str,
    workspace_id: str,
    query: str,
    top_k: int,
    tiers: Optional[List[str]],
    scopes: Optional[List[str]],
    memory_kinds: Optional[List[str]],
    path_prefixes: Optional[List[str]],
    payload: Dict[str, Any],
    fts_meta: Dict[str, Any],
    fts_hit_count: int,
    vector_hit_count: int,
    result_hit_count: int,
    duration_ms: float,
) -> None:
    detail = {
        "event": "memory.search",
        "ts_s": time.time(),
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "query_len": len(str(query or "")),
        "query_sha256": _query_digest(str(query or "")),
        "top_k": int(top_k),
        "tiers": tiers or [],
        "scopes": scopes or [],
        "memory_kinds": memory_kinds or [],
        "path_prefix_count": len(path_prefixes or []),
        "actor_role": _actor_role(payload),
        "actor_present": bool(_actor_user_id(payload)),
        "fts_hit_count": int(fts_hit_count),
        "vector_hit_count": int(vector_hit_count),
        "result_hit_count": int(result_hit_count),
        "duration_ms": float(duration_ms),
        **fts_meta,
    }
    logger.info(
        "agent_memory.event %s",
        json.dumps(detail, ensure_ascii=False, sort_keys=True, default=str),
    )


def _rrf_merge(fts_hits, vec_hits, top_k, k: int = 60):
    """Reciprocal-rank-fusion of FTS and vector hit lists."""
    scores: Dict[Any, float] = {}
    rep: Dict[Any, Any] = {}
    for rank, h in enumerate(fts_hits or []):
        key = (h.path, h.line, h.entry_id)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        rep[key] = h
    for rank, h in enumerate(vec_hits or []):
        key = (h.path, h.line, h.entry_id)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        rep.setdefault(key, h)
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    out = []
    for key, sc in ordered[: int(top_k)]:
        out.append(replace(rep[key], score=float(sc)))
    return out


@dataclass(frozen=True)
class FileFirstWriteResult:
    entry_id: str
    path: str
    created_at: str
    line_start: int


class FileFirstBackend:
    def __init__(self, *, service_config: Dict[str, Any]) -> None:
        self._service_config = dict(service_config or {})
        # Best-effort auto index rebuild guards (per-process).
        # These are mutated on request paths, so guard them for multi-threaded servers.
        self._auto_guard = threading.Lock()
        self._auto_rebuild_lock: dict[str, threading.Lock] = {}
        self._auto_rebuild_inflight: set[str] = set()
        self._auto_rebuild_last_attempt_s: dict[str, float] = {}
        self._auto_stale_check_last_s: dict[str, float] = {}

    @staticmethod
    def _coerce_wm_state_to_json_object(state: Any) -> Dict[str, Any]:
        if isinstance(state, dict):
            return state
        if isinstance(state, str):
            text = state.strip()
            if not text:
                return {}
            try:
                loaded = json.loads(text)
            except Exception:
                return {"raw": state}
            if isinstance(loaded, dict):
                return loaded
            return {"value": loaded}
        return {"value": state}

    def _require_scope(self, *, tenant_id: str, workspace_id: str) -> None:
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id")
        if not workspace_id:
            raise HTTPException(status_code=400, detail="Missing workspace_id")

    def _ws_root(self, *, tenant_id: str, workspace_id: str) -> Path:
        root = workspace_root(tenant_id=tenant_id, workspace_id=workspace_id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _index(self, *, ws_root: Path) -> SqliteFtsIndex:
        return SqliteFtsIndex(index_path=ws_root / ".index" / "index.sqlite")

    def _pgvector_index(
        self, *, tenant_id: str, workspace_id: str
    ) -> Optional[PgVectorIndex]:
        try:
            return PgVectorIndex.from_env(
                tenant_id=tenant_id, workspace_id=workspace_id
            )
        except Exception:
            logger.exception("pgvector index init failed; vector layer unavailable")
            return None

    @staticmethod
    def _env_flag(name: str) -> bool:
        return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}

    def _auto_rebuild_enabled_on_failure(self) -> bool:
        return self._env_flag("AGENT_MEMORY_INDEX_AUTO_REBUILD") or self._env_flag(
            "AGENT_MEMORY_INDEX_AUTO_REBUILD_ON_FAILURE"
        )

    def _auto_rebuild_enabled_on_stale(self) -> bool:
        return self._env_flag("AGENT_MEMORY_INDEX_AUTO_REBUILD") or self._env_flag(
            "AGENT_MEMORY_INDEX_AUTO_REBUILD_ON_STALE"
        )

    def _auto_rebuild_failure_backoff_s(self) -> float:
        try:
            return float(
                os.getenv("AGENT_MEMORY_INDEX_AUTO_REBUILD_FAILURE_BACKOFF_S") or "60"
            )
        except Exception:
            return 60.0

    def _auto_rebuild_stale_cooldown_s(self) -> float:
        try:
            return float(
                os.getenv("AGENT_MEMORY_INDEX_AUTO_REBUILD_STALE_COOLDOWN_S") or "600"
            )
        except Exception:
            return 600.0

    def _auto_rebuild_stale_check_interval_s(self) -> float:
        try:
            return float(
                os.getenv("AGENT_MEMORY_INDEX_AUTO_REBUILD_STALE_CHECK_INTERVAL_S")
                or "30"
            )
        except Exception:
            return 30.0

    def _auto_rebuild_stale_scan_max_files(self) -> int:
        try:
            return int(os.getenv("AGENT_MEMORY_INDEX_STALE_SCAN_MAX_FILES") or "2000")
        except Exception:
            return 2000

    @staticmethod
    def _is_rebuildable_index_error(exc: Exception) -> bool:
        msg = str(exc or "").lower()
        return (
            "rebuild the index" in msg or "not initialized" in msg or "corrupted" in msg
        )

    def _ws_key(self, *, tenant_id: str, workspace_id: str) -> str:
        return f"{tenant_id}::{workspace_id}"

    def _lock_for(self, key: str) -> threading.Lock:
        with self._auto_guard:
            lock = self._auto_rebuild_lock.get(key)
            if lock is None:
                lock = threading.Lock()
                self._auto_rebuild_lock[key] = lock
            return lock

    def _compute_index_stale(self, *, ws_root: Path) -> bool:
        index_path = ws_root / ".index" / "index.sqlite"
        try:
            idx_mtime_s = (
                float(index_path.stat().st_mtime) if index_path.exists() else None
            )
        except FileNotFoundError:
            idx_mtime_s = None

        if idx_mtime_s is None:
            return True

        cutoff = idx_mtime_s + 1.0
        scanned = 0
        max_files = max(1, self._auto_rebuild_stale_scan_max_files())
        for p in ws_root.rglob("*.md"):
            if not p.is_file():
                continue
            if ".index" in str(p):
                continue
            scanned += 1
            if scanned > max_files:
                logger.info(
                    "Skipping stale index full scan because workspace exceeds max files",
                    extra={"workspace": str(ws_root), "max_files": max_files},
                )
                return False
            try:
                if float(p.stat().st_mtime) > cutoff:
                    return True
            except FileNotFoundError:
                continue
        return False

    def _rebuild_index_from_workspace(self, *, ws_root: Path) -> int:
        """Internal rebuild that does NOT depend on the public rebuild endpoint gate."""

        index_path = ws_root / ".index" / "index.sqlite"
        index: SqliteFtsIndex | None = None
        try:
            try:
                index = self._index(ws_root=ws_root)
            except RuntimeError as exc:
                if self._is_rebuildable_index_error(exc):
                    try:
                        if index_path.exists():
                            index_path.unlink()
                    except Exception as unlink_exc:
                        logger.warning(
                            "Failed to delete corrupted index; will retry create anyway",
                            extra={
                                "index_path": str(index_path),
                                "error": str(unlink_exc),
                            },
                        )
                    index = self._index(ws_root=ws_root)
                else:
                    raise

            index.conn.execute("DELETE FROM docs")
            index.conn.commit()

            md_files = [
                p
                for p in ws_root.rglob("*.md")
                if p.is_file() and ".index" not in str(p)
            ]
            count = 0
            for p in sorted(md_files):
                rel = str(p.relative_to(ws_root)).replace("\\", "/")
                text = p.read_text(encoding="utf-8", errors="replace")
                rows: List[Dict[str, Any]] = []
                for entry in iter_entries(text):
                    meta = dict(entry.metadata or {})
                    tier = str(meta.get("tier") or "")
                    scope = str(meta.get("scope") or "")
                    created_at = str(meta.get("created_at") or "")
                    entry_id = str(meta.get("id") or "") or None
                    pref_key = (
                        str(meta.get("key") or "").strip()
                        if tier == "preferences"
                        else None
                    )
                    memory_kind = str(meta.get("memory_kind") or "").strip() or None
                    chunk_text = entry.content or ""
                    if not chunk_text:
                        continue
                    rows.append(
                        {
                            "path": rel,
                            "entry_id": entry_id,
                            "tier": tier or None,
                            "scope": scope or None,
                            "memory_kind": memory_kind,
                            "created_at": created_at or None,
                            "line_start": int(entry.start_line),
                            "content": chunk_text,
                            "metadata": meta,
                            "pref_key": pref_key or None,
                        }
                    )
                    count += 1
                index.insert_chunks(rows)
            return int(count)
        finally:
            if index is not None:
                index.close()

    def _maybe_rebuild_index_sync(self, *, key: str, ws_root: Path) -> bool:
        now = time.time()
        backoff_s = self._auto_rebuild_failure_backoff_s()
        with self._auto_guard:
            last = float(self._auto_rebuild_last_attempt_s.get(key) or 0.0)
        if last and now - last < backoff_s:
            return False

        lock = self._lock_for(key)
        with lock:
            now = time.time()
            with self._auto_guard:
                last = float(self._auto_rebuild_last_attempt_s.get(key) or 0.0)
            if last and now - last < backoff_s:
                return False
            with self._auto_guard:
                self._auto_rebuild_last_attempt_s[key] = now
            try:
                self._rebuild_index_from_workspace(ws_root=ws_root)
                return True
            except Exception:
                logger.exception(
                    "auto index rebuild failed", extra={"workspace": str(ws_root)}
                )
                return False

    def _maybe_rebuild_index_async_if_stale(self, *, key: str, ws_root: Path) -> None:
        if not self._auto_rebuild_enabled_on_stale():
            return

        now = time.time()
        interval_s = self._auto_rebuild_stale_check_interval_s()
        with self._auto_guard:
            last_check = float(self._auto_stale_check_last_s.get(key) or 0.0)
        if last_check and now - last_check < interval_s:
            return
        with self._auto_guard:
            self._auto_stale_check_last_s[key] = now

        try:
            stale = self._compute_index_stale(ws_root=ws_root)
        except Exception:
            logger.exception(
                "staleness check failed; skipping auto rebuild",
                extra={"workspace": str(ws_root)},
            )
            return
        if not stale:
            return

        cooldown_s = self._auto_rebuild_stale_cooldown_s()
        with self._auto_guard:
            last_attempt = float(self._auto_rebuild_last_attempt_s.get(key) or 0.0)
        if last_attempt and now - last_attempt < cooldown_s:
            return
        with self._auto_guard:
            if key in self._auto_rebuild_inflight:
                return
            self._auto_rebuild_inflight.add(key)

        def _run() -> None:
            try:
                lock = self._lock_for(key)
                with lock:
                    now2 = time.time()
                    with self._auto_guard:
                        last2 = float(self._auto_rebuild_last_attempt_s.get(key) or 0.0)
                    if last2 and now2 - last2 < cooldown_s:
                        return
                    with self._auto_guard:
                        self._auto_rebuild_last_attempt_s[key] = now2
                    self._rebuild_index_from_workspace(ws_root=ws_root)
            except Exception:
                logger.exception(
                    "auto index rebuild (stale) failed",
                    extra={"workspace": str(ws_root)},
                )
            finally:
                with self._auto_guard:
                    self._auto_rebuild_inflight.discard(key)

        threading.Thread(
            target=_run, name=f"am-index-rebuild:{key}", daemon=True
        ).start()

    def _write_entry(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        rel_path: str,
        tier: str,
        scope: str,
        content_md: str,
        metadata: Dict[str, Any],
        overwrite: bool = False,
        pref_key: Optional[str] = None,
    ) -> FileFirstWriteResult:
        ws = self._ws_root(tenant_id=tenant_id, workspace_id=workspace_id)
        try:
            file_path = safe_workspace_path(
                root=ws, relative_path=rel_path, require_md=True
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        entry_id = metadata.get("id") or uuid.uuid4().hex
        created_at = (
            metadata.get("created_at")
            or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        )

        full_meta = {
            **(metadata or {}),
            "id": entry_id,
            "created_at": created_at,
            "tier": tier,
            "scope": scope,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
        }

        entry_text = format_entry(metadata=full_meta, content_md=content_md)
        with self._lock_for("wsfile:" + str(file_path)):
            with _file_lock(file_path):
                if overwrite:
                    _write_text_atomic(file_path, entry_text)
                    line_start = 1
                else:
                    line_start = _append_text(file_path, entry_text)

        result = FileFirstWriteResult(
            entry_id=str(entry_id),
            path=rel_path,
            created_at=str(created_at),
            line_start=int(line_start),
        )

        # Update derived index (best-effort; Markdown is still the source of truth).
        try:
            index = self._index(ws_root=ws)
        except Exception:
            logger.exception(
                "index init failed; write succeeded but was not indexed path=%s",
                rel_path,
            )
            return result

        try:
            try:
                if overwrite:
                    index.delete_by_path(path=rel_path)
                    if self._vector_enabled():
                        index.delete_vectors_by_path(path=rel_path)

                chunks = split_chunks_with_line_numbers(entry_text, min_chars=200)
                index.insert_chunks(
                    [
                        {
                            "path": rel_path,
                            "entry_id": entry_id,
                            "tier": tier,
                            "scope": scope,
                            "memory_kind": full_meta.get("memory_kind"),
                            "created_at": created_at,
                            "line_start": int(line_start + offset_line - 1),
                            "content": chunk,
                            "metadata": full_meta,
                            "pref_key": pref_key,
                        }
                        for offset_line, chunk in chunks
                    ]
                )
                if self._vector_enabled():
                    if self._vector_async_enabled():
                        self._schedule_vector_entry(
                            tenant_id=tenant_id,
                            workspace_id=workspace_id,
                            ws_root=ws,
                            rel_path=rel_path,
                            entry_id=entry_id,
                            tier=tier,
                            scope=scope,
                            created_at=created_at,
                            line_start=int(line_start),
                            content_md=content_md,
                            metadata=full_meta,
                        )
                    else:
                        self._insert_vector_entry(
                            tenant_id=tenant_id,
                            workspace_id=workspace_id,
                            ws_root=ws,
                            rel_path=rel_path,
                            entry_id=entry_id,
                            tier=tier,
                            scope=scope,
                            created_at=created_at,
                            line_start=int(line_start),
                            content_md=content_md,
                            metadata=full_meta,
                            sqlite_index=index,
                        )
            except Exception:
                logger.exception(
                    "index update failed; write succeeded but was not indexed path=%s",
                    rel_path,
                )
        finally:
            index.close()

        return result

    # ---- Native file-first APIs ----

    def _upsert_ltm_preference(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        user_id: str,
        key: str,
        value: Any,
        scope: str = "user",
    ) -> FileFirstWriteResult:
        """Store a preference with UPSERT semantics in a per-user/key file."""
        self._require_scope(tenant_id=tenant_id, workspace_id=workspace_id)
        safe_user = _safe_pref_path_part(user_id, fallback="_global")
        safe_key = _safe_pref_path_part(key, fallback="preference")
        rel_path = f"preferences/{safe_user}/{safe_key}.md"
        metadata = {
            "id": uuid.uuid4().hex,
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "key": key,
            "value": value,
            "user_id": user_id,
            "memory_kind": "preference",
        }
        return self._write_entry(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            rel_path=rel_path,
            tier="preferences",
            scope=scope,
            content_md=f"- {key}: {value}",
            metadata=metadata,
            overwrite=True,
            pref_key=key,
        )

    def _preference_file_value(self, *, ws: Path, user_id: str, key: str) -> Any:
        safe_user = _safe_pref_path_part(user_id, fallback="_global")
        safe_key = _safe_pref_path_part(key, fallback="preference")
        rel_path = f"preferences/{safe_user}/{safe_key}.md"
        try:
            abs_path = safe_workspace_path(
                root=ws, relative_path=rel_path, require_md=True
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            text = abs_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        best: Any = None
        for entry in iter_entries(text):
            meta = entry.metadata or {}
            if (
                str(meta.get("tier") or "") == "preferences"
                and str(meta.get("key") or "") == key
            ):
                best = meta.get("value")
        return best

    def _vector_enabled(self) -> bool:
        return str(os.getenv("AGENT_MEMORY_VECTOR_ENABLED", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def _vector_async_enabled(self) -> bool:
        return str(
            os.getenv("AGENT_MEMORY_VECTOR_ASYNC_INDEX", "1")
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def _vector_backend(self) -> str:
        backend = str(os.getenv("AGENT_MEMORY_VECTOR_BACKEND") or "").strip().lower()
        if backend in {"pgvector", "postgres", "postgresql"}:
            return "pgvector"
        if os.getenv("AGENT_MEMORY_PGVECTOR_DSN") or os.getenv(
            "AGENT_MEMORY_POSTGRES_DSN"
        ):
            return "pgvector"
        return "sqlite"

    def _get_embedder(self):
        cached = getattr(self, "_embedder_cached", "unset")
        if cached == "unset":
            try:
                from config.agent_config import AgentConfig
                from agent_memory_lib.embedding_client import (
                    embedding_client_from_env_like_config,
                )

                self._embedder_cached = embedding_client_from_env_like_config(
                    AgentConfig.from_env()
                )
            except Exception:
                logger.exception(
                    "vector embedder init failed; vector layer disabled for this process"
                )
                self._embedder_cached = None
        return self._embedder_cached

    def _embed_text(self, text: str):
        if not text:
            return None
        ec = self._get_embedder()
        if ec is None:
            return None
        try:
            return ec.embed_one(str(text)[:8000])
        except Exception:
            logger.exception("embed_one failed; skipping vector for this write/query")
            return None

    def _insert_vector_entry(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        ws_root: Path,
        rel_path: str,
        entry_id: str,
        tier: str,
        scope: str,
        created_at: str,
        line_start: int,
        content_md: str,
        metadata: Dict[str, Any],
        sqlite_index: Optional[SqliteFtsIndex] = None,
    ) -> None:
        embedding = self._embed_text(content_md)
        if embedding is None:
            return

        if self._vector_backend() == "pgvector":
            pg_index = self._pgvector_index(
                tenant_id=tenant_id, workspace_id=workspace_id
            )
            if pg_index is None:
                return
            try:
                pg_index.insert_vector(
                    path=rel_path,
                    entry_id=entry_id,
                    tier=tier,
                    scope=scope,
                    created_at=created_at,
                    line_start=int(line_start),
                    content=str(content_md)[:2000],
                    metadata=metadata,
                    embedding=embedding,
                    memory_kind=str(metadata.get("memory_kind") or "") or None,
                )
                return
            finally:
                pg_index.close()

        opened_index = sqlite_index is None
        index = sqlite_index or self._index(ws_root=ws_root)
        try:
            index.insert_vector(
                path=rel_path,
                entry_id=entry_id,
                tier=tier,
                scope=scope,
                created_at=created_at,
                line_start=int(line_start),
                content=str(content_md)[:2000],
                metadata=metadata,
                embedding=embedding,
                memory_kind=str(metadata.get("memory_kind") or "") or None,
            )
        finally:
            if opened_index:
                index.close()

    def _schedule_vector_entry(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        ws_root: Path,
        rel_path: str,
        entry_id: str,
        tier: str,
        scope: str,
        created_at: str,
        line_start: int,
        content_md: str,
        metadata: Dict[str, Any],
    ) -> None:
        def _run() -> None:
            try:
                self._insert_vector_entry(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    ws_root=ws_root,
                    rel_path=rel_path,
                    entry_id=entry_id,
                    tier=tier,
                    scope=scope,
                    created_at=created_at,
                    line_start=line_start,
                    content_md=content_md,
                    metadata=metadata,
                )
            except Exception:
                logger.exception(
                    "async vector index update failed; markdown/FTS write succeeded"
                )

        _vector_executor().submit(_run)

    def write_memory(
        self, *, tenant_id: str, workspace_id: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        self._require_scope(tenant_id=tenant_id, workspace_id=workspace_id)
        tier = str(payload.get("tier") or "semantic").strip().lower()
        if tier not in _CANONICAL_TIERS:
            raise HTTPException(status_code=422, detail=f"Unsupported tier: {tier}")

        scope = str(payload.get("scope") or "project").strip() or "project"
        target = str(payload.get("target") or "").strip().lower()
        expected_target = _TIER_TARGET[tier]
        if target and target != expected_target:
            raise HTTPException(
                status_code=422,
                detail=f"tier {tier!r} must use target {expected_target!r}",
            )

        metadata = dict(payload.get("metadata") or {})
        metadata["memory_kind"] = _memory_kind_for(tier, metadata)
        actor_user_id = _actor_user_id(payload)
        if tier in _PRIVATE_TIERS and actor_user_id and not metadata.get("user_id"):
            metadata["user_id"] = actor_user_id
        content = str(payload.get("content") or "").strip()

        if tier == "preferences":
            key = _normalize_pref_key(
                str(metadata.get("key") or payload.get("key") or "")
            )
            if not key:
                raise HTTPException(
                    status_code=422, detail="preferences write requires key"
                )
            user_id = str(
                metadata.get("user_id") or payload.get("user_id") or ""
            ).strip()
            if not user_id and actor_user_id:
                user_id = actor_user_id
            if not _actor_can_read_private(payload, user_id):
                raise HTTPException(status_code=403, detail="memory user scope denied")
            value = metadata.get("value", payload.get("value", content))
            result = self._upsert_ltm_preference(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                user_id=user_id,
                key=key,
                value=value,
                scope=scope,
            )
            return {
                "entry_id": result.entry_id,
                "path": result.path,
                "created_at": result.created_at,
                "line_start": result.line_start,
            }

        if tier == "stm":
            conv_id = str(
                metadata.get("conversation_id") or payload.get("conversation_id") or ""
            ).strip()
            if not conv_id:
                raise HTTPException(
                    status_code=422, detail="stm write requires conversation_id"
                )
            if not _actor_can_read_private(payload, str(metadata.get("user_id") or "")):
                raise HTTPException(status_code=403, detail="memory user scope denied")
            summary = (
                metadata.get("stm_summary")
                if isinstance(metadata.get("stm_summary"), dict)
                else {}
            )
            if not content:
                content = str(
                    summary.get("final_answer") or metadata.get("summary") or ""
                ).strip()
            if not content:
                raise HTTPException(
                    status_code=422, detail="stm write requires content"
                )
            metadata["conversation_id"] = conv_id
            rel_path = f"stm/{conv_id}.md"
            overwrite = False
            pref_key = None
        elif tier == "wm":
            task_id = str(
                metadata.get("task_id") or payload.get("task_id") or ""
            ).strip()
            if not task_id:
                raise HTTPException(status_code=422, detail="wm write requires task_id")
            if not _actor_can_read_private(payload, str(metadata.get("user_id") or "")):
                raise HTTPException(status_code=403, detail="memory user scope denied")
            ttl_s = _positive_int_or_none(
                metadata.get("ttl_s", payload.get("ttl_s")),
                field_name="ttl_s",
            )
            if ttl_s is not None:
                metadata["ttl_s"] = ttl_s
                metadata["expires_at_s"] = float(time.time()) + float(ttl_s)
            state = metadata.get("state", payload.get("state"))
            if not content:
                state_obj = self._coerce_wm_state_to_json_object(state)
                content = (
                    "```json\n"
                    + json.dumps(state_obj, ensure_ascii=False, default=str)
                    + "\n```"
                )
            metadata["task_id"] = task_id
            rel_path = f"wm/{task_id}.md"
            overwrite = True
            pref_key = None
        elif tier == "semantic":
            if not content:
                raise HTTPException(
                    status_code=422, detail="semantic write requires content"
                )
            rel_path = f"memory/{_utc_date()}.md"
            overwrite = False
            pref_key = None
        else:
            subject = str(
                metadata.get("subject") or payload.get("subject") or ""
            ).strip()
            relation = str(
                metadata.get("relation") or payload.get("relation") or ""
            ).strip()
            obj = str(metadata.get("obj") or payload.get("obj") or "").strip()
            if not (subject and relation and obj):
                raise HTTPException(
                    status_code=422, detail="graph write requires subject/relation/obj"
                )
            if not content:
                content = f"- ({subject}) -[{relation}]-> ({obj})"
            metadata.update({"subject": subject, "relation": relation, "obj": obj})
            rel_path = f"graph/relations/{_utc_date()}.md"
            overwrite = False
            pref_key = None

        result = self._write_entry(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            rel_path=rel_path,
            tier=tier,
            scope=scope,
            content_md=content,
            metadata=metadata,
            overwrite=overwrite,
            pref_key=pref_key,
        )

        if tier == "graph":
            best_effort_upsert(
                cfg=self._service_config,
                edge=GraphEdge(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    scope=scope,
                    subject=str(metadata["subject"]),
                    relation=str(metadata["relation"]),
                    obj=str(metadata["obj"]),
                    entry_id=result.entry_id,
                    source_path=result.path,
                    source_line=result.line_start,
                ),
            )

        return {
            "entry_id": result.entry_id,
            "path": result.path,
            "created_at": result.created_at,
            "line_start": result.line_start,
        }

    def search_memory(
        self, *, tenant_id: str, workspace_id: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        self._require_scope(tenant_id=tenant_id, workspace_id=workspace_id)
        query = str(payload.get("query") or "").strip()
        # NOTE: don't use `or 5` here; `0` must be rejected rather than coerced.
        try:
            top_k = int(payload.get("top_k", 5))
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail="top_k must be an integer"
            ) from exc
        if top_k <= 0 or top_k > 100:
            raise HTTPException(
                status_code=422, detail="top_k must be between 1 and 100"
            )
        tiers = _clean_filter_list(payload.get("tiers"))
        scopes = _clean_filter_list(payload.get("scopes"))
        memory_kinds = _clean_filter_list(payload.get("memory_kinds"))
        path_prefixes = _clean_path_prefixes(payload.get("path_prefixes"))
        started_s = time.monotonic()
        fts_meta: Dict[str, Any] = {}
        fts_hit_count = 0
        vector_hit_count = 0

        ws = self._ws_root(tenant_id=tenant_id, workspace_id=workspace_id)
        key = self._ws_key(tenant_id=tenant_id, workspace_id=workspace_id)

        # If index appears stale (typically due to manual file edits), trigger a background rebuild.
        self._maybe_rebuild_index_async_if_stale(key=key, ws_root=ws)

        def _open_index_or_rebuild() -> SqliteFtsIndex:
            try:
                return self._index(ws_root=ws)
            except RuntimeError as exc:
                if (
                    self._auto_rebuild_enabled_on_failure()
                    and self._is_rebuildable_index_error(exc)
                ):
                    ok = self._maybe_rebuild_index_sync(key=key, ws_root=ws)
                    if ok:
                        return self._index(ws_root=ws)
                raise

        try:
            index = _open_index_or_rebuild()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("index init error")
            raise HTTPException(status_code=503, detail="Search index error") from exc
        try:
            try:
                try:
                    hits, fts_meta = _search_index_with_fallback(
                        index,
                        query=query,
                        top_k=top_k,
                        tiers=tiers,
                        scopes=scopes,
                        memory_kinds=memory_kinds,
                        path_prefixes=path_prefixes,
                    )
                except RuntimeError as exc:
                    # Auto heal derived index and retry once.
                    if (
                        self._auto_rebuild_enabled_on_failure()
                        and self._is_rebuildable_index_error(exc)
                    ):
                        ok = self._maybe_rebuild_index_sync(key=key, ws_root=ws)
                        if ok:
                            index.close()
                            index = _open_index_or_rebuild()
                            hits, fts_meta = _search_index_with_fallback(
                                index,
                                query=query,
                                top_k=top_k,
                                tiers=tiers,
                                scopes=scopes,
                                memory_kinds=memory_kinds,
                                path_prefixes=path_prefixes,
                            )
                        else:
                            raise
                    else:
                        raise
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            hits = [h for h in hits if _hit_is_visible_to_actor(h, payload)]
            fts_hit_count = len(hits)
            if self._vector_enabled() and query:
                try:
                    _qemb = self._embed_text(query)
                    if _qemb is not None:
                        vector_tiers = tiers
                        vector_scopes = scopes
                        if self._vector_backend() == "pgvector":
                            pg_index = self._pgvector_index(
                                tenant_id=tenant_id, workspace_id=workspace_id
                            )
                            if pg_index is None:
                                _vhits = []
                            else:
                                try:
                                    _vhits = pg_index.vector_search(
                                        query_embedding=_qemb,
                                        top_k=top_k,
                                        tiers=vector_tiers,
                                        scopes=vector_scopes,
                                        memory_kinds=memory_kinds,
                                        path_prefixes=path_prefixes,
                                    )
                                finally:
                                    pg_index.close()
                        else:
                            _vhits = index.vector_search(
                                query_embedding=_qemb,
                                top_k=top_k,
                                tiers=vector_tiers,
                                scopes=vector_scopes,
                                memory_kinds=memory_kinds,
                                path_prefixes=path_prefixes,
                            )
                        _vhits = [
                            h for h in (_vhits or []) if _hit_is_visible_to_actor(h, payload)
                        ]
                        vector_hit_count = len(_vhits)
                        hits = _rrf_merge(hits, _vhits, top_k)
                except Exception:
                    logger.exception("vector search failed; using FTS results only")
        finally:
            index.close()

        result_hits = [
            {
                "score": h.score,
                "snippet": h.snippet,
                "path": h.path,
                "line": h.line,
                "entry_id": h.entry_id,
                "tier": h.tier,
                "scope": h.scope,
                "memory_kind": (h.metadata or {}).get("memory_kind"),
                "created_at": h.created_at,
                "metadata": h.metadata,
            }
            for h in hits
        ]
        _log_memory_search_event(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            query=query,
            top_k=top_k,
            tiers=tiers,
            scopes=scopes,
            memory_kinds=memory_kinds,
            path_prefixes=path_prefixes,
            payload=payload,
            fts_meta=fts_meta,
            fts_hit_count=fts_hit_count,
            vector_hit_count=vector_hit_count,
            result_hit_count=len(result_hits),
            duration_ms=round((time.monotonic() - started_s) * 1000, 3),
        )
        return {"hits": result_hits}

    def read_memory(
        self, *, tenant_id: str, workspace_id: str, payload: Dict[str, Any]
    ) -> Any:
        self._require_scope(tenant_id=tenant_id, workspace_id=workspace_id)
        tier = str(payload.get("tier") or "").strip().lower()
        if tier not in _CANONICAL_TIERS:
            raise HTTPException(status_code=422, detail=f"Unsupported tier: {tier}")

        ws = self._ws_root(tenant_id=tenant_id, workspace_id=workspace_id)

        if tier == "stm":
            conv_id = str(
                payload.get("conversation_id") or payload.get("id") or ""
            ).strip()
            if not conv_id:
                raise HTTPException(
                    status_code=422, detail="stm read requires conversation_id"
                )
            last_k = int(
                payload.get("last_k")
                or payload.get("limit")
                or payload.get("top_k")
                or 15
            )
            abs_path = safe_workspace_path(
                root=ws, relative_path=f"stm/{conv_id}.md", require_md=True
            )
            try:
                text = abs_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return []
            items: List[Dict[str, Any]] = []
            for entry in iter_entries(text):
                meta = entry.metadata or {}
                if not _actor_can_read_private(payload, str(meta.get("user_id") or "")):
                    continue
                summary = meta.get("stm_summary") or {}
                if isinstance(summary, dict):
                    items.append(summary)
            return items[-max(1, last_k) :]

        if tier == "wm":
            task_id = str(payload.get("task_id") or payload.get("id") or "").strip()
            if not task_id:
                raise HTTPException(status_code=422, detail="wm read requires task_id")
            abs_path = safe_workspace_path(
                root=ws, relative_path=f"wm/{task_id}.md", require_md=True
            )
            try:
                text = abs_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return None
            latest_entry = None
            for entry in iter_entries(text):
                latest_entry = entry
            if latest_entry is not None:
                meta = latest_entry.metadata or {}
                if not _actor_can_read_private(payload, str(meta.get("user_id") or "")):
                    raise HTTPException(
                        status_code=403, detail="memory user scope denied"
                    )
                expires_at_s = meta.get("expires_at_s")
                if expires_at_s is not None:
                    try:
                        expired = float(time.time()) >= float(expires_at_s)
                    except Exception:
                        expired = False
                    if expired:
                        try:
                            abs_path.unlink()
                        except FileNotFoundError:
                            pass
                        except Exception:
                            logger.warning(
                                "expired wm state could not be deleted",
                                extra={"path": str(abs_path)},
                                exc_info=True,
                            )
                        return None
            return first_json_code_block(text)

        if tier == "preferences":
            user_id = str(payload.get("user_id") or "").strip()
            if not user_id and _actor_role(payload) not in _PRIVILEGED_ACTOR_ROLES:
                user_id = _actor_user_id(payload)
            if user_id and not _actor_can_read_private(payload, user_id):
                raise HTTPException(status_code=403, detail="memory user scope denied")
            key = _normalize_pref_key(str(payload.get("key") or ""))
            if key:
                return self._preference_file_value(ws=ws, user_id=user_id, key=key)
            try:
                cap = int(payload.get("limit") or 50)
            except Exception:
                cap = 50
            cap = max(1, cap)
            latest: Dict[str, Any] = {}
            pref_root = ws / "preferences"
            roots = (
                [pref_root / _safe_pref_path_part(user_id, fallback="_global")]
                if user_id
                else [pref_root]
            )
            for root in roots:
                if not root.exists():
                    continue
                for p in sorted(root.rglob("*.md")):
                    try:
                        text = p.read_text(encoding="utf-8")
                    except FileNotFoundError:
                        continue
                    for entry in iter_entries(text):
                        meta = entry.metadata or {}
                        if str(meta.get("tier") or "") != "preferences":
                            continue
                        k = str(meta.get("key") or "").strip()
                        if k:
                            latest[k] = meta.get("value")
            if len(latest) > cap:
                latest = dict(list(latest.items())[-cap:])
            return latest

        if tier == "graph":
            query = str(payload.get("query") or "").strip()
            if not query:
                raise HTTPException(status_code=422, detail="graph read requires query")
            return self.search_memory(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                payload={
                    "query": query,
                    "top_k": int(payload.get("top_k") or payload.get("limit") or 5),
                    "tiers": ["graph"],
                    "memory_kinds": ["kg_relation"],
                    "path_prefixes": ["graph/relations/"],
                    "scopes": payload.get("scopes"),
                },
            )

        raise HTTPException(
            status_code=422, detail="semantic memories are read through search"
        )

    def get_memory(
        self, *, tenant_id: str, workspace_id: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        self._require_scope(tenant_id=tenant_id, workspace_id=workspace_id)
        rel_path = str(payload.get("path") or "").strip()
        start_line = payload.get("start_line")
        max_lines = payload.get("max_lines")

        ws = self._ws_root(tenant_id=tenant_id, workspace_id=workspace_id)
        try:
            abs_path = safe_workspace_path(
                root=ws, relative_path=rel_path, require_md=True
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            text = abs_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Not found")

        tier = rel_path.replace("\\", "/").lstrip("/").split("/", 1)[0].lower()
        if tier in _PRIVATE_TIERS:
            if tier == "preferences":
                safe_actor = _safe_pref_path_part(
                    _actor_user_id(payload), fallback="_global"
                )
                privileged = _actor_role(payload) in _PRIVILEGED_ACTOR_ROLES
                if not privileged and not rel_path.replace("\\", "/").lstrip(
                    "/"
                ).startswith(f"preferences/{safe_actor}/"):
                    raise HTTPException(
                        status_code=403, detail="memory user scope denied"
                    )
            elif not _entries_visible_to_actor(text, payload):
                raise HTTPException(status_code=403, detail="memory user scope denied")

        if start_line is not None or max_lines is not None:
            s = int(start_line) if start_line is not None else 1
            m = int(max_lines) if max_lines is not None else 200
            if s <= 0 or m <= 0:
                raise HTTPException(
                    status_code=422, detail="Invalid start_line/max_lines"
                )
            lines = text.splitlines()
            text = "\n".join(lines[s - 1 : s - 1 + m])

        return {"path": rel_path, "content": text}

    def rebuild_index(self, *, tenant_id: str, workspace_id: str) -> Dict[str, Any]:
        self._require_scope(tenant_id=tenant_id, workspace_id=workspace_id)
        if (
            os.getenv("AGENT_MEMORY_INDEX_REBUILD_ENABLED") or ""
        ).strip().lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            raise HTTPException(status_code=403, detail="Index rebuild disabled")

        ws = self._ws_root(tenant_id=tenant_id, workspace_id=workspace_id)
        try:
            count = self._rebuild_index_from_workspace(ws_root=ws)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("index rebuild error")
            raise HTTPException(status_code=503, detail="Search index error") from exc

        return {"status": "success", "indexed_entries": int(count)}

    def status(self) -> Dict[str, Any]:
        root = str(os.getenv("AGENT_MEMORY_FILE_ROOT") or "").strip() or str(
            Path("~/.agent_memory_service/workspaces").expanduser()
        )
        return {
            "backend": "file_first",
            "file_root": root,
            "graph_enabled": (os.getenv("AGENT_MEMORY_GRAPH_ENABLED") or "").strip(),
        }

    def stats(self, *, tenant_id: str, workspace_id: str) -> Dict[str, Any]:
        self._require_scope(tenant_id=tenant_id, workspace_id=workspace_id)
        ws = self._ws_root(tenant_id=tenant_id, workspace_id=workspace_id)

        def _sum_sizes(paths: List[Path]) -> int:
            total = 0
            for p in paths:
                try:
                    total += int(p.stat().st_size)
                except FileNotFoundError:
                    continue
            return total

        def _count_entries(paths: List[Path]) -> int:
            count = 0
            for p in paths:
                try:
                    text = p.read_text(encoding="utf-8")
                except FileNotFoundError:
                    continue
                for _ in iter_entries(text):
                    count += 1
            return count

        stm_files = [p for p in (ws / "stm").glob("*.md") if p.is_file()]
        wm_files = [p for p in (ws / "wm").glob("*.md") if p.is_file()]
        preference_files = [
            p for p in (ws / "preferences").rglob("*.md") if p.is_file()
        ]
        daily_files = [p for p in (ws / "memory").glob("*.md") if p.is_file()]
        graph_files = [
            p for p in (ws / "graph" / "relations").glob("*.md") if p.is_file()
        ]

        stm_count = _count_entries(stm_files)
        stm_size = _sum_sizes(stm_files)

        # WM is overwrite-by-file; each file represents one current state.
        wm_count = len(wm_files)
        wm_size = _sum_sizes(wm_files)

        ltm_files = preference_files + daily_files
        ltm_count = _count_entries(ltm_files)
        ltm_size = _sum_sizes(ltm_files)

        # Graph: best-effort node/edge counts from Markdown truth.
        edges = 0
        nodes: set[str] = set()
        for p in graph_files:
            try:
                text = p.read_text(encoding="utf-8")
            except FileNotFoundError:
                continue
            for entry in iter_entries(text):
                meta = entry.metadata or {}
                subject = str(
                    meta.get("subject") or meta.get("kg", {}).get("subject") or ""
                ).strip()
                obj = str(
                    meta.get("obj") or meta.get("kg", {}).get("obj") or ""
                ).strip()
                relation = str(
                    meta.get("relation") or meta.get("kg", {}).get("relation") or ""
                ).strip()
                if subject and obj and relation:
                    edges += 1
                    nodes.add(subject)
                    nodes.add(obj)

        kg_size = _sum_sizes(graph_files)

        md_files = [
            p for p in ws.rglob("*.md") if p.is_file() and ".index" not in str(p)
        ]
        total_size = _sum_sizes(md_files)

        # Best-effort index status (derived; safe to delete/rebuild).
        index_path = ws / ".index" / "index.sqlite"
        try:
            idx_mtime_s = (
                float(index_path.stat().st_mtime) if index_path.exists() else None
            )
        except FileNotFoundError:
            idx_mtime_s = None
        index_stale = self._compute_index_stale(ws_root=ws)

        # Portal/admin UI expects this shape.
        return {
            "stm": {"count": int(stm_count), "size_bytes": int(stm_size)},
            "wm": {"count": int(wm_count), "size_bytes": int(wm_size)},
            "ltm": {"count": int(ltm_count), "size_bytes": int(ltm_size)},
            "knowledge_graph": {
                "nodes": int(len(nodes)),
                "edges": int(edges),
                "size_bytes": int(kg_size),
            },
            # Extra info for debugging/ops.
            "file_first": {
                "files": int(len(md_files)),
                "size_bytes": int(total_size),
                "root": str(ws),
                "index": {
                    "path": str(index_path),
                    "mtime_s": idx_mtime_s,
                    "stale": bool(index_stale),
                },
            },
        }
