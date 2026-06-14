import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from agent_memory_framework.mcp_base import BaseMCPClient
from agent_memory_framework.mcp_compat import stdio_transport

_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class StdioMCPServerConfig:
    command: str
    args: List[str]
    env: Optional[Dict[str, str]] = None
    cwd: Optional[str] = None


class StdioMCPClient(BaseMCPClient):
    """MCP client that communicates via stdio with a subprocess."""

    def __init__(self, server: StdioMCPServerConfig):
        self._server = server

    async def _with_session(self, fn):
        from mcp.client.session import ClientSession

        async with stdio_transport(
            command=self._server.command,
            args=list(self._server.args),
            env=self._server.env,
            cwd=self._server.cwd,
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _expand_env_refs(
    value: str,
    *,
    source: Mapping[str, str],
    missing: List[str],
) -> str:
    def _replace(match: re.Match[str]) -> str:
        env_name = match.group(1).strip()
        env_value = source.get(env_name, "")
        if env_value:
            return env_value
        missing.append(env_name)
        return ""

    return _ENV_REF_RE.sub(_replace, value)


def resolve_mcp_server_env(
    server: Mapping[str, Any],
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> Tuple[Optional[Dict[str, str]], List[str]]:
    """Resolve a server env block without storing secrets in MCP JSON.

    `env` holds literal non-secret values. Values like `${TOKEN_NAME}` are
    expanded from the process environment. `env_from` copies optional variables
    from the process environment. `required_env` copies variables and reports
    missing names so callers can skip unauthenticated servers cleanly.
    """

    source = os.environ if environ is None else environ
    resolved: Dict[str, str] = {}
    missing: List[str] = []

    raw_env = server.get("env") or {}
    if isinstance(raw_env, Mapping):
        for key, value in raw_env.items():
            name = str(key).strip()
            if not name or value is None:
                continue
            text = str(value)
            if _ENV_REF_RE.search(text):
                resolved[name] = _expand_env_refs(
                    text, source=source, missing=missing
                )
            else:
                resolved[name] = text

    for env_name in _string_list(server.get("env_from")):
        env_value = source.get(env_name, "")
        if env_value:
            resolved[env_name] = env_value

    for env_name in _string_list(server.get("required_env")):
        env_value = source.get(env_name, "")
        if env_value:
            resolved[env_name] = env_value
        else:
            missing.append(env_name)

    return (resolved or None), sorted(set(missing))


def resolve_mcp_server_args(
    server: Mapping[str, Any],
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> Tuple[List[str], List[str]]:
    """Resolve command arguments with optional `${ENV_NAME}` placeholders."""

    source = os.environ if environ is None else environ
    missing: List[str] = []
    resolved = [
        _expand_env_refs(str(arg), source=source, missing=missing)
        for arg in _string_list(server.get("args"))
    ]
    return resolved, sorted(set(missing))


def resolve_mcp_server_headers(
    server: Mapping[str, Any],
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> Tuple[Optional[Dict[str, str]], List[str]]:
    """Resolve HTTP MCP headers with optional `${ENV_NAME}` placeholders."""

    raw_headers = server.get("headers") or {}
    if not isinstance(raw_headers, Mapping):
        return None, []

    source = os.environ if environ is None else environ
    missing: List[str] = []
    resolved: Dict[str, str] = {}
    for key, value in raw_headers.items():
        name = str(key).strip()
        if not name or value is None:
            continue
        resolved[name] = _expand_env_refs(str(value), source=source, missing=missing)
    return (resolved or None), sorted(set(missing))


def stdio_mcp_client_from_env(*, env_var: str = "AGENT_MEMORY_MCP_STDIO") -> StdioMCPClient:
    raw_text = os.environ.get(env_var, "").strip()
    if not raw_text:
        raise ValueError(
            f"Missing {env_var}. Provide JSON like: "
            f"{{\"command\":\"python\",\"args\":[\"-m\",\"agent_memory_mcp_server\"]}}"
        )

    raw = json.loads(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid {env_var}: expected JSON object")

    args, missing_args = resolve_mcp_server_args(raw)
    env, missing_env = resolve_mcp_server_env(raw)
    missing = sorted(set(missing_args + missing_env))
    if missing:
        raise ValueError(f"Invalid {env_var}: missing required environment variables: {', '.join(missing)}")

    server = StdioMCPServerConfig(
        command=str(raw.get("command") or "").strip(),
        args=args,
        env=env,
        cwd=str(raw.get("cwd")).strip() if raw.get("cwd") else None,
    )
    if not server.command:
        raise ValueError(f"Invalid {env_var}: missing 'command'")
    return StdioMCPClient(server)


def mcp_servers_from_env(*, env_var: str = "AGENT_MEMORY_MCP_SERVERS") -> List[Dict[str, Any]]:
    """Load multi-server MCP config from env.

    Expected JSON:
    [{"name":"local","transport":"stdio","namespace":"local","command":"python","args":["-m","agent_memory_mcp_server"]},
     {"name":"third","transport":"http","namespace":"third","url":"http://127.0.0.1:8002/mcp"}]
    """

    raw_text = os.environ.get(env_var, "").strip()
    if not raw_text:
        return []
    raw = json.loads(raw_text)
    if not isinstance(raw, list):
        raise ValueError(f"Invalid {env_var}: expected JSON list")
    out: List[Dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out


def mcp_servers_from_file(path: str) -> List[Dict[str, Any]]:
    """Load multi-server MCP config from a JSON file.

    File format matches `AGENT_MEMORY_MCP_SERVERS` payload (a JSON list).
    """

    raw_text = open(path, "r", encoding="utf-8").read().strip()
    if not raw_text:
        return []
    raw = json.loads(raw_text)
    if not isinstance(raw, list):
        raise ValueError(f"Invalid MCP config file {path}: expected JSON list")
    out: List[Dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out


def mcp_servers_from_settings() -> List[Dict[str, Any]]:
    """Optional bridge: build a single stdio MCP server from env vars.

    Reads ``MCP_ENABLED`` / ``MCP_STDIO_COMMAND`` / ``MCP_STDIO_ARGS`` /
    ``MCP_NAMESPACE`` directly so the SDK stays self-contained (no dependency on
    a product-level pydantic settings module).
    """

    def _enabled(value: Optional[str]) -> bool:
        if value is None:
            return True
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}

    if not _enabled(os.getenv("MCP_ENABLED")):
        return []

    command = (os.getenv("MCP_STDIO_COMMAND") or "").strip()
    args_text = (os.getenv("MCP_STDIO_ARGS") or "").strip()
    namespace = (os.getenv("MCP_NAMESPACE") or "mcp").strip() or "mcp"

    if not command:
        return []

    args = args_text.split() if args_text else []
    return [
        {
            "name": "default",
            "transport": "stdio",
            "namespace": namespace,
            "command": command,
            "args": args,
        }
    ]
