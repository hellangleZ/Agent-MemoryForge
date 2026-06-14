from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol


class MemoryTier(str, Enum):
    """Normalized memory tiers.

    These tiers are stable across backends; adapters can map to a concrete
    service's internal taxonomy.
    """

    stm = "stm"
    wm = "wm"
    preferences = "preferences"
    semantic = "semantic"


class MemoryScope(str, Enum):
    """High-level scope for memory records."""

    user = "user"
    repo = "repo"
    project = "project"
    team = "team"


@dataclass(frozen=True)
class MemoryProvenance:
    source: str
    trace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    raw: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.raw is None:
            object.__setattr__(self, "raw", {})


@dataclass(frozen=True)
class MemoryRef:
    tenant_id: str
    workspace_id: str
    scope: MemoryScope
    user_id: Optional[str] = None
    repo_id: Optional[str] = None
    project_id: Optional[str] = None
    team_id: Optional[str] = None


@dataclass(frozen=True)
class MemoryRecord:
    tier: MemoryTier
    ref: MemoryRef
    content: str
    record_id: Optional[str] = None
    metadata: Dict[str, Any] = None  # type: ignore[assignment]
    score: Optional[float] = None
    provenance: Optional[MemoryProvenance] = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


@dataclass(frozen=True)
class MemoryQuery:
    tier: MemoryTier
    ref: MemoryRef
    query: str
    top_k: int = 5


class MemoryStore(Protocol):
    """Framework memory interface.

    Implementations MUST enforce tenant/workspace scoping.
    """

    def store(self, record: MemoryRecord) -> MemoryRecord: ...

    def retrieve(self, query: MemoryQuery) -> List[MemoryRecord]: ...
