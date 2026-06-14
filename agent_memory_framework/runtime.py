from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional

from agent_memory_lib import MemoryClient

from agent_memory_framework.llm import LLMProvider
from agent_memory_framework.settings import Settings
from agent_memory_framework.trace import TraceCollector, trace_span


@dataclass
class Runtime:
    agent_id: str
    user_id: str
    memory_client: MemoryClient
    llm_provider: LLMProvider
    conversation_id: str
    settings: Settings
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    trace: Optional[TraceCollector] = None

    def trace_root(self, name: str = "runtime", **attributes: Any):
        """Create a root trace span with runtime metadata.

        This is a convenience helper so callers can consistently attach core
        identifiers (agent/user/conversation/request/trace) to traces.
        """

        base = {
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
        }
        base.update(attributes)
        return trace_span(self.trace, name, **base)

    @property
    def config(self) -> Mapping[str, Any]:
        """Return an immutable view of the runtime configuration."""
        return MappingProxyType({
            "max_tool_turns": self.settings.max_tool_turns,
            **self.settings.extras
        })
