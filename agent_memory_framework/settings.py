from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class Settings:
    """Framework settings.

    Kept intentionally small; callers can pass extra configuration via `extras`.
    """

    max_tool_turns: int = 4
    extras: Dict[str, Any] = field(default_factory=dict)
