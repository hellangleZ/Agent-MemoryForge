from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from agent_memory_lib.text_processing import TextProcessor, estimate_tokens

from agent_memory_framework.context import ContextAssembler
from agent_memory_framework.execution_loop import ExecutionLoop
from agent_memory_framework.mcp import MCPClient, register_mcp_tools
from agent_memory_framework.runtime import Runtime
from agent_memory_framework.tools import ToolRegistry
from agent_memory_framework.trace import trace_span
from utils.logging_config import get_logger
from config.constants import MemoryConfig

# NOTE: `MemoryManager` lives in `agent_memory_framework.memory_runtime`. It is
# imported lazily inside `__init__` (not at module top) to keep the top-level
# `import agent_memory_framework` surface light.

# Use constant from config
MAX_HISTORY_SIZE = MemoryConfig.MAX_CONVERSATION_HISTORY


class Agent(ABC):
    def __init__(self, runtime: Runtime):
        from agent_memory_framework.memory_runtime.memory_manager import MemoryManager

        self.runtime = runtime
        self.logger = get_logger(f"agent.{runtime.agent_id}")

        self.tool_registry = ToolRegistry()

        self.memory_store = MemoryManager(
            memory_client=runtime.memory_client,
            user_id=runtime.user_id,
            conversation_id=runtime.conversation_id,
            config=runtime.config,
        )
        self.text_processor = TextProcessor()
        self.context_assembler = ContextAssembler(
            memory_manager=self.memory_store,
            text_processor=self.text_processor,
            config=runtime.config,
        )

        self.execution_loop = ExecutionLoop(
            agent_id=runtime.agent_id,
            llm_call_fn=self._llm_call,
            tool_registry=self.tool_registry,
            config=runtime.config,
        )

        self.register_tools(self.tool_registry)
        self.conversation_history: List[Dict[str, Any]] = []

    @abstractmethod
    def system_prompt(self) -> str: ...

    def system_prompt_override(self) -> str | None:
        return self.runtime.config.get("system_prompt")

    @abstractmethod
    def register_tools(self, registry: ToolRegistry) -> None: ...

    def run_turn(self, user_query: str) -> str:
        with self.runtime.trace_root("agent.turn"):
            return self._run_turn_impl(user_query)

    def _run_turn_impl(self, user_query: str) -> str:
        with trace_span(
            self.runtime.trace, "context.build", agent_id=self.runtime.agent_id
        ):
            messages = self.context_assembler.build(
                user_query=user_query,
                conversation_history=self.conversation_history
                + [{"role": "user", "content": user_query}],
                system_prompt=self.system_prompt_override() or self.system_prompt(),
            )

        self.logger.info(
            "Context messages=%s tokens~%s",
            len(messages),
            estimate_tokens(str(messages)),
            extra={
                "trace_id": self.runtime.trace_id,
                "request_id": self.runtime.request_id,
            },
        )

        with trace_span(self.runtime.trace, "llm.turn", agent_id=self.runtime.agent_id):
            response_text = self.execution_loop.run_single_turn(messages)

        self.conversation_history.append({"role": "user", "content": user_query})
        self.conversation_history.append(
            {"role": "assistant", "content": response_text}
        )
        self._prune_history()
        return response_text

    def _prune_history(self) -> None:
        """Prune conversation history to prevent unbounded growth.

        Keeps the history within MAX_HISTORY_SIZE by removing oldest messages
        while preserving the alternation of user/assistant messages.
        """
        if len(self.conversation_history) > MAX_HISTORY_SIZE:
            # Remove oldest messages, keeping the most recent
            # Ensure we keep paired user/assistant messages
            excess = len(self.conversation_history) - MAX_HISTORY_SIZE
            # Round up to even number to maintain message pairs
            if excess % 2 != 0:
                excess += 1
            self.conversation_history = self.conversation_history[excess:]
            self.logger.debug(
                "Pruned conversation history: removed=%s remaining=%s",
                excess,
                len(self.conversation_history),
            )

    def _llm_call(self, messages: List[Dict[str, Any]]):
        result = self.runtime.llm_provider.generate(
            messages, trace_id=self.runtime.trace_id
        )
        if result.tool_calls:
            return result.raw
        return {
            "choices": [
                {
                    "message": {
                        "content": result.text,
                    }
                }
            ]
        }

    def enable_mcp(self, client: MCPClient, *, namespace: str = "mcp") -> None:
        """Enable MCP tool invocation for this agent.

        Registers all MCP tools into the agent's ToolRegistry under `namespace`.
        """

        register_mcp_tools(
            registry=self.tool_registry, client=client, namespace=namespace
        )


__all__ = ["Agent"]
