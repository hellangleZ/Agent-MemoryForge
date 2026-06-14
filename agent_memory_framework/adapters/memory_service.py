from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent_memory_lib import MemoryClient

from agent_memory_framework.memory import (
    MemoryProvenance,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryStore,
    MemoryTier,
)
from agent_memory_framework.feature_flags import enable_scoping


def _scope_filter_fields(scope: MemoryScope) -> Dict[str, Any]:
    return {"scope": scope.value}


def _scoped_id(*, tenant_id: str, workspace_id: str, raw_id: str) -> str:
    prefix = f"t:{tenant_id}:ws:{workspace_id}:"
    if raw_id.startswith(prefix):
        return raw_id
    return prefix + raw_id


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


@dataclass
class MemoryServiceStore(MemoryStore):
    """Adapter for the canonical memory service API.

    The underlying service is user-centric; this adapter injects tenant/workspace
    metadata and always filters retrieval by these dimensions.
    """

    client: MemoryClient
    default_trace_id: Optional[str] = None

    def store(self, record: MemoryRecord) -> MemoryRecord:
        if enable_scoping(default=True) is False:
            raise RuntimeError(
                "Memory scoping is disabled (AGENT_MEMORY_ENABLE_SCOPING=0). "
                "Refusing to store to avoid cross-tenant/workspace leakage. "
                "Set AGENT_MEMORY_ENABLE_SCOPING=1 to re-enable."
            )

        params: Dict[str, Any] = {
            "tenant_id": record.ref.tenant_id,
            "workspace_id": record.ref.workspace_id,
            **_scope_filter_fields(record.ref.scope),
            **record.metadata,
        }

        if record.ref.user_id is not None:
            params["user_id"] = record.ref.user_id
        if record.ref.repo_id is not None:
            params["repo_id"] = record.ref.repo_id
        if record.ref.project_id is not None:
            params["project_id"] = record.ref.project_id
        if record.ref.team_id is not None:
            params["team_id"] = record.ref.team_id

        if record.tier is MemoryTier.preferences:
            key = params.pop("key", None) or record.metadata.get("key")
            if not key:
                raise ValueError("preferences tier requires metadata['key']")
            value = params.pop("value", None)
            if value is None and "value" in record.metadata:
                value = record.metadata["value"]
            if value is None:
                raise ValueError("preferences tier requires metadata['value']")
            response = self.client.store_ltm_preference(
                user_id=record.ref.user_id or "", key=str(key), value=value
            )
        elif record.tier is MemoryTier.stm:
            conv_id = params.pop(
                "conversation_id", record.metadata.get("conversation_id")
            )
            round_id = params.pop("round_id", record.metadata.get("round_id"))
            summary = params.pop("summary", record.content)
            if not conv_id or round_id is None:
                raise ValueError(
                    "stm tier requires metadata['conversation_id'] and metadata['round_id']"
                )
            response = self.client.store_stm(
                conversation_id=_scoped_id(
                    tenant_id=record.ref.tenant_id,
                    workspace_id=record.ref.workspace_id,
                    raw_id=str(conv_id),
                ),
                round_id=int(round_id),
                summary=str(summary),
            )
        elif record.tier is MemoryTier.wm:
            task_id = params.pop("task_id", record.metadata.get("task_id"))
            state = params.pop("state", record.metadata.get("state"))
            if not task_id or state is None:
                raise ValueError(
                    "wm tier requires metadata['task_id'] and metadata['state']"
                )
            response = self.client.store_wm(
                user_id=record.ref.user_id or "",
                task_id=_scoped_id(
                    tenant_id=record.ref.tenant_id,
                    workspace_id=record.ref.workspace_id,
                    raw_id=str(task_id),
                ),
                state=state,
            )
        else:
            response = self.client.memory_write(
                tier=record.tier.value,
                scope=record.ref.scope.value,
                content=record.content,
                metadata=params,
                tenant_id=record.ref.tenant_id,
                workspace_id=record.ref.workspace_id,
            )

        record_id = None
        if isinstance(response.get("data"), dict):
            record_id = response["data"].get("entry_id") or response["data"].get("id")

        provenance = record.provenance or MemoryProvenance(
            source="memory_service",
            trace_id=self.default_trace_id,
            raw={"response": response},
        )
        if provenance.created_at is None:
            object.__setattr__(provenance, "created_at", datetime.now(timezone.utc))

        return MemoryRecord(
            tier=record.tier,
            ref=record.ref,
            content=record.content,
            record_id=record_id,
            metadata=record.metadata,
            score=record.score,
            provenance=provenance,
        )

    def retrieve(self, query: MemoryQuery) -> List[MemoryRecord]:
        if enable_scoping(default=True) is False:
            raise RuntimeError(
                "Memory scoping is disabled (AGENT_MEMORY_ENABLE_SCOPING=0). "
                "Refusing to retrieve to avoid cross-tenant/workspace leakage. "
                "Set AGENT_MEMORY_ENABLE_SCOPING=1 to re-enable."
            )

        params: Dict[str, Any] = {
            "tenant_id": query.ref.tenant_id,
            "workspace_id": query.ref.workspace_id,
            **_scope_filter_fields(query.ref.scope),
        }
        if query.ref.user_id is not None:
            params["user_id"] = query.ref.user_id
        if query.ref.repo_id is not None:
            params["repo_id"] = query.ref.repo_id
        if query.ref.project_id is not None:
            params["project_id"] = query.ref.project_id
        if query.ref.team_id is not None:
            params["team_id"] = query.ref.team_id

        if query.tier is MemoryTier.preferences:
            key = query.query
            response = self.client.retrieve_ltm_preference(
                user_id=query.ref.user_id or "", key=str(key)
            )
            if response is None:
                return []
            return [
                MemoryRecord(
                    tier=query.tier,
                    ref=query.ref,
                    content=str(response),
                    metadata={"key": key, "value": response},
                    provenance=MemoryProvenance(
                        source="memory_service", trace_id=self.default_trace_id
                    ),
                )
            ]

        if query.tier is MemoryTier.stm:
            response = self.client.retrieve_stm(
                conversation_id=_scoped_id(
                    tenant_id=query.ref.tenant_id,
                    workspace_id=query.ref.workspace_id,
                    raw_id=str(query.query),
                ),
                last_k=query.top_k,
            )
            items = response.get("data", []) if isinstance(response, dict) else []
        elif query.tier is MemoryTier.wm:
            response = self.client.retrieve_wm(
                user_id=query.ref.user_id or "",
                task_id=_scoped_id(
                    tenant_id=query.ref.tenant_id,
                    workspace_id=query.ref.workspace_id,
                    raw_id=str(query.query),
                ),
            )
            if response.get("status") != "success":
                return []
            state = response.get("data")
            items = [{"state": state}] if state is not None else []
        else:
            response = self.client.memory_search(
                query=query.query,
                top_k=query.top_k,
                tiers=[query.tier.value],
                scopes=[query.ref.scope.value],
                tenant_id=query.ref.tenant_id,
                workspace_id=query.ref.workspace_id,
            )
            data = response.get("data", {}) if isinstance(response, dict) else {}
            items = data.get("hits", []) if isinstance(data, dict) else []

        records: List[MemoryRecord] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            content_obj = item.get("content")
            if isinstance(content_obj, dict):
                content_obj = content_obj.get("snippet")
            content = str(
                content_obj
                or item.get("snippet")
                or item.get("summary")
                or item.get("text")
                or ""
            )
            score = item.get("score")
            created = _parse_datetime(item.get("created_at") or item.get("timestamp"))
            records.append(
                MemoryRecord(
                    tier=query.tier,
                    ref=query.ref,
                    content=content,
                    record_id=str(item.get("id"))
                    if item.get("id") is not None
                    else None,
                    metadata=item,
                    score=float(score) if isinstance(score, (int, float)) else None,
                    provenance=MemoryProvenance(
                        source="memory_service",
                        trace_id=self.default_trace_id,
                        created_at=created,
                        raw={"item": item},
                    ),
                )
            )
        return records
