from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class MemoryPolicy:
    stm_max_summaries: int = 15
    stm_ttl_s: int = 1800
    stm_relevance_threshold: float = 0.3
    stm_top_k: int = 5
    wm_max_size: int = 20
    wm_ttl_s: int = 7 * 24 * 3600

    semantic_top_k: int = 5

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "MemoryPolicy":
        def _get(name: str, default: Any) -> Any:
            return config.get(name, default)

        return cls(
            stm_max_summaries=int(_get("stm_max_summaries", cls.stm_max_summaries)),
            stm_ttl_s=int(_get("stm_ttl", cls.stm_ttl_s)),
            stm_relevance_threshold=float(
                _get("stm_relevance_threshold", cls.stm_relevance_threshold)
            ),
            stm_top_k=int(_get("stm_top_k", cls.stm_top_k)),
            wm_max_size=int(_get("wm_max_size", cls.wm_max_size)),
            wm_ttl_s=int(_get("wm_ttl_s", cls.wm_ttl_s)),
            semantic_top_k=int(_get("semantic_top_k", cls.semantic_top_k)),
        )
