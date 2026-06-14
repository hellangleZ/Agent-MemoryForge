"""Tool registry (SDK core).

This is the single source of truth for the agent tool registry. It lives in the
framework SDK so the runtime/product layers depend on the SDK (and not the
reverse).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from utils.exceptions import LLMClientError
from utils.logging_config import get_logger

logger = get_logger(__name__)


class ToolRegistry:
    """Registry of tools available to an agent.

    A tool is a callable plus an OpenAI-style JSON schema describing its
    parameters. Tools are grouped by a free-form ``category`` label.
    """

    def __init__(self) -> None:
        self.tools: Dict[str, Dict[str, Any]] = {}
        logger.debug("ToolRegistry initialized")

    def register(
        self,
        name: str,
        func: Callable,
        schema: Dict[str, Any],
        category: str = "general",
    ) -> None:
        """Register a tool by name.

        Args:
            name: Unique tool name.
            func: Callable invoked when the tool is executed.
            schema: OpenAI-format parameter schema.
            category: Optional grouping label.
        """
        self.tools[name] = {"function": func, "schema": schema, "category": category}
        logger.debug("Registered tool: %s", name)

    def get(self, name: str) -> Optional[Callable]:
        """Return the callable for ``name`` (or ``None``)."""
        tool = self.tools.get(name)
        return tool["function"] if tool else None

    def get_schema(self, name: str) -> Optional[Dict[str, Any]]:
        """Return the schema for ``name`` (or ``None``)."""
        tool = self.tools.get(name)
        return tool["schema"] if tool else None

    def list_tools(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """List registered tools, optionally filtered by ``category``."""
        return [
            {"name": name, **tool["schema"]}
            for name, tool in self.tools.items()
            if category is None or tool["category"] == category
        ]

    def execute(self, name: str, **kwargs: Any) -> Any:
        """Execute a registered tool.

        Raises:
            LLMClientError: if the tool is missing or raises during execution.
        """
        tool = self.tools.get(name)
        if not tool:
            raise LLMClientError(
                f"Tool not found: {name}",
                details={"available_tools": list(self.tools.keys())},
            )

        try:
            result = tool["function"](**kwargs)
            logger.debug("Tool %s executed successfully", name)
            return result
        except Exception as exc:
            logger.error("Tool %s execution failed: %s", name, exc)
            raise LLMClientError(
                f"Tool execution failed: {name}",
                details={"error": str(exc), "kwargs": kwargs},
            ) from exc


__all__ = ["ToolRegistry"]
