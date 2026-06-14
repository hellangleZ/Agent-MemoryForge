from __future__ import annotations

import os

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional, Type

from agent_memory_framework.agent import Agent
from agent_memory_framework.mcp import MCPClient
from agent_memory_framework.mcp import register_mcp_tools
from agent_memory_framework.tools import ToolRegistry


@dataclass(frozen=True)
class DiscoveredAgent:
    key: str
    spec: str
    cls: Type[Agent]

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "spec": self.spec,
            "module": self.cls.__module__,
            "class_name": self.cls.__name__,
            "doc": (self.cls.__doc__ or "").strip() or None,
        }


@dataclass(frozen=True)
class DiscoveredTool:
    name: str
    category: str
    schema: Dict[str, Any]
    spec: str
    func: Callable[..., Any]

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "schema": self.schema,
            "spec": self.spec,
        }


def load_object_from_spec(spec: str) -> Any:
    """Load a Python object based on `module:AttrName` spec."""
    if ":" not in spec:
        raise ValueError("Invalid spec; expected 'module:AttrName'")
    module_name, attr_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def load_agent_class_from_spec(spec: str) -> Type[Agent]:
    obj = load_object_from_spec(spec)
    if not isinstance(obj, type) or not issubclass(obj, Agent):
        raise TypeError(f"{spec} is not an Agent subclass")
    return obj


def load_agent_spec(name_or_spec: str) -> Type[Agent]:
    """Load an Agent class by registry name or explicit module spec."""

    discovered = discover_agents()
    if name_or_spec in discovered:
        return load_agent_class_from_spec(discovered[name_or_spec].spec)
    return load_agent_class_from_spec(name_or_spec)


def _iter_modules(package_name: str) -> Iterable[str]:
    package = importlib.import_module(package_name)
    if not getattr(package, "__path__", None):
        return []
    for modinfo in pkgutil.iter_modules(package.__path__):
        yield f"{package_name}.{modinfo.name}"


def _default_agent_key(module_basename: str) -> str:
    if module_basename == "minimal_demo":
        return "pm-minimal"
    return module_basename.replace("_agent", "").replace("_", "-")


def discover_agents(
    package: str = "agent_runtime.product.templates",
    *,
    predicate: Optional[Callable[[Type[Agent]], bool]] = None,
) -> Dict[str, DiscoveredAgent]:
    """Discover `Agent` subclasses in a package.

    Keys are stable and derived from module basename (e.g. `code_assistant`
    -> `code-assistant`). The `spec` is always `module:ClassName`.
    """

    discovered: Dict[str, DiscoveredAgent] = {}
    for module_name in _iter_modules(package):
        module_basename = module_name.rsplit(".", 1)[-1]
        module = importlib.import_module(module_name)

        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if not isinstance(obj, type) or not issubclass(obj, Agent) or obj is Agent:
                continue
            if obj is Agent or obj is type or obj is object:
                continue
            if obj.__module__ != module.__name__:
                continue
            if predicate and not predicate(obj):
                continue

            # Prefer the module attribute name for stable specs,
            # since aliases can share the same underlying class.
            spec = f"{obj.__module__}:{attr_name}"
            key = _default_agent_key(module_basename)
            discovered.setdefault(key, DiscoveredAgent(key=key, spec=spec, cls=obj))

    return discovered


def discover_tools_from_mcp(
    client: MCPClient,
    *,
    namespace: str = "mcp",
) -> Dict[str, DiscoveredTool]:
    """Discover tools from an MCP server.

    Keys are tool names with namespace applied.
    """

    discovered: Dict[str, DiscoveredTool] = {}
    payload = client.list_tools()
    if isinstance(payload, dict) and "tools" in payload:
        payload = payload["tools"]
    if not isinstance(payload, list):
        return discovered

    for raw in payload:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        description = str(raw.get("description") or "").strip()
        input_schema = raw.get("inputSchema") or raw.get("input_schema") or {}
        category = str(raw.get("category") or namespace).strip() or namespace
        schema = {
            "description": description or f"MCP tool: {name}",
            "parameters": input_schema if isinstance(input_schema, dict) else {},
        }

        def _make_call(tool_name: str):
            def _call(**kwargs: Any) -> Any:
                return client.call_tool(tool_name, kwargs)

            return _call

        namespaced_name = f"{namespace}.{name}" if namespace else name

        discovered.setdefault(
            namespaced_name,
            DiscoveredTool(
                name=namespaced_name,
                category=category,
                schema=schema,
                spec=f"mcp:{name}",
                func=_make_call(name),
            ),
        )

    return discovered


def discover_tools() -> Dict[str, DiscoveredTool]:
    """Discover tools from the default local MCP server.

    The filesystem plugin system has been removed. This function discovers
    tools from the default local MCP server.
    """

    from agent_memory_framework.mcp_http_client import (
        HttpMCPServerConfig,
        StreamableHttpMCPClient,
    )
    from agent_memory_framework.mcp_stdio_client import (
        resolve_mcp_server_args,
        resolve_mcp_server_env,
        resolve_mcp_server_headers,
        mcp_servers_from_env,
        mcp_servers_from_settings,
        stdio_mcp_client_from_env,
    )

    servers = mcp_servers_from_env() or mcp_servers_from_settings()
    if not servers:
        # No multi-server config. Only fall back to a single stdio server when one is
        # explicitly configured via AGENT_MEMORY_MCP_STDIO; otherwise return no tools
        # gracefully instead of raising (callers like the portal must not 500 when MCP
        # is absent).
        if not os.environ.get("AGENT_MEMORY_MCP_STDIO", "").strip():
            return {}
        client = stdio_mcp_client_from_env()
        return discover_tools_from_mcp(client, namespace="mcp")

    discovered: Dict[str, DiscoveredTool] = {}
    for server in servers:
        transport = str(server.get("transport") or "").strip().lower()
        namespace = str(server.get("namespace") or "mcp").strip() or "mcp"

        if transport == "stdio":
            from agent_memory_framework.mcp_stdio_client import (
                StdioMCPClient,
                StdioMCPServerConfig,
            )

            args, missing_args = resolve_mcp_server_args(server)
            env, missing_env = resolve_mcp_server_env(server)
            if missing_args or missing_env:
                continue
            client = StdioMCPClient(
                StdioMCPServerConfig(
                    command=str(server.get("command") or "").strip(),
                    args=args,
                    env=env,
                    cwd=str(server.get("cwd")).strip() if server.get("cwd") else None,
                )
            )
            discovered.update(discover_tools_from_mcp(client, namespace=namespace))
        elif transport in {"http", "streamable-http", "streamable_http"}:
            url = str(server.get("url") or "").strip()
            if not url:
                continue
            headers, missing_headers = resolve_mcp_server_headers(server)
            if missing_headers:
                continue
            timeout_s = server.get("timeout_s")
            client = StreamableHttpMCPClient(
                HttpMCPServerConfig(
                    url=url,
                    headers=headers,
                    timeout_s=float(timeout_s) if timeout_s is not None else 30.0,
                )
            )
            discovered.update(discover_tools_from_mcp(client, namespace=namespace))
        else:
            continue

    return discovered


def discover_tools_grouped() -> Dict[str, Dict[str, DiscoveredTool]]:
    """Discover tools grouped by namespace.

    Returns a mapping like:
    {
      "local": {"local.calculate_budget": DiscoveredTool(...), ...},
      "third": {"third.search": DiscoveredTool(...), ...},
    }
    """

    tools = discover_tools()
    grouped: Dict[str, Dict[str, DiscoveredTool]] = {}
    for name, tool in tools.items():
        namespace = name.split(".", 1)[0] if "." in name else "mcp"
        grouped.setdefault(namespace, {})[name] = tool
    return grouped


def register_discovered_tools(
    registry: ToolRegistry, tools: Dict[str, DiscoveredTool]
) -> None:
    for tool in tools.values():
        registry.register(
            name=tool.name,
            func=tool.func,
            schema=tool.schema,
            category=tool.category,
        )


def register_mcp_tools_into_registry(
    registry: ToolRegistry,
    client: MCPClient,
    *,
    namespace: str = "mcp",
) -> None:
    register_mcp_tools(registry=registry, client=client, namespace=namespace)
