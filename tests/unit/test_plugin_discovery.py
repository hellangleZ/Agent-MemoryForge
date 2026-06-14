from __future__ import annotations

import pytest

from agent_memory_framework.mcp_stdio_client import (
    StdioMCPClient,
    StdioMCPServerConfig,
    resolve_mcp_server_args,
    resolve_mcp_server_env,
    resolve_mcp_server_headers,
)
from agent_memory_framework.plugins import (
    discover_agents,
    discover_tools_from_mcp,
    load_object_from_spec,
)


def require_mcp_runtime() -> None:
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
    except Exception as exc:
        pytest.skip(f"optional mcp runtime unavailable: {exc}")


def test_discover_agents_finds_templates() -> None:
    agents = discover_agents()
    assert "code-assistant" in agents
    assert agents["code-assistant"].spec.endswith(":CodeAssistantAgent")


def test_load_object_from_spec_roundtrip() -> None:
    agents = discover_agents()
    spec = agents["code-assistant"].spec
    cls = load_object_from_spec(spec)
    assert cls is agents["code-assistant"].cls


def test_discover_tools_from_mcp_local_server() -> None:
    require_mcp_runtime()
    client = StdioMCPClient(
        StdioMCPServerConfig(command="python", args=["-m", "agent_memory_mcp_server"])
    )
    tools = discover_tools_from_mcp(client)
    assert "mcp.calculate_budget" in tools
    assert tools["mcp.calculate_budget"].schema["parameters"].get("type") == "object"


def test_discover_tools_multi_server_env_uses_namespace(monkeypatch) -> None:
    require_mcp_runtime()
    import json as _json
    monkeypatch.setenv("AGENT_MEMORY_MCP_SERVERS", _json.dumps([
        {"name": "local", "transport": "stdio", "namespace": "local",
         "command": "python", "args": ["-m", "agent_memory_mcp_server"]}
    ]))
    from agent_memory_framework.plugins import discover_tools

    tools = discover_tools()
    assert "local.calculate_budget" in tools
    assert tools["local.calculate_budget"].name == "local.calculate_budget"


def test_discover_tools_grouped_splits_by_namespace(monkeypatch) -> None:
    require_mcp_runtime()
    import json as _json
    monkeypatch.setenv("AGENT_MEMORY_MCP_SERVERS", _json.dumps([
        {"name": "local", "transport": "stdio", "namespace": "local",
         "command": "python", "args": ["-m", "agent_memory_mcp_server"]}
    ]))
    from agent_memory_framework.plugins import discover_tools_grouped

    grouped = discover_tools_grouped()
    assert "local" in grouped
    assert "local.calculate_budget" in grouped["local"]


def test_resolve_mcp_server_env_supports_required_env(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "token-for-test")
    env, missing = resolve_mcp_server_env(
        {
            "env": {"STATIC_MODE": "readonly"},
            "env_from": ["OPTIONAL_EMPTY"],
            "required_env": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
        }
    )

    assert missing == []
    assert env == {
        "STATIC_MODE": "readonly",
        "GITHUB_PERSONAL_ACCESS_TOKEN": "token-for-test",
    }


def test_resolve_mcp_server_env_reports_missing_required_env(monkeypatch) -> None:
    monkeypatch.delenv("NOTION_TOKEN", raising=False)

    env, missing = resolve_mcp_server_env({"required_env": ["NOTION_TOKEN"]})

    assert env is None
    assert missing == ["NOTION_TOKEN"]


def test_resolve_mcp_server_env_respects_explicit_empty_environ(monkeypatch) -> None:
    monkeypatch.setenv("NOTION_TOKEN", "process-env-secret")

    env, missing = resolve_mcp_server_env(
        {
            "env": {"STATIC_MODE": "readonly", "TOKEN": "${NOTION_TOKEN}"},
            "required_env": ["NOTION_TOKEN"],
        },
        environ={},
    )

    assert env == {"STATIC_MODE": "readonly", "TOKEN": ""}
    assert missing == ["NOTION_TOKEN"]


def test_resolve_mcp_server_args_expands_env_placeholders(monkeypatch) -> None:
    monkeypatch.setenv("NEON_API_KEY", "neon-key-for-test")

    args, missing = resolve_mcp_server_args(
        {"args": ["start", "${NEON_API_KEY}"]}
    )

    assert missing == []
    assert args == ["start", "neon-key-for-test"]


def test_resolve_mcp_server_args_reports_missing_env(monkeypatch) -> None:
    monkeypatch.delenv("NEON_API_KEY", raising=False)

    args, missing = resolve_mcp_server_args(
        {"args": ["start", "${NEON_API_KEY}"]}
    )

    assert args == ["start", ""]
    assert missing == ["NEON_API_KEY"]


def test_resolve_mcp_server_args_respects_explicit_empty_environ(monkeypatch) -> None:
    monkeypatch.setenv("NEON_API_KEY", "process-env-secret")

    args, missing = resolve_mcp_server_args(
        {"args": ["start", "${NEON_API_KEY}"]},
        environ={},
    )

    assert args == ["start", ""]
    assert missing == ["NEON_API_KEY"]


def test_resolve_mcp_server_headers_expands_env_placeholders(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_ACCESS_TOKEN", "supabase-token-for-test")

    headers, missing = resolve_mcp_server_headers(
        {
            "headers": {
                "Authorization": "Bearer ${SUPABASE_ACCESS_TOKEN}",
            }
        }
    )

    assert missing == []
    assert headers == {"Authorization": "Bearer supabase-token-for-test"}


def test_resolve_mcp_server_headers_reports_missing_env(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_ACCESS_TOKEN", raising=False)

    headers, missing = resolve_mcp_server_headers(
        {
            "headers": {
                "Authorization": "Bearer ${SUPABASE_ACCESS_TOKEN}",
            }
        }
    )

    assert headers == {"Authorization": "Bearer "}
    assert missing == ["SUPABASE_ACCESS_TOKEN"]


def test_resolve_mcp_server_headers_respects_explicit_empty_environ(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_ACCESS_TOKEN", "process-env-secret")

    headers, missing = resolve_mcp_server_headers(
        {
            "headers": {
                "Authorization": "Bearer ${SUPABASE_ACCESS_TOKEN}",
            }
        },
        environ={},
    )

    assert headers == {"Authorization": "Bearer "}
    assert missing == ["SUPABASE_ACCESS_TOKEN"]


def test_pytest_collection_sanity() -> None:
    # Regression guard: this test module should import and run quickly.
    assert True
