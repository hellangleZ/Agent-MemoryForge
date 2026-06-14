from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from agent_memory_lib.text_processing import estimate_tokens


def now_s() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def current_usage_month(ts_s: Optional[float] = None) -> str:
    dt = (
        datetime.fromtimestamp(float(ts_s), tz=timezone.utc)
        if ts_s is not None
        else datetime.now(timezone.utc)
    )
    return dt.strftime("%Y-%m")


def _normalize_month(month: Optional[str], ts_s: Optional[float] = None) -> str:
    raw = str(month or "").strip()
    if raw:
        try:
            datetime.strptime(raw, "%Y-%m")
        except ValueError as exc:
            raise ValueError("month must use YYYY-MM") from exc
        return raw
    return current_usage_month(ts_s)


def estimate_message_tokens(messages: Iterable[Any]) -> int:
    total = 0
    for raw in messages or []:
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump(exclude_none=True)
        if not isinstance(raw, dict):
            total += estimate_tokens(str(raw))
            continue
        role = str(raw.get("role") or "")
        content = raw.get("content")
        if isinstance(content, (dict, list)):
            content_text = json.dumps(content, ensure_ascii=False, sort_keys=True)
        else:
            content_text = str(content or "")
        total += estimate_tokens(role) + estimate_tokens(content_text) + 1
    return max(0, int(total))


@dataclass(frozen=True)
class UsageEvent:
    id: str
    ts_s: float
    month: str
    tenant_id: str
    workspace_id: str
    user_id: str
    agent_id: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    status: str
    trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuotaRecord:
    tenant_id: str
    workspace_id: str
    user_id: str
    monthly_token_quota: int
    enabled: bool
    updated_at: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    blocked: bool
    used_tokens: int
    estimated_tokens: int
    monthly_token_quota: Optional[int]
    remaining_tokens: Optional[int]
    quota_enabled: bool
    month: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UsageSummary:
    tenant_id: str
    workspace_id: str
    user_id: str
    month: str
    request_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    monthly_token_quota: Optional[int]
    quota_enabled: bool
    remaining_tokens: Optional[int]
    blocked: bool
    updated_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SQLiteUsageStore:
    def __init__(self, *, db_path: str) -> None:
        self._db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                  id TEXT PRIMARY KEY,
                  ts_s REAL NOT NULL,
                  month TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  workspace_id TEXT NOT NULL,
                  user_id TEXT NOT NULL,
                  agent_id TEXT NOT NULL,
                  model TEXT NOT NULL,
                  input_tokens INTEGER NOT NULL,
                  output_tokens INTEGER NOT NULL,
                  total_tokens INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  trace_id TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_usage_events_scope_month
                  ON usage_events(tenant_id, workspace_id, user_id, month);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_usage_events_tenant_month_scope
                  ON usage_events(tenant_id, month, workspace_id, user_id);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_quotas (
                  tenant_id TEXT NOT NULL,
                  workspace_id TEXT NOT NULL,
                  user_id TEXT NOT NULL,
                  monthly_token_quota INTEGER NOT NULL,
                  enabled INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  PRIMARY KEY (tenant_id, workspace_id, user_id)
                );
                """
            )

    def record_usage(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        user_id: str,
        agent_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        status: str,
        trace_id: Optional[str] = None,
        month: Optional[str] = None,
        ts_s: Optional[float] = None,
    ) -> UsageEvent:
        event_ts = float(ts_s if ts_s is not None else now_s())
        usage_month = _normalize_month(month, event_ts)
        input_count = max(0, int(input_tokens or 0))
        output_count = max(0, int(output_tokens or 0))
        event = UsageEvent(
            id=uuid.uuid4().hex,
            ts_s=event_ts,
            month=usage_month,
            tenant_id=str(tenant_id),
            workspace_id=str(workspace_id),
            user_id=str(user_id),
            agent_id=str(agent_id or ""),
            model=str(model or ""),
            input_tokens=input_count,
            output_tokens=output_count,
            total_tokens=input_count + output_count,
            status=str(status or "success"),
            trace_id=str(trace_id) if trace_id else None,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_events(
                  id, ts_s, month, tenant_id, workspace_id, user_id, agent_id,
                  model, input_tokens, output_tokens, total_tokens, status, trace_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event.id,
                    event.ts_s,
                    event.month,
                    event.tenant_id,
                    event.workspace_id,
                    event.user_id,
                    event.agent_id,
                    event.model,
                    event.input_tokens,
                    event.output_tokens,
                    event.total_tokens,
                    event.status,
                    event.trace_id,
                ),
            )
        return event

    def set_quota(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        user_id: str,
        monthly_token_quota: int,
        enabled: bool = True,
    ) -> QuotaRecord:
        quota = QuotaRecord(
            tenant_id=str(tenant_id),
            workspace_id=str(workspace_id),
            user_id=str(user_id),
            monthly_token_quota=max(0, int(monthly_token_quota or 0)),
            enabled=bool(enabled),
            updated_at=now_s(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_quotas(
                  tenant_id, workspace_id, user_id, monthly_token_quota, enabled, updated_at
                ) VALUES (?,?,?,?,?,?)
                ON CONFLICT(tenant_id, workspace_id, user_id)
                DO UPDATE SET
                  monthly_token_quota=excluded.monthly_token_quota,
                  enabled=excluded.enabled,
                  updated_at=excluded.updated_at
                """,
                (
                    quota.tenant_id,
                    quota.workspace_id,
                    quota.user_id,
                    quota.monthly_token_quota,
                    1 if quota.enabled else 0,
                    quota.updated_at,
                ),
            )
        return quota

    def get_quota(
        self, *, tenant_id: str, workspace_id: str, user_id: str
    ) -> Optional[QuotaRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT tenant_id, workspace_id, user_id, monthly_token_quota, enabled, updated_at
                  FROM usage_quotas
                 WHERE tenant_id=? AND workspace_id=? AND user_id=?
                """,
                (tenant_id, workspace_id, user_id),
            ).fetchone()
        return self._quota_from_row(row) if row else None

    def list_quotas(
        self,
        *,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[QuotaRecord]:
        query = [
            """
            SELECT tenant_id, workspace_id, user_id, monthly_token_quota, enabled, updated_at
              FROM usage_quotas
             WHERE tenant_id=?
            """
        ]
        args: List[Any] = [tenant_id]
        if workspace_id:
            query.append("AND workspace_id=?")
            args.append(workspace_id)
        if user_id:
            query.append("AND user_id=?")
            args.append(user_id)
        query.append("ORDER BY workspace_id ASC, user_id ASC")
        with self._connect() as conn:
            rows = conn.execute(" ".join(query), args).fetchall()
        return [self._quota_from_row(row) for row in rows]

    def delete_quotas_for_user(self, *, tenant_id: str, user_id: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM usage_quotas WHERE tenant_id=? AND user_id=?",
                (tenant_id, user_id),
            )
        return int(cur.rowcount or 0)

    def get_month_usage(
        self, *, tenant_id: str, workspace_id: str, user_id: str, month: Optional[str]
    ) -> int:
        usage_month = _normalize_month(month)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(total_tokens), 0) AS total_tokens
                  FROM usage_events
                 WHERE tenant_id=? AND workspace_id=? AND user_id=? AND month=?
                """,
                (tenant_id, workspace_id, user_id, usage_month),
            ).fetchone()
        return int(row["total_tokens"] or 0) if row else 0

    def check_quota(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        user_id: str,
        estimated_tokens: int,
        month: Optional[str] = None,
    ) -> QuotaDecision:
        usage_month = _normalize_month(month)
        quota = self.get_quota(
            tenant_id=tenant_id, workspace_id=workspace_id, user_id=user_id
        )
        used = self.get_month_usage(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            user_id=user_id,
            month=usage_month,
        )
        estimate = max(0, int(estimated_tokens or 0))
        if quota is None or not quota.enabled:
            return QuotaDecision(
                allowed=True,
                blocked=False,
                used_tokens=used,
                estimated_tokens=estimate,
                monthly_token_quota=quota.monthly_token_quota if quota else None,
                remaining_tokens=None,
                quota_enabled=False,
                month=usage_month,
            )

        remaining = max(0, quota.monthly_token_quota - used)
        blocked = used >= quota.monthly_token_quota or estimate > remaining
        return QuotaDecision(
            allowed=not blocked,
            blocked=blocked,
            used_tokens=used,
            estimated_tokens=estimate,
            monthly_token_quota=quota.monthly_token_quota,
            remaining_tokens=remaining,
            quota_enabled=True,
            month=usage_month,
        )

    def list_usage_summary(
        self,
        *,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        user_id: Optional[str] = None,
        month: Optional[str] = None,
    ) -> List[UsageSummary]:
        usage_month = _normalize_month(month)
        query = [
            """
            SELECT tenant_id, workspace_id, user_id, month,
                   COUNT(*) AS request_count,
                   COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens
              FROM usage_events
             WHERE tenant_id=? AND month=?
            """
        ]
        args: List[Any] = [tenant_id, usage_month]
        if workspace_id:
            query.append("AND workspace_id=?")
            args.append(workspace_id)
        if user_id:
            query.append("AND user_id=?")
            args.append(user_id)
        query.append("GROUP BY tenant_id, workspace_id, user_id, month")
        with self._connect() as conn:
            rows = conn.execute(" ".join(query), args).fetchall()

        by_key: Dict[tuple[str, str], Dict[str, Any]] = {}
        for row in rows:
            key = (str(row["workspace_id"]), str(row["user_id"]))
            by_key[key] = {
                "tenant_id": str(row["tenant_id"]),
                "workspace_id": str(row["workspace_id"]),
                "user_id": str(row["user_id"]),
                "month": str(row["month"]),
                "request_count": int(row["request_count"] or 0),
                "input_tokens": int(row["input_tokens"] or 0),
                "output_tokens": int(row["output_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
            }

        quota_map = {
            (q.workspace_id, q.user_id): q
            for q in self.list_quotas(
                tenant_id=tenant_id, workspace_id=workspace_id, user_id=user_id
            )
        }
        for key, quota in quota_map.items():
            by_key.setdefault(
                key,
                {
                    "tenant_id": quota.tenant_id,
                    "workspace_id": quota.workspace_id,
                    "user_id": quota.user_id,
                    "month": usage_month,
                    "request_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
            )

        out: List[UsageSummary] = []
        for key, values in by_key.items():
            quota = quota_map.get(key)
            total = int(values["total_tokens"])
            quota_limit = quota.monthly_token_quota if quota else None
            quota_enabled = bool(quota and quota.enabled)
            remaining = (
                max(0, int(quota_limit or 0) - total) if quota_enabled else None
            )
            blocked = bool(quota_enabled and quota_limit is not None and total >= quota_limit)
            out.append(
                UsageSummary(
                    tenant_id=str(values["tenant_id"]),
                    workspace_id=str(values["workspace_id"]),
                    user_id=str(values["user_id"]),
                    month=str(values["month"]),
                    request_count=int(values["request_count"]),
                    input_tokens=int(values["input_tokens"]),
                    output_tokens=int(values["output_tokens"]),
                    total_tokens=total,
                    monthly_token_quota=quota_limit,
                    quota_enabled=quota_enabled,
                    remaining_tokens=remaining,
                    blocked=blocked,
                    updated_at=quota.updated_at if quota else None,
                )
            )
        return sorted(out, key=lambda item: (item.workspace_id, item.user_id))

    @staticmethod
    def _quota_from_row(row: sqlite3.Row) -> QuotaRecord:
        return QuotaRecord(
            tenant_id=str(row["tenant_id"]),
            workspace_id=str(row["workspace_id"]),
            user_id=str(row["user_id"]),
            monthly_token_quota=int(row["monthly_token_quota"]),
            enabled=bool(int(row["enabled"])),
            updated_at=int(row["updated_at"]),
        )
