from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from utils.logging_config import get_logger


logger = get_logger(__name__)


def graph_enabled(default: bool = False) -> bool:
    val = os.getenv("AGENT_MEMORY_GRAPH_ENABLED")
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class GraphEdge:
    tenant_id: str
    workspace_id: str
    scope: str
    subject: str
    relation: str
    obj: str
    entry_id: str
    source_path: str
    source_line: int


def _normalize_term(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _validated_edge(edge: GraphEdge) -> Optional[GraphEdge]:
    subject = _normalize_term(edge.subject)
    relation = _normalize_term(edge.relation)
    obj = _normalize_term(edge.obj)
    source_path = _normalize_term(edge.source_path).replace("\\", "/")

    if not (subject and relation and obj):
        return None
    for name, value in (("subject", subject), ("relation", relation), ("obj", obj)):
        if "\n" in value or "\r" in value:
            logger.warning("graph edge %s contains newline; skipping", name)
            return None
        if len(value) > 512:
            logger.warning("graph edge %s too long; skipping", name)
            return None
    if not source_path:
        return None

    return GraphEdge(
        tenant_id=str(edge.tenant_id),
        workspace_id=str(edge.workspace_id),
        scope=str(edge.scope),
        subject=subject,
        relation=relation,
        obj=obj,
        entry_id=str(edge.entry_id),
        source_path=source_path,
        source_line=int(edge.source_line),
    )


def _rel_id(edge: GraphEdge) -> str:
    raw = "|".join(
        [
            edge.tenant_id,
            edge.workspace_id,
            edge.scope,
            edge.subject,
            edge.relation,
            edge.obj,
            edge.source_path,
            str(int(edge.source_line)),
            edge.entry_id,
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class Neo4jGraphWriter:
    """Optional derived graph index.

    This is a derived index only; Markdown is the source of truth.
    """

    def __init__(self, *, uri: str, user: str, password: str) -> None:
        try:
            from neo4j import GraphDatabase  # type: ignore
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "Missing optional dependency 'neo4j' required for graph index. "
                "Install via: python -m pip install -e '.[gateway]'"
            ) from exc

        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        try:
            self._driver.close()
        except Exception:
            return

    def upsert_edge(self, edge: GraphEdge) -> None:
        rel_id = _rel_id(edge)
        cypher = """
        MERGE (s:Entity {tenant_id:$tenant_id, workspace_id:$workspace_id, scope:$scope, name:$subject})
        MERGE (o:Entity {tenant_id:$tenant_id, workspace_id:$workspace_id, scope:$scope, name:$obj})
        MERGE (s)-[r:REL {tenant_id:$tenant_id, workspace_id:$workspace_id, scope:$scope, rel_id:$rel_id}]->(o)
        SET r.predicate=$relation, r.entry_id=$entry_id, r.source_path=$source_path, r.source_line=$source_line
        """
        params = {
            "tenant_id": edge.tenant_id,
            "workspace_id": edge.workspace_id,
            "scope": edge.scope,
            "subject": edge.subject,
            "relation": edge.relation,
            "obj": edge.obj,
            "entry_id": edge.entry_id,
            "source_path": edge.source_path,
            "source_line": int(edge.source_line),
            "rel_id": rel_id,
        }
        with self._driver.session() as session:
            session.run(cypher, params)


def best_effort_upsert(
    *,
    cfg: Dict[str, Any],
    edge: GraphEdge,
) -> None:
    if not graph_enabled(default=False):
        return

    validated = _validated_edge(edge)
    if validated is None:
        return

    uri = str(cfg.get("neo4j_uri") or "").strip()
    user = str(cfg.get("neo4j_user") or "").strip()
    password = str(cfg.get("neo4j_password") or "").strip()

    if not (uri and user and password):
        logger.warning("graph enabled but neo4j config missing; skipping")
        return

    writer = None
    try:
        writer = Neo4jGraphWriter(uri=uri, user=user, password=password)
        writer.upsert_edge(validated)
    except Exception:
        logger.exception("neo4j upsert failed; continuing (derived index)")
    finally:
        if writer is not None:
            writer.close()
