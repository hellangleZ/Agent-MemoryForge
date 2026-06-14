"""Base class for MCP clients with common implementation."""
from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, List, Protocol

import anyio

from agent_memory_framework.mcp import MCPClient


class SessionFunction(Protocol):
    """Protocol for functions that operate on an MCP session."""
    async def __call__(self, session: Any) -> Any: ...


class BaseMCPClient(MCPClient):
    """Base class for MCP clients with common method implementations.

    Subclasses must implement `_with_session` to handle transport-specific
    session management.
    """

    @abstractmethod
    async def _with_session(self, fn: SessionFunction) -> Any:
        """Execute a function within an MCP session context.

        Args:
            fn: Async function that takes a ClientSession and returns a result.

        Returns:
            The result of the function execution.
        """
        ...

    def _run_async(self, fn: SessionFunction) -> Any:
        """Run an async function in anyio event loop."""
        return anyio.run(lambda: self._with_session(fn))

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all available tools from the MCP server."""
        async def _list(session: Any) -> List[Dict[str, Any]]:
            result = await session.list_tools()
            return [t.model_dump() for t in result.tools]

        return self._run_async(_list)

    def list_resources(self) -> List[Dict[str, Any]]:
        """List all available resources from the MCP server."""
        async def _list(session: Any) -> List[Dict[str, Any]]:
            result = await session.list_resources()
            return [r.model_dump() for r in result.resources]

        return self._run_async(_list)

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on the MCP server."""
        async def _call(session: Any) -> Any:
            result = await session.call_tool(name, arguments)
            return result.model_dump()

        return self._run_async(_call)

    def read_resource(self, uri: str) -> Any:
        """Read a resource from the MCP server."""
        async def _read(session: Any) -> Any:
            from pydantic import TypeAdapter

            from mcp.types import AnyUrl

            parsed = TypeAdapter(AnyUrl).validate_python(uri)
            result = await session.read_resource(parsed)
            return result.model_dump()

        return self._run_async(_read)


__all__ = ["BaseMCPClient"]
