from typing import Any, Callable, Dict, Optional

import httpx

McpHttpClientFactory = Callable[..., httpx.AsyncClient]


def httpx_client_factory_with_overrides(
    *,
    extra_headers: Optional[Dict[str, str]] = None,
    timeout_s: Optional[float] = None,
) -> McpHttpClientFactory:
    """Create a MCP-compatible `httpx_client_factory` with optional overrides.

    MCP's `streamablehttp_client` calls this factory with keyword args:
    `headers`, `timeout` and `auth`. We merge headers and optionally override
    the default timeout.
    """

    def _factory(**kwargs: Any) -> httpx.AsyncClient:
        headers = kwargs.pop("headers", None)
        if extra_headers:
            headers = {**(headers or {}), **extra_headers}
        kwargs["headers"] = headers

        if timeout_s is not None:
            kwargs["timeout"] = httpx.Timeout(timeout_s)

        return httpx.AsyncClient(**kwargs)

    return _factory


def streamable_http_transport(
    *,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout_s: float = 30.0,
):
    from mcp.client.streamable_http import streamablehttp_client

    return streamablehttp_client(
        url,
        httpx_client_factory=httpx_client_factory_with_overrides(
            extra_headers=headers,
            timeout_s=timeout_s,
        ),
    )


def stdio_transport(
    *,
    command: str,
    args: list[str],
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
):
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=command,
        args=list(args),
        env=env,
        cwd=cwd,
    )
    return stdio_client(params)
