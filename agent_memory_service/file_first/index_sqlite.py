from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS docs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT NOT NULL,
  entry_id TEXT,
  tier TEXT,
  scope TEXT,
  memory_kind TEXT,
  created_at TEXT,
  line_start INTEGER,
  content TEXT NOT NULL,
  metadata_json TEXT,
  pref_key TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts
USING fts5(content, content='docs', content_rowid='id', tokenize='porter');

CREATE INDEX IF NOT EXISTS idx_docs_path ON docs(path);
CREATE INDEX IF NOT EXISTS idx_docs_tier ON docs(tier);
CREATE INDEX IF NOT EXISTS idx_docs_scope ON docs(scope);
CREATE INDEX IF NOT EXISTS idx_docs_memory_kind ON docs(memory_kind);
CREATE INDEX IF NOT EXISTS idx_docs_pref_key ON docs(pref_key);

CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
  INSERT INTO docs_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON docs BEGIN
  INSERT INTO docs_fts(docs_fts, rowid, content) VALUES('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE OF content ON docs BEGIN
  INSERT INTO docs_fts(docs_fts, rowid, content) VALUES('delete', old.id, old.content);
  INSERT INTO docs_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TABLE IF NOT EXISTS vecs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT NOT NULL,
  entry_id TEXT,
  tier TEXT,
  scope TEXT,
  memory_kind TEXT,
  created_at TEXT,
  line_start INTEGER,
  dim INTEGER,
  embedding BLOB,
  content TEXT,
  metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_vecs_path ON vecs(path);
CREATE INDEX IF NOT EXISTS idx_vecs_memory_kind ON vecs(memory_kind);
"""


@dataclass(frozen=True)
class SearchHit:
    score: float
    snippet: str
    path: str
    line: int
    entry_id: Optional[str]
    tier: Optional[str]
    scope: Optional[str]
    created_at: Optional[str]
    metadata: Dict[str, Any]


def _clean_index_snippet(snippet: Any, content: Any, metadata: Dict[str, Any]) -> str:
    subject = str((metadata or {}).get("subject") or "").strip()
    relation = str((metadata or {}).get("relation") or "").strip()
    obj = str((metadata or {}).get("obj") or "").strip()
    if subject and relation and obj:
        return f"{subject} -[{relation}]-> {obj}"

    metadata_key_re = re.compile(
        r'"(?:created_at|entry_id|memory_kind|source|tenant_id|workspace_id|tags)"\s*:'
    )

    text = str(snippet or "").strip()
    if (
        "<!--" in text
        or "am:entry" in text
        or "-->" in text
        or metadata_key_re.search(text)
    ):
        text = str(content or "").strip()
    text = re.sub(r"<!--\s*am:entry\b.*?-->", "", text, flags=re.DOTALL)
    if "-->" in text:
        text = text.rsplit("-->", 1)[-1]
    if "-[" not in text:
        text = text.replace("[", "").replace("]", "")
    text = re.sub(r"\s+", " ", text).strip()
    if metadata_key_re.search(text):
        return ""
    return text.strip(" …")


class SqliteFtsIndex:
    _QUERY_TOKEN_RE = re.compile(r"[^\w]+", re.UNICODE)

    @classmethod
    def normalize_query(cls, query: str) -> str:
        """Normalize a user query into a safe FTS5 MATCH string.

        FTS5 treats characters like '-' as operators in certain contexts, which
        can produce confusing errors (e.g. "no such column"). We normalize to a
        simple AND-of-tokens query by stripping punctuation into spaces.
        """
        raw = (query or "").strip()
        if not raw:
            return ""
        cleaned = cls._QUERY_TOKEN_RE.sub(" ", raw).strip()
        tokens = [t for t in cleaned.split() if t]
        return " ".join(tokens)

    def __init__(self, *, index_path: Path) -> None:
        self.index_path = index_path
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self.conn = sqlite3.connect(str(self.index_path), timeout=15)
            self.conn.execute("PRAGMA foreign_keys=ON")
            self._ensure_schema()
        except sqlite3.DatabaseError as exc:
            raise RuntimeError("Search index is corrupted; rebuild the index") from exc

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            return

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        existing = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _ensure_schema(self) -> None:
        try:
            self.conn.executescript(SCHEMA_SQL)
            self._ensure_column("docs", "memory_kind", "TEXT")
            self._ensure_column("vecs", "memory_kind", "TEXT")
            self.conn.commit()
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if "fts5" in msg:
                raise RuntimeError(
                    "SQLite FTS5 is not available in this Python/SQLite build; "
                    "File-First search requires FTS5."
                ) from exc
            raise

    def delete_by_path(self, *, path: str) -> int:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM docs WHERE path = ?", (path,))
        n = cur.rowcount or 0
        self.conn.commit()
        return int(n)

    def insert_chunk(
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
        pref_key: Optional[str] = None,
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO docs (path, entry_id, tier, scope, memory_kind, created_at, line_start, content, metadata_json, pref_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                path,
                entry_id,
                tier,
                scope,
                memory_kind,
                created_at,
                int(line_start),
                content,
                json.dumps(metadata or {}, ensure_ascii=False),
                pref_key,
            ),
        )
        self.conn.commit()

    def insert_chunks(self, chunks: Sequence[Dict[str, Any]]) -> None:
        rows = []
        for chunk in chunks:
            rows.append(
                (
                    chunk.get("path"),
                    chunk.get("entry_id"),
                    chunk.get("tier"),
                    chunk.get("scope"),
                    chunk.get("memory_kind")
                    or (chunk.get("metadata") or {}).get("memory_kind"),
                    chunk.get("created_at"),
                    int(chunk.get("line_start") or 1),
                    chunk.get("content") or "",
                    json.dumps(chunk.get("metadata") or {}, ensure_ascii=False),
                    chunk.get("pref_key"),
                )
            )
        if not rows:
            return
        cur = self.conn.cursor()
        cur.executemany(
            """
            INSERT INTO docs (path, entry_id, tier, scope, memory_kind, created_at, line_start, content, metadata_json, pref_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.conn.commit()

    def delete_vectors_by_path(self, *, path: str) -> int:
        cur = self.conn.cursor()
        try:
            cur.execute("DELETE FROM vecs WHERE path = ?", (path,))
            self.conn.commit()
            return int(cur.rowcount or 0)
        except sqlite3.OperationalError:
            return 0

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
        content: str = "",
        metadata: Dict[str, Any],
        embedding: Sequence[float],
    ) -> None:
        import numpy as np

        arr = np.asarray(list(embedding), dtype=np.float32)
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO vecs (path, entry_id, tier, scope, memory_kind, created_at, line_start, dim, embedding, content, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                path,
                entry_id,
                tier,
                scope,
                memory_kind,
                created_at,
                int(line_start),
                int(arr.size),
                arr.tobytes(),
                content,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        self.conn.commit()

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
        import numpy as np

        where: List[str] = ["embedding IS NOT NULL"]
        params: List[Any] = []
        if tiers:
            where.append("tier IN (%s)" % ",".join("?" for _ in tiers))
            params.extend([str(t) for t in tiers])
        if scopes:
            where.append("scope IN (%s)" % ",".join("?" for _ in scopes))
            params.extend([str(s) for s in scopes])
        if memory_kinds:
            where.append("memory_kind IN (%s)" % ",".join("?" for _ in memory_kinds))
            params.extend([str(k) for k in memory_kinds])
        if path_prefixes:
            where.append("(" + " OR ".join("path LIKE ?" for _ in path_prefixes) + ")")
            params.extend([str(p) + "%" for p in path_prefixes])
        sql = (
            "SELECT path, line_start, entry_id, tier, scope, created_at, metadata_json, content, embedding "
            "FROM vecs WHERE " + " AND ".join(where)
        )
        cur = self.conn.cursor()
        try:
            cur.execute(sql, tuple(params))
        except sqlite3.OperationalError:
            return []
        rows = cur.fetchall()
        if not rows:
            return []
        q = np.asarray(list(query_embedding), dtype=np.float32)
        qn = float(np.linalg.norm(q))
        if qn == 0.0:
            return []
        q = q / qn
        scored: List[tuple] = []
        for (
            path,
            line_start,
            entry_id,
            tier,
            scope,
            created_at,
            meta_json,
            content,
            emb,
        ) in rows:
            v = np.frombuffer(emb, dtype=np.float32)
            if v.size == 0 or v.size != q.size:
                continue
            vn = float(np.linalg.norm(v))
            if vn == 0.0:
                continue
            cos = float(np.dot(q, v / vn))
            scored.append(
                (
                    cos,
                    path,
                    line_start,
                    entry_id,
                    tier,
                    scope,
                    created_at,
                    meta_json,
                    content,
                )
            )
        scored.sort(key=lambda x: x[0], reverse=True)
        hits: List[SearchHit] = []
        for (
            cos,
            path,
            line_start,
            entry_id,
            tier,
            scope,
            created_at,
            meta_json,
            content,
        ) in scored[: int(top_k)]:
            try:
                meta = json.loads(meta_json) if meta_json else {}
                if not isinstance(meta, dict):
                    meta = {}
            except Exception:
                meta = {}
            hits.append(
                SearchHit(
                    score=float(cos),
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

    def search(
        self,
        *,
        query: str,
        top_k: int = 5,
        tiers: Optional[Sequence[str]] = None,
        scopes: Optional[Sequence[str]] = None,
        memory_kinds: Optional[Sequence[str]] = None,
        path_prefixes: Optional[Sequence[str]] = None,
    ) -> List[SearchHit]:
        q = self.normalize_query(query)
        if not q:
            return []

        where: List[str] = ["docs_fts MATCH ?"]
        params: List[Any] = [q]

        if tiers:
            where.append("docs.tier IN (%s)" % ",".join("?" for _ in tiers))
            params.extend([str(t) for t in tiers])
        if scopes:
            where.append("docs.scope IN (%s)" % ",".join("?" for _ in scopes))
            params.extend([str(s) for s in scopes])
        if memory_kinds:
            where.append(
                "docs.memory_kind IN (%s)" % ",".join("?" for _ in memory_kinds)
            )
            params.extend([str(k) for k in memory_kinds])
        if path_prefixes:
            where.append(
                "(" + " OR ".join("docs.path LIKE ?" for _ in path_prefixes) + ")"
            )
            params.extend([str(p) + "%" for p in path_prefixes])

        sql = f"""
        SELECT
          bm25(docs_fts) AS bm25_score,
          snippet(docs_fts, 0, '[', ']', '…', 12) AS snippet,
          docs.path,
          docs.line_start,
          docs.entry_id,
          docs.tier,
          docs.scope,
          docs.created_at,
          docs.metadata_json,
          docs.content
        FROM docs_fts
        JOIN docs ON docs_fts.rowid = docs.id
        WHERE {" AND ".join(where)}
        ORDER BY bm25_score ASC
        LIMIT ?
        """

        params.append(int(top_k))
        cur = self.conn.cursor()
        try:
            cur.execute(sql, tuple(params))
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if "fts5" in msg and "syntax" in msg:
                raise ValueError("Invalid search query") from exc
            if "no such table" in msg:
                raise RuntimeError(
                    "Search index is not initialized; rebuild the index"
                ) from exc
            raise RuntimeError("Search index error") from exc
        rows = cur.fetchall()

        hits: List[SearchHit] = []
        for (
            bm25_score,
            snippet,
            path,
            line_start,
            entry_id,
            tier,
            scope,
            created_at,
            meta_json,
            content,
        ) in rows:
            try:
                meta = json.loads(meta_json) if meta_json else {}
                if not isinstance(meta, dict):
                    meta = {}
            except Exception:
                meta = {}
            clean_snippet = _clean_index_snippet(snippet, content, meta)
            if not clean_snippet:
                continue

            score = float(-bm25_score) if isinstance(bm25_score, (int, float)) else 0.0
            hits.append(
                SearchHit(
                    score=score,
                    snippet=clean_snippet,
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
