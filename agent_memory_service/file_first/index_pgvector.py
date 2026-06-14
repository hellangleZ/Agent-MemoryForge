from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Sequence

from agent_memory_service.file_first.index_sqlite import SearchHit, _clean_index_snippet


def _as_float_vector(values: Sequence[float]) -> List[float]:
    out: List[float] = []
    for value in values:
        f = float(value)
        if not math.isfinite(f):
            raise ValueError("embedding contains non-finite value")
        out.append(f)
    if not out:
        raise ValueError("embedding must not be empty")
    return out


def _vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{v:.8g}" for v in _as_float_vector(values)) + "]"


class PgVectorIndex:
    """Postgres/pgvector derived index for enterprise-scale vector search.

    Markdown plus SQLite FTS remain the source of truth and keyword index. This
    class stores only rebuildable vector rows and performs ANN-capable nearest
    neighbor search through pgvector instead of loading every vector into Python.
    """

    def __init__(
        self,
        *,
        dsn: str,
        tenant_id: str,
        workspace_id: str,
        dim: int,
        table_name: str = "agent_memory_vectors",
        connect_timeout_s: float = 5.0,
        connection: Any = None,
    ) -> None:
        self.dsn = str(dsn or "").strip()
        self.tenant_id = str(tenant_id)
        self.workspace_id = str(workspace_id)
        self.dim = int(dim)
        if self.dim <= 0:
            raise ValueError("pgvector dim must be positive")
        self.table_name = self._safe_identifier(table_name)
        self._conn = connection
        self._connect_timeout_s = float(connect_timeout_s)

        if self._conn is None:
            try:
                import psycopg
            except Exception as exc:  # pragma: no cover - depends on optional extra
                raise RuntimeError(
                    "psycopg is required for AGENT_MEMORY_VECTOR_BACKEND=pgvector"
                ) from exc
            self._conn = psycopg.connect(
                self.dsn,
                autocommit=True,
                connect_timeout=self._connect_timeout_s,
            )
        self._ensure_schema()

    @classmethod
    def from_env(cls, *, tenant_id: str, workspace_id: str) -> Optional["PgVectorIndex"]:
        backend = (os.getenv("AGENT_MEMORY_VECTOR_BACKEND") or "").strip().lower()
        dsn = (
            os.getenv("AGENT_MEMORY_PGVECTOR_DSN")
            or os.getenv("AGENT_MEMORY_POSTGRES_DSN")
            or ""
        ).strip()
        if backend not in {"pgvector", "postgres", "postgresql"} and not dsn:
            return None
        if backend and backend not in {"pgvector", "postgres", "postgresql"}:
            return None
        if not dsn:
            raise RuntimeError("AGENT_MEMORY_PGVECTOR_DSN is required for pgvector")
        dim = int(os.getenv("AGENT_MEMORY_PGVECTOR_DIM") or "1536")
        table_name = os.getenv("AGENT_MEMORY_PGVECTOR_TABLE") or "agent_memory_vectors"
        timeout = float(os.getenv("AGENT_MEMORY_PGVECTOR_CONNECT_TIMEOUT_S") or "5")
        return cls(
            dsn=dsn,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            dim=dim,
            table_name=table_name,
            connect_timeout_s=timeout,
        )

    @staticmethod
    def _safe_identifier(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("identifier must not be empty")
        if not all(ch.isalnum() or ch == "_" for ch in text):
            raise ValueError("identifier may contain only letters, numbers, and underscore")
        if text[0].isdigit():
            raise ValueError("identifier must not start with a number")
        return text

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            return

    def _ensure_schema(self) -> None:
        table = self.table_name
        with self._conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                  id BIGSERIAL PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  workspace_id TEXT NOT NULL,
                  path TEXT NOT NULL,
                  entry_id TEXT,
                  tier TEXT,
                  scope TEXT,
                  memory_kind TEXT,
                  created_at TEXT,
                  line_start INTEGER NOT NULL DEFAULT 1,
                  embedding vector({self.dim}) NOT NULL,
                  content TEXT,
                  metadata_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  UNIQUE (tenant_id, workspace_id, path, entry_id, line_start)
                )
                """
            )
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN memory_kind TEXT")
            except Exception:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {table}_scope_idx
                ON {table} (tenant_id, workspace_id, tier, scope, memory_kind)
                """
            )
            # HNSW is available on pgvector >= 0.5. If the installed extension is
            # older, the table still works with exact pgvector search.
            try:
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS {table}_embedding_hnsw_idx
                    ON {table}
                    USING hnsw (embedding vector_cosine_ops)
                    """
                )
            except Exception:
                try:
                    self._conn.rollback()
                except Exception:
                    pass

    def delete_by_path(self, *, path: str) -> int:
        table = self.table_name
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                DELETE FROM {table}
                WHERE tenant_id = %s AND workspace_id = %s AND path = %s
                """,
                (self.tenant_id, self.workspace_id, path),
            )
            return int(getattr(cur, "rowcount", 0) or 0)

    def insert_vector(
        self,
        *,
        path: str,
        entry_id: Optional[str],
        tier: Optional[str],
        scope: Optional[str],
        memory_kind: Optional[str] = None,
        created_at: Optional[str] = None,
        line_start: int = 1,
        content: str,
        metadata: Dict[str, Any],
        embedding: Sequence[float],
    ) -> None:
        vec = _as_float_vector(embedding)
        if len(vec) != self.dim:
            raise ValueError(f"embedding dim {len(vec)} does not match pgvector dim {self.dim}")
        table = self.table_name
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {table}
                  (tenant_id, workspace_id, path, entry_id, tier, scope, memory_kind, created_at,
                   line_start, embedding, content, metadata_json, updated_at)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s::jsonb, now())
                ON CONFLICT (tenant_id, workspace_id, path, entry_id, line_start)
                DO UPDATE SET
                  tier = EXCLUDED.tier,
                  scope = EXCLUDED.scope,
                  memory_kind = EXCLUDED.memory_kind,
                  created_at = EXCLUDED.created_at,
                  embedding = EXCLUDED.embedding,
                  content = EXCLUDED.content,
                  metadata_json = EXCLUDED.metadata_json,
                  updated_at = now()
                """,
                (
                    self.tenant_id,
                    self.workspace_id,
                    path,
                    entry_id,
                    tier,
                    scope,
                    memory_kind,
                    created_at,
                    int(line_start),
                    _vector_literal(vec),
                    str(content or ""),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )

    def vector_search(
        self,
        *,
        query_embedding: Sequence[float],
        top_k: int = 5,
        tiers: Optional[Sequence[str]] = None,
        scopes: Optional[Sequence[str]] = None,
        memory_kinds: Optional[Sequence[str]] = None,
        path_prefixes: Optional[Sequence[str]] = None,
    ) -> List[SearchHit]:
        vec = _as_float_vector(query_embedding)
        if len(vec) != self.dim:
            return []
        where: List[str] = ["tenant_id = %s", "workspace_id = %s"]
        where_params: List[Any] = [self.tenant_id, self.workspace_id]
        if tiers:
            where.append("tier = ANY(%s)")
            where_params.append([str(t) for t in tiers])
        if scopes:
            where.append("scope = ANY(%s)")
            where_params.append([str(s) for s in scopes])
        if memory_kinds:
            where.append("memory_kind = ANY(%s)")
            where_params.append([str(k) for k in memory_kinds])
        if path_prefixes:
            where.append("(" + " OR ".join("path LIKE %s" for _ in path_prefixes) + ")")
            where_params.extend([str(p) + "%" for p in path_prefixes])
        query_vec = _vector_literal(vec)

        table = self.table_name
        sql = f"""
            SELECT
              path,
              line_start,
              entry_id,
              tier,
              scope,
              created_at,
              metadata_json,
              content,
              1 - (embedding <=> %s::vector) AS score
            FROM {table}
            WHERE {' AND '.join(where)}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        hits: List[SearchHit] = []
        with self._conn.cursor() as cur:
            cur.execute(sql, tuple([query_vec, *where_params, query_vec, int(top_k)]))
            for path, line_start, entry_id, tier, scope, created_at, meta_json, content, score in cur.fetchall():
                meta = meta_json or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                if not isinstance(meta, dict):
                    meta = {}
                hits.append(
                    SearchHit(
                        score=float(score or 0.0),
                        snippet=_clean_index_snippet(content, content, meta),
                        path=str(path),
                        line=int(line_start or 1),
                        entry_id=str(entry_id) if entry_id is not None else None,
                        tier=str(tier) if tier is not None else None,
                        scope=str(scope) if scope is not None else None,
                        created_at=str(created_at) if created_at is not None else None,
                        metadata=meta,
                    )
                )
        return hits


__all__ = ["PgVectorIndex", "_vector_literal"]
