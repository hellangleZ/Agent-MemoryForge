from __future__ import annotations

from typing import Any, Dict, List

from agent_memory_framework.context import ContextAssembler
from agent_memory_framework.mcp import (
    normalize_mcp_resources,
    normalize_mcp_tools,
    register_mcp_tools,
)
from agent_memory_framework.tools import ToolRegistry


class FakeMCPClient:
    def __init__(self):
        self.tool_calls: List[Dict[str, Any]] = []

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "echo",
                "description": "Echo back args",
                "inputSchema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            }
        ]

    def list_resources(self) -> List[Dict[str, Any]]:
        return [
            {"uri": "file:///README.md", "name": "README", "mimeType": "text/markdown"}
        ]

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        self.tool_calls.append({"name": name, "arguments": arguments})
        return {"ok": True, "name": name, "arguments": arguments}

    def read_resource(self, uri: str) -> Any:
        return {"uri": uri, "content": "hello"}


def test_normalize_mcp_tools_and_register_executes():
    client = FakeMCPClient()
    tools = normalize_mcp_tools(client.list_tools())
    assert [t.name for t in tools] == ["echo"]
    assert tools[0].input_schema["type"] == "object"

    registry = ToolRegistry()
    register_mcp_tools(registry=registry, client=client, namespace="mcp")
    assert registry.get("mcp.echo") is not None

    result = registry.execute("mcp.echo", text="hi")
    assert result["ok"] is True
    assert client.tool_calls == [{"name": "echo", "arguments": {"text": "hi"}}]


def test_normalize_mcp_resources_and_context_listing_injected():
    resources = normalize_mcp_resources(
        [
            {"uri": "file:///README.md", "name": "README", "mimeType": "text/markdown"},
            {"uri": "mem://foo"},
        ]
    )
    assert [r.uri for r in resources] == ["file:///README.md", "mem://foo"]

    assembler = ContextAssembler.minimal()

    # Avoid touching MemoryManager/ContextBuilder paths: use system+history minimal and list injection.
    messages = assembler.build_with_mcp_resources(
        user_query="hi",
        conversation_history=[{"role": "user", "content": "hi"}],
        system_prompt="sys",
        mcp_resources=[{"uri": "file:///README.md", "name": "README"}],
    )

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "sys"
    # The injected MCP listing should appear as a system message.
    assert any(
        m.get("role") == "system" and "## MCP Resources" in (m.get("content") or "")
        for m in messages
    )
