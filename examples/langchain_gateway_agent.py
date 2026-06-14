"""LangChain E2E example for calling the Agent-MemoryForge gateway.

This example intentionally keeps LangChain as an optional integration dependency:

    python -m pip install langchain-core
    python examples/langchain_gateway_agent.py --mint-dev-token

For production, pass AGENT_MEMORY_ACCESS_TOKEN instead of minting a local dev
token. The script records end-to-end latency for the gateway call and validates
that the returned answer contains expected memory facts.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

import requests
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _mint_dev_token(*, tenant_id: str, user_id: str, secret_file: str | None) -> str:
    if secret_file and not os.getenv("AUTH_JWT_SECRET"):
        with open(secret_file, "r", encoding="utf-8") as handle:
            os.environ["AUTH_JWT_SECRET"] = handle.read().strip()

    from agent_runtime.product.auth_tokens import create_access_token

    return create_access_token(sub=user_id, tenant_id=tenant_id, expires_in_s=900)


def _build_gateway_tool(
    *,
    gateway_url: str,
    token: str,
    workspace_id: str,
    tenant_id: str,
    user_id: str,
    agent_id: str,
    conversation_id: str,
):
    @tool("agent_memory_chat")
    def agent_memory_chat(question: str) -> Dict[str, Any]:
        """Ask the Agent-MemoryForge product gateway and return its answer plus latency."""

        started = time.perf_counter()
        response = requests.post(
            f"{gateway_url.rstrip('/')}/v1/chat",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Workspace-Id": workspace_id,
                "X-Trace-Id": f"lc_e2e_{uuid.uuid4().hex[:12]}",
            },
            json={
                "agent": agent_id,
                "user_id": user_id,
                "conversation_id": conversation_id,
                "messages": [{"role": "user", "content": question}],
                "temperature": 0.0,
                "max_tool_turns": 6,
            },
            timeout=90,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        response.raise_for_status()
        payload = response.json()
        return {
            "status": payload.get("status"),
            "answer": payload.get("answer") or "",
            "conversation_id": payload.get("conversation_id"),
            "trace_id": payload.get("trace_id"),
            "latency_ms": latency_ms,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
        }

    return agent_memory_chat


def main() -> int:
    parser = argparse.ArgumentParser(description="LangChain E2E gateway agent")
    parser.add_argument(
        "--gateway-url",
        default=os.getenv("AGENT_MEMORY_GATEWAY_URL", "http://127.0.0.1:8080"),
    )
    parser.add_argument(
        "--tenant-id", default=os.getenv("AGENT_MEMORY_TENANT_ID", "t_zhouboyang")
    )
    parser.add_argument(
        "--workspace-id", default=os.getenv("AGENT_MEMORY_WORKSPACE_ID", "ws_default")
    )
    parser.add_argument(
        "--user-id", default=os.getenv("AGENT_MEMORY_USER_ID", "zhouboyang")
    )
    parser.add_argument(
        "--agent-id", default=os.getenv("AGENT_MEMORY_AGENT_ID", "code-assistant")
    )
    parser.add_argument(
        "--conversation-id", default=f"conv_langchain_e2e_{uuid.uuid4().hex[:12]}"
    )
    parser.add_argument(
        "--question",
        default="请从长期记忆里回答：finance_mrr 的刷新 SLA、owner、上游依赖是什么？",
    )
    parser.add_argument("--mint-dev-token", action="store_true")
    parser.add_argument("--jwt-secret-file", default=".runtime/dev_auth_jwt_secret")
    args = parser.parse_args()

    token = os.getenv("AGENT_MEMORY_ACCESS_TOKEN")
    if not token and args.mint_dev_token:
        token = _mint_dev_token(
            tenant_id=args.tenant_id,
            user_id=args.user_id,
            secret_file=args.jwt_secret_file,
        )
    if not token:
        raise SystemExit("Set AGENT_MEMORY_ACCESS_TOKEN or pass --mint-dev-token")

    gateway_tool = _build_gateway_tool(
        gateway_url=args.gateway_url,
        token=token,
        workspace_id=args.workspace_id,
        tenant_id=args.tenant_id,
        user_id=args.user_id,
        agent_id=args.agent_id,
        conversation_id=args.conversation_id,
    )
    agent = RunnableLambda(lambda inputs: gateway_tool.invoke(inputs["question"]))
    result = agent.invoke({"question": args.question})

    answer = str(result.get("answer") or "")
    expected = ["09:00", "Alice", "raw_invoices", "raw_payments"]
    missing = [item for item in expected if item not in answer]
    passed = result.get("status") == "success" and not missing

    print(
        {
            "passed": passed,
            "status": result.get("status"),
            "latency_ms": result.get("latency_ms"),
            "trace_id": result.get("trace_id"),
            "conversation_id": result.get("conversation_id"),
            "missing": missing,
            "answer_preview": answer[:240],
        }
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
