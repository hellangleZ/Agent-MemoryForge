from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


_SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password)")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._\-]+)")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_PASSWORD_VALUE_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|api[_-]?key|token|secret)\s*[:=]\s*([^\s,;]+)"
)


def redact(value: Any, *, max_len: int = 5000) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value

    if isinstance(value, str):
        s = value
        s = _BEARER_RE.sub("Bearer [REDACTED]", s)
        s = _OPENAI_KEY_RE.sub("[REDACTED]", s)
        s = _PASSWORD_VALUE_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", s)
        if len(s) > max_len:
            s = s[:max_len] + "…"
        return s

    if isinstance(value, list):
        return [redact(v, max_len=max_len) for v in value]
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and _SECRET_KEY_RE.search(k):
                out[k] = "[REDACTED]"
            else:
                out[k] = redact(v, max_len=max_len)
        return out

    return redact(str(value), max_len=max_len)


@dataclass(frozen=True)
class AuditEvent:
    ts_s: float
    tenant_id: str
    workspace_id: str
    actor: str
    action: str
    resource: str
    ok: bool
    detail: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class MetricPoint:
    ts_s: float
    tenant_id: str
    workspace_id: str
    name: str
    value: float
    tags: Dict[str, str]


class InMemoryObservabilityStore:
    def __init__(self, *, max_events: int = 5000, max_metrics: int = 5000) -> None:
        self._max_events = max_events
        self._max_metrics = max_metrics
        self._audit: List[AuditEvent] = []
        self._metrics: List[MetricPoint] = []

    def record_audit(self, event: AuditEvent) -> None:
        self._audit.append(event)
        if len(self._audit) > self._max_events:
            self._audit = self._audit[-self._max_events :]

    def record_metric(self, point: MetricPoint) -> None:
        self._metrics.append(point)
        if len(self._metrics) > self._max_metrics:
            self._metrics = self._metrics[-self._max_metrics :]

    def query_audit(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        limit: int = 200,
        action: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> List[AuditEvent]:
        items = [
            e
            for e in self._audit
            if e.tenant_id == tenant_id and e.workspace_id == workspace_id
        ]
        if action:
            items = [e for e in items if e.action == action]
        if actor:
            items = [e for e in items if e.actor == actor]
        items = items[-max(1, int(limit)) :]
        return list(reversed(items))

    def query_audit_all(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        action: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> List[AuditEvent]:
        items = [
            e
            for e in self._audit
            if e.tenant_id == tenant_id and e.workspace_id == workspace_id
        ]
        if action:
            items = [e for e in items if e.action == action]
        if actor:
            items = [e for e in items if e.actor == actor]
        return list(reversed(items))

    def query_metrics(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        limit: int = 500,
        name: Optional[str] = None,
    ) -> List[MetricPoint]:
        items = [
            m
            for m in self._metrics
            if m.tenant_id == tenant_id and m.workspace_id == workspace_id
        ]
        if name:
            items = [m for m in items if m.name == name]
        items = items[-max(1, int(limit)) :]
        return list(reversed(items))


class RedisObservabilityStore:
    def __init__(
        self,
        *,
        redis_client,
        audit_key: str = "agent_gateway:audit",
        metric_key: str = "agent_gateway:metrics",
        max_events: int = 50000,
        max_metrics: int = 50000,
    ) -> None:
        self._redis = redis_client
        self._audit_key = audit_key
        self._metric_key = metric_key
        self._max_events = max(1, int(max_events))
        self._max_metrics = max(1, int(max_metrics))

    @staticmethod
    def _decode(raw: Any) -> str:
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return str(raw)

    def _push(self, key: str, payload: Dict[str, Any], *, max_items: int) -> None:
        pipe = self._redis.pipeline(transaction=True)
        pipe.rpush(key, json.dumps(payload, ensure_ascii=False))
        pipe.ltrim(key, -int(max_items), -1)
        pipe.execute()

    def record_audit(self, event: AuditEvent) -> None:
        self._push(self._audit_key, asdict(event), max_items=self._max_events)

    def record_metric(self, point: MetricPoint) -> None:
        self._push(self._metric_key, asdict(point), max_items=self._max_metrics)

    def _audit_items(self, *, limit: Optional[int] = None) -> List[AuditEvent]:
        n = max(1, int(limit or self._max_events))
        rows = self._redis.lrange(self._audit_key, -n, -1) or []
        out: List[AuditEvent] = []
        for raw in rows:
            try:
                data = json.loads(self._decode(raw))
                out.append(AuditEvent(**data))
            except Exception:
                continue
        return out

    def _metric_items(self, *, limit: Optional[int] = None) -> List[MetricPoint]:
        n = max(1, int(limit or self._max_metrics))
        rows = self._redis.lrange(self._metric_key, -n, -1) or []
        out: List[MetricPoint] = []
        for raw in rows:
            try:
                data = json.loads(self._decode(raw))
                out.append(MetricPoint(**data))
            except Exception:
                continue
        return out

    def query_audit(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        limit: int = 200,
        action: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> List[AuditEvent]:
        items = [
            e
            for e in self._audit_items(limit=max(limit * 5, limit))
            if e.tenant_id == tenant_id and e.workspace_id == workspace_id
        ]
        if action:
            items = [e for e in items if e.action == action]
        if actor:
            items = [e for e in items if e.actor == actor]
        items = items[-max(1, int(limit)) :]
        return list(reversed(items))

    def query_audit_all(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        action: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> List[AuditEvent]:
        items = [
            e
            for e in self._audit_items()
            if e.tenant_id == tenant_id and e.workspace_id == workspace_id
        ]
        if action:
            items = [e for e in items if e.action == action]
        if actor:
            items = [e for e in items if e.actor == actor]
        return list(reversed(items))

    def query_metrics(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        limit: int = 500,
        name: Optional[str] = None,
    ) -> List[MetricPoint]:
        items = [
            m
            for m in self._metric_items(limit=max(limit * 5, limit))
            if m.tenant_id == tenant_id and m.workspace_id == workspace_id
        ]
        if name:
            items = [m for m in items if m.name == name]
        items = items[-max(1, int(limit)) :]
        return list(reversed(items))


def now_s() -> float:
    return time.time()


def log_structured_event(
    logger: logging.Logger,
    event: str,
    *,
    level: str = "info",
    **fields: Any,
) -> None:
    """Emit a redacted JSON event to normal container logs.

    Redis audit/metrics remain the queryable source of truth. This helper gives
    operators enough evidence in ordinary Docker logs without exposing raw user
    prompts, memory snippets, or credentials.
    """

    payload = redact({"event": event, "ts_s": now_s(), **fields})
    message = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    log_fn = getattr(logger, level, None)
    if not callable(log_fn):
        log_fn = logger.info
    log_fn("agent_memory.event %s", message)
