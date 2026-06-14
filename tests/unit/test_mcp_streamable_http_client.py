import socket
import threading
import time

import pytest
import uvicorn

from agent_memory_framework.mcp_http_client import (
    HttpMCPServerConfig,
    StreamableHttpMCPClient,
)


def require_mcp_runtime() -> None:
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
    except Exception as exc:
        pytest.skip(f"optional mcp runtime unavailable: {exc}")


@pytest.mark.unit
def test_streamable_http_client_lists_tools() -> None:
    require_mcp_runtime()
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(host="127.0.0.1", port=0)

    @mcp.tool()
    def ping(text: str) -> str:
        return f"pong:{text}"

    app = mcp.streamable_http_app()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    port = sock.getsockname()[1]

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="on",
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()

    deadline = time.time() + 5
    while not server.started and time.time() < deadline:
        time.sleep(0.05)

    assert server.started, "uvicorn server did not start"

    client = StreamableHttpMCPClient(
        HttpMCPServerConfig(url=f"http://127.0.0.1:{port}/mcp")
    )
    tools = client.list_tools()
    assert any(t.get("name") == "ping" for t in tools)

    server.should_exit = True
    thread.join(timeout=5)

    try:
        sock.close()
    except OSError:
        pass
