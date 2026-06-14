from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, Mapping, Optional


@dataclass(frozen=True)
class TraceSpan:
    name: str
    started_at_s: float
    ended_at_s: float
    ok: bool
    attributes: Dict[str, Any]

    @property
    def duration_ms(self) -> float:
        return max(0.0, (self.ended_at_s - self.started_at_s) * 1000.0)


class TraceCollector:
    """Small, backend-agnostic trace collector.

    Designed to be used by Agent/MultiAgentRuntime and optionally exported.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._spans: list[TraceSpan] = []

    def record(
        self,
        name: str,
        *,
        started_at_s: float,
        ended_at_s: float,
        ok: bool,
        attributes: Optional[Mapping[str, Any]] = None,
    ) -> None:
        span = TraceSpan(
            name=name,
            started_at_s=started_at_s,
            ended_at_s=ended_at_s,
            ok=ok,
            attributes=dict(attributes or {}),
        )
        with self._lock:
            self._spans.append(span)

    def as_dict(self) -> Dict[str, Any]:
        with self._lock:
            spans = list(self._spans)
        return {
            "spans": [
                {
                    "name": s.name,
                    "started_at_s": s.started_at_s,
                    "ended_at_s": s.ended_at_s,
                    "duration_ms": s.duration_ms,
                    "ok": s.ok,
                    "attributes": s.attributes,
                }
                for s in spans
            ]
        }


class trace_span:
    def __init__(
        self, collector: Optional[TraceCollector], name: str, **attributes: Any
    ) -> None:
        self._collector = collector
        self._name = name
        self._attributes = attributes
        self._started_at_s = 0.0
        self._ok = True

    def __enter__(self):
        self._started_at_s = time.time()
        return self

    def __exit__(self, exc_type, exc, tb):
        ended = time.time()
        self._ok = exc is None
        if self._collector is not None:
            self._collector.record(
                self._name,
                started_at_s=self._started_at_s,
                ended_at_s=ended,
                ok=self._ok,
                attributes=self._attributes,
            )
        return False
