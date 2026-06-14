#!/usr/bin/env python3
"""Verify API endpoint accessibility after HTML route removal.

This script tests that all API endpoints required by the Next.js frontend
are still accessible after removing HTML portal routes from agent_gateway.py.

Usage:
    python scripts/verify_api_endpoints.py [--base-url URL]

Examples:
    # Test against default gateway
    python scripts/verify_api_endpoints.py

    # Test against custom endpoint
    python scripts/verify_api_endpoints.py --base-url http://localhost:8080
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from typing import Any

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required. Install with: pip install httpx")
    sys.exit(1)


@dataclass
class EndpointResult:
    """Result of testing a single endpoint."""

    method: str
    path: str
    status_code: int | None
    success: bool
    error: str | None = None

    def __str__(self) -> str:
        status = "✅" if self.success else "❌"
        code = self.status_code or "ERR"
        error_msg = f" - {self.error}" if self.error else ""
        return f"{status} {self.method:6} {self.path} -> {code}{error_msg}"


# Endpoint definitions: (method, path, request_body, requires_auth)
# requires_auth: None = no auth, "admin" = admin credentials, "user" = user credentials
ENDPOINTS: list[tuple[str, str, dict[str, Any] | None, str | None]] = [
    # Health & Status (no auth required)
    ("GET", "/health", None, None),
    ("GET", "/healthz", None, None),
    ("GET", "/readyz", None, None),
    # Authentication (no auth required for login/signup)
    ("POST", "/portal/v1/login", {"username": "admin", "password": "admin"}, None),
    ("POST", "/portal/v1/signup", {"username": "test_user", "password": "test123"}, None),
    # Authenticated endpoints (will test with admin credentials)
    ("GET", "/portal/v1/me", None, "admin"),
    ("POST", "/portal/v1/password/change", {"old_password": "admin", "new_password": "newpass"}, "admin"),
    ("POST", "/portal/v1/token/refresh", None, "admin"),
    ("POST", "/portal/v1/logout", None, "admin"),
    # Workspace Management
    ("GET", "/portal/v1/workspaces", None, "admin"),
    ("GET", "/portal/v1/workspace/config", None, "admin"),
    ("POST", "/portal/v1/workspace/config", {"config": {}}, "admin"),
    ("POST", "/portal/v1/workspace/apply", {}, "admin"),
    # Tools
    ("GET", "/portal/v1/tools", None, "admin"),
    ("GET", "/portal/v1/tools/status", None, "admin"),
    ("GET", "/portal/v1/tools/policy", None, "admin"),
    ("POST", "/portal/v1/tools/policy", {"policy": {}}, "admin"),
    # Agents
    ("GET", "/portal/v1/agents", None, "admin"),
    ("POST", "/portal/v1/agents", {"name": "test-agent", "type": "code-assistant"}, "admin"),
    # Memory
    ("POST", "/portal/v1/memory/retrieve", {"memory_type": "ltm_preference", "params": {}}, "admin"),
    ("GET", "/portal/v1/memory/stats", None, "admin"),
    ("POST", "/v1/memory/retrieve", {"memory_type": "ltm_preference", "params": {}}, "admin"),
    ("POST", "/v1/memory/store", {"memory_type": "ltm_preference", "content": {"key": "test", "value": "test"}}, "admin"),
    # Monitoring
    ("GET", "/portal/v1/monitoring/metrics", None, "admin"),
    ("GET", "/portal/v1/monitoring/audit", None, "admin"),
    ("GET", "/portal/v1/monitoring/metrics/export", None, "admin"),
    ("GET", "/portal/v1/monitoring/audit/export", None, "admin"),
    # Runs
    ("GET", "/v1/runs", None, "admin"),
    ("GET", "/v1/runs/test-trace-id", None, "admin"),
    # Chat
    ("POST", "/v1/chat", {"messages": [{"role": "user", "content": "hello"}]}, "admin"),
    # Full Chain Management
    ("GET", "/v1/full-chain/dependencies", None, None),
    ("GET", "/v1/full-chain/status", None, None),
    ("GET", "/v1/full-chain/services", None, None),
    # Jobs
    ("POST", "/v1/jobs", {"job_type": "test", "payload": {}}, "admin"),
]


async def get_auth_token(client: httpx.AsyncClient, base_url: str) -> str | None:
    """Get authentication token using admin credentials."""
    try:
        resp = await client.post(
            f"{base_url}/portal/v1/login",
            json={"username": "admin", "password": "admin"},
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("access_token")
    except Exception:
        pass
    return None


async def test_endpoint(
    client: httpx.AsyncClient,
    base_url: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    auth_token: str | None,
) -> EndpointResult:
    """Test a single API endpoint."""
    url = f"{base_url}{path}"
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    try:
        if method == "GET":
            resp = await client.get(url, headers=headers)
        elif method == "POST":
            resp = await client.post(url, json=body or {}, headers=headers)
        else:
            return EndpointResult(method, path, None, False, f"Unsupported method: {method}")

        # Consider 2xx and 4xx as "endpoint exists" (5xx is server error, 404 is not found)
        if resp.status_code == 404:
            return EndpointResult(method, path, resp.status_code, False, "Not found")
        if resp.status_code >= 500:
            return EndpointResult(method, path, resp.status_code, False, "Server error")
        return EndpointResult(method, path, resp.status_code, True)
    except httpx.ConnectError:
        return EndpointResult(method, path, None, False, "Connection refused")
    except Exception as e:
        return EndpointResult(method, path, None, False, str(e))


async def verify_endpoints(base_url: str) -> tuple[int, int]:
    """Verify all endpoints and return (success_count, total_count)."""
    print(f"\nVerifying API endpoints at: {base_url}")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Get auth token for authenticated endpoints
        print("Getting auth token...")
        auth_token = await get_auth_token(client, base_url)
        if auth_token:
            print("✅ Auth token obtained\n")
        else:
            print("⚠️  Could not get auth token, will skip authenticated endpoints\n")

        results: list[EndpointResult] = []

        for method, path, body, auth_required in ENDPOINTS:
            token = None
            if auth_required:
                if auth_token:
                    token = auth_token
                else:
                    # Skip authenticated endpoints if we don't have a token
                    results.append(
                        EndpointResult(method, path, None, False, "Skipped (no auth)")
                    )
                    continue

            result = await test_endpoint(client, base_url, method, path, body, token)
            results.append(result)
            print(result)

    # Summary
    print("\n" + "=" * 60)
    success = sum(1 for r in results if r.success)
    total = len(results)
    print(f"Summary: {success}/{total} endpoints accessible")

    # Show failures
    failures = [r for r in results if not r.success]
    if failures:
        print("\nFailed endpoints:")
        for f in failures:
            print(f"  - {f.method} {f.path}: {f.error or f.status_code}")

    return success, total


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify API endpoints")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8080",
        help="Base URL for the gateway (default: http://127.0.0.1:8080)",
    )
    args = parser.parse_args()

    success, total = asyncio.run(verify_endpoints(args.base_url))

    # Return 0 if all endpoints pass, 1 otherwise
    return 0 if success == total else 1


if __name__ == "__main__":
    sys.exit(main())
