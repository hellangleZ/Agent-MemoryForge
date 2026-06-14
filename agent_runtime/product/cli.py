from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Dict, Optional

from agent_runtime.product.agent_registry import load_product_agent


def _load_agent_class(agent_name_or_spec: str):
    """Load an Agent class by registry name or explicit module spec.

    The gateway historically depended on a product CLI module to resolve agent
    identifiers. We keep that seam but delegate implementation to the stable
    product agent registry used by the gateway.
    """

    return load_product_agent(agent_name_or_spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Product CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    parser.add_argument(
        "--gateway-url",
        default=os.getenv("AGENT_GATEWAY_URL", "http://127.0.0.1:8080"),
        help="Base URL for agent gateway control plane",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("AGENT_GATEWAY_API_KEY"),
        help="Gateway API key for x-api-key header",
    )
    parser.add_argument(
        "--auth-token",
        default=os.getenv("AGENT_GATEWAY_AUTH_TOKEN"),
        help="Bearer token for Authorization header",
    )
    parser.add_argument(
        "--workspace-id",
        default=os.getenv("AGENT_GATEWAY_WORKSPACE_ID"),
        help="Workspace id for x-workspace-id header",
    )

    status_p = sub.add_parser("full-chain-status", help="Show running full-chain process status")
    status_p.add_argument("--local", action="store_true", help="Use local process manager instead of gateway")

    stop_p = sub.add_parser("full-chain-stop", help="Stop running full-chain processes")
    stop_p.add_argument("--local", action="store_true", help="Use local process manager instead of gateway")

    logs_p = sub.add_parser("full-chain-logs", help="Print last N lines of a service log")
    logs_p.add_argument("service", help="Service name (memory_service|gateway|distill_worker)")
    logs_p.add_argument("--tail", type=int, default=200)
    logs_p.add_argument("--local", action="store_true", help="Use local process manager instead of gateway")

    logs_stream_p = sub.add_parser(
        "full-chain-logs-stream",
        help="Stream service logs (SSE via gateway; local fallback prints tail)",
    )
    logs_stream_p.add_argument("service", help="Service name (memory_service|gateway|distill_worker)")
    logs_stream_p.add_argument("--tail", type=int, default=50)
    logs_stream_p.add_argument("--interval-s", type=float, default=0.25)
    logs_stream_p.add_argument("--max-events", type=int, default=0)
    logs_stream_p.add_argument("--local", action="store_true", help="Use local process manager instead of gateway")

    deps_p = sub.add_parser("full-chain-deps", help="Show dependency probe results")
    deps_p.add_argument("--local", action="store_true", help="No-op locally; always uses gateway")

    services_p = sub.add_parser("full-chain-services", help="List known service names")
    services_p.add_argument("--local", action="store_true", help="Use local process manager instead of gateway")

    start_p = sub.add_parser("full-chain-start", help="Start services via gateway")
    start_p.add_argument("--memory-port", type=int, default=8001)
    start_p.add_argument("--gateway-port", type=int, default=8080)
    start_p.add_argument("--memory-url", default="http://127.0.0.1:8001")
    start_p.add_argument("--start-distill-worker", action="store_true")
    start_p.add_argument("--verbose", action="store_true")
    start_p.add_argument("--restart", action="store_true")
    start_p.add_argument(
        "--no-deps",
        action="store_true",
        help="Disable dependency gating (require_dependencies_healthy=false)",
    )

    ns = parser.parse_args(argv)
    def _headers() -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if getattr(ns, "api_key", None):
            headers["x-api-key"] = str(ns.api_key)
        if getattr(ns, "auth_token", None):
            headers["authorization"] = f"Bearer {str(ns.auth_token)}"
        if getattr(ns, "workspace_id", None):
            headers["x-workspace-id"] = str(ns.workspace_id)
        return headers

    def _gateway_get_json(path: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        import requests

        url = str(getattr(ns, "gateway_url")).rstrip("/") + path
        resp = requests.get(url, headers=_headers(), params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("gateway returned non-object json")
        return data

    def _gateway_get_stream(
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
    ):
        import requests

        url = str(getattr(ns, "gateway_url")).rstrip("/") + path
        resp = requests.get(url, headers=_headers(), params=params, timeout=30, stream=True)
        resp.raise_for_status()
        return resp

    def _gateway_post_json(path: str, *, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        import requests

        url = str(getattr(ns, "gateway_url")).rstrip("/") + path
        resp = requests.post(url, headers=_headers(), json=payload or {}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("gateway returned non-object json")
        return data

    def _local_manager():
        from agent_runtime.product.full_chain_manager import FullChainManager

        repo_root = Path(__file__).resolve().parents[2]
        return FullChainManager(repo_root=repo_root)

    if ns.cmd == "full-chain-status":
        if getattr(ns, "local", False):
            running = _local_manager().status()
            if not running:
                print("no running services")
                return 0
            for name, info in running.items():
                print(f"{name}\tpid={info.pid}\tlog={info.log_path or '-'}")
            return 0

        data = _gateway_get_json("/v1/full-chain/status")
        items = (data.get("data") if isinstance(data, dict) else None) or {}
        if not items:
            print("no running services")
            return 0
        for name, info in items.items():
            pid = (info or {}).get("pid") if isinstance(info, dict) else None
            log_path = (info or {}).get("log_path") if isinstance(info, dict) else None
            print(f"{name}\tpid={pid}\tlog={log_path or '-'}")
        return 0

    if ns.cmd == "full-chain-stop":
        if getattr(ns, "local", False):
            _local_manager().stop_all()
            print("stopped")
            return 0

        _gateway_post_json("/v1/full-chain/stop")
        print("stopped")
        return 0

    if ns.cmd == "full-chain-logs":
        if not hasattr(ns, "service"):
            raise SystemExit("missing service")
        service = str(getattr(ns, "service"))
        tail = int(getattr(ns, "tail", 200))
        if getattr(ns, "local", False):
            manager = _local_manager()
            log_path = manager.logs_path(service)
            if not log_path or not log_path.exists():
                raise SystemExit("no logs for service")
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-tail:]:
                print(line)
            return 0

        data = _gateway_get_json("/v1/full-chain/logs", params={"service": service, "tail": tail})
        lines = (((data.get("data") or {}) if isinstance(data, dict) else {}) or {}).get("lines")
        if not isinstance(lines, list):
            raise SystemExit("no logs for service")
        for line in lines:
            print(line)
        return 0

    if ns.cmd == "full-chain-logs-stream":
        if not hasattr(ns, "service"):
            raise SystemExit("missing service")
        service = str(getattr(ns, "service"))
        tail = int(getattr(ns, "tail", 50))
        if getattr(ns, "local", False):
            manager = _local_manager()
            log_path = manager.logs_path(service)
            if not log_path or not log_path.exists():
                raise SystemExit("no logs for service")
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-tail:]:
                print(line)
            return 0

        interval_s = float(getattr(ns, "interval_s", 0.25))
        max_events = int(getattr(ns, "max_events", 0))
        resp = _gateway_get_stream(
            "/v1/full-chain/logs/stream",
            params={
                "service": service,
                "tail": tail,
                "interval_s": interval_s,
                "max_events": max_events,
            },
        )

        # SSE: lines look like "data: ..." or "event: ..."; we only print data payload.
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = str(raw)
            if line.startswith("data: "):
                print(line[len("data: ") :])
            elif line.startswith("event: error"):
                print(line)
        return 0

    if ns.cmd == "full-chain-deps":
        data = _gateway_get_json("/v1/full-chain/dependencies")
        deps = (((data.get("data") or {}) if isinstance(data, dict) else {}) or {}).get("dependencies")
        if not isinstance(deps, dict):
            raise SystemExit("no dependency data")
        for name, info in deps.items():
            if not isinstance(info, dict):
                continue
            ok = info.get("ok")
            detail = info.get("detail")
            extra = f" ({detail})" if detail else ""
            print(f"{name}\tok={ok}{extra}")
        return 0

    if ns.cmd == "full-chain-services":
        if getattr(ns, "local", False):
            for name in _local_manager().known_services():
                print(name)
            return 0
        data = _gateway_get_json("/v1/full-chain/services")
        services = (((data.get("data") or {}) if isinstance(data, dict) else {}) or {}).get("services")
        if not isinstance(services, list):
            raise SystemExit("no services")
        for name in services:
            print(name)
        return 0

    if ns.cmd == "full-chain-start":
        payload = {
            "memory_port": int(getattr(ns, "memory_port", 8001)),
            "gateway_port": int(getattr(ns, "gateway_port", 8080)),
            "memory_url": str(getattr(ns, "memory_url", "http://127.0.0.1:8001")),
            "verbose": bool(getattr(ns, "verbose", False)),
            "start_distill_worker": bool(getattr(ns, "start_distill_worker", False)),
            "restart": bool(getattr(ns, "restart", False)),
            "require_dependencies_healthy": not bool(getattr(ns, "no_deps", False)),
        }
        data = _gateway_post_json("/v1/full-chain/start", payload=payload)
        items = (data.get("data") if isinstance(data, dict) else None) or {}
        for name, info in items.items():
            pid = (info or {}).get("pid") if isinstance(info, dict) else None
            log_path = (info or {}).get("log_path") if isinstance(info, dict) else None
            print(f"{name}\tpid={pid}\tlog={log_path or '-'}")
        return 0
    raise SystemExit(f"Unknown command: {ns.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
