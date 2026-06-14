from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol


class MCPClient(Protocol):
    def list_tools(self) -> List[Dict[str, Any]]: ...

    def list_resources(self) -> List[Dict[str, Any]]: ...

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any: ...

    def read_resource(self, uri: str) -> Any: ...


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    category: str = "mcp"


@dataclass(frozen=True)
class MCPResource:
    uri: str
    name: Optional[str] = None
    description: Optional[str] = None
    mime_type: Optional[str] = None


def _tool_parameters_from_input_schema(input_schema: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(input_schema, dict):
        return {"type": "object", "properties": {}}
    if input_schema.get("type"):
        return input_schema
    # Degrade gracefully for slightly-nonconformant payloads.
    return {"type": "object", "properties": dict(input_schema)}


def normalize_mcp_tools(payload: Any) -> List[MCPTool]:
    """Normalize MCP tool listings to a stable internal format.

    Expected input shape is similar to:
    - [{"name": "foo", "description": "...", "inputSchema": {...}}, ...]
    """

    if payload is None:
        return []
    if isinstance(payload, dict) and "tools" in payload:
        payload = payload["tools"]

    if not isinstance(payload, list):
        return []

    tools: List[MCPTool] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        description = str(raw.get("description") or "").strip()
        input_schema = raw.get("inputSchema") or raw.get("input_schema") or {}
        tools.append(
            MCPTool(
                name=name,
                description=description,
                input_schema=_tool_parameters_from_input_schema(input_schema),
                category=str(raw.get("category") or "mcp"),
            )
        )
    return tools


def normalize_mcp_resources(payload: Any) -> List[MCPResource]:
    """Normalize MCP resource listings to a stable internal format."""

    if payload is None:
        return []
    if isinstance(payload, dict) and "resources" in payload:
        payload = payload["resources"]
    if not isinstance(payload, list):
        return []

    resources: List[MCPResource] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        uri = str(raw.get("uri") or "").strip()
        if not uri:
            continue
        resources.append(
            MCPResource(
                uri=uri,
                name=(
                    str(raw.get("name")).strip()
                    if raw.get("name") is not None
                    else None
                ),
                description=(
                    str(raw.get("description")).strip()
                    if raw.get("description") is not None
                    else None
                ),
                mime_type=(
                    str(raw.get("mimeType")).strip()
                    if raw.get("mimeType") is not None
                    else None
                ),
            )
        )
    return resources


def register_mcp_tools(
    *, registry: Any, client: MCPClient, namespace: str = "mcp"
) -> None:
    """Register MCP tools into a ToolRegistry-like object.

    The registry is expected to support `register(name, func, schema, category=...)`.
    """

    tools = normalize_mcp_tools(client.list_tools())
    for tool in tools:
        tool_name = f"{namespace}.{tool.name}" if namespace else tool.name

        def _make_call(name: str) -> Callable[..., Any]:
            def _call(**kwargs: Any) -> Any:
                return client.call_tool(name, kwargs)

            return _call

        registry.register(
            name=tool_name,
            func=_make_call(tool.name),
            category=tool.category,
            schema={
                "description": tool.description or f"MCP tool: {tool.name}",
                "parameters": tool.input_schema,
            },
        )


def format_mcp_resources_for_context(
    resources: List[MCPResource], *, max_items: int = 20
) -> str:
    if not resources:
        return ""

    chunks = ["## MCP Resources"]
    for res in resources[:max_items]:
        label = res.name or res.uri
        line = f"- {label} ({res.uri})"
        if res.mime_type:
            line += f" [{res.mime_type}]"
        chunks.append(line)
    if len(resources) > max_items:
        chunks.append(f"- ... ({len(resources) - max_items} more)")
    return "\n".join(chunks)
