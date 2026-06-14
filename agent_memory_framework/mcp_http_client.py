from dataclasses import dataclass
from typing import Dict, Optional

from agent_memory_framework.mcp_base import BaseMCPClient
from agent_memory_framework.mcp_compat import streamable_http_transport


@dataclass(frozen=True)
class HttpMCPServerConfig:
    url: str
    headers: Optional[Dict[str, str]] = None
    timeout_s: float = 30.0


class StreamableHttpMCPClient(BaseMCPClient):
    """MCP client that communicates via HTTP with streamable transport."""

    def __init__(self, server: HttpMCPServerConfig):
        self._server = server

    async def _with_session(self, fn):
        from mcp.client.session import ClientSession

        async with streamable_http_transport(
            url=self._server.url,
            headers=self._server.headers,
            timeout_s=self._server.timeout_s,
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)
