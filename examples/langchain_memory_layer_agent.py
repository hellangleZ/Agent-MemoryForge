"""LangChain memory-layer E2E example.

This is the recommended enterprise integration shape:

- Customer-owned LangChain/LangGraph/custom agent keeps its own LLM and tool loop.
- Agent-MemoryForge is used only as the scoped memory layer through the SDK/API.
- The gateway derives tenant/workspace/actor from auth and proxies memory APIs.

The default "customer LLM" below is deterministic so CI and enterprise smoke tests
can run without sending data to a third-party model. Replace that RunnableLambda
with ChatOpenAI, AzureChatOpenAI, Anthropic, a private model, or any LangChain
chat model in a real customer agent.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent_memory_lib import MemoryClient

EXPECTED_FACTS = ["09:00", "Alice", "raw_invoices", "raw_payments"]
DEFAULT_QUESTION = "请用我们的记忆回答：finance_mrr 的刷新 SLA、owner、上游依赖是什么？"


def _mint_dev_token(*, tenant_id: str, user_id: str, secret_file: str | None) -> str:
    if secret_file and not os.getenv("AUTH_JWT_SECRET"):
        with open(secret_file, "r", encoding="utf-8") as handle:
            os.environ["AUTH_JWT_SECRET"] = handle.read().strip()

    from agent_runtime.product.auth_tokens import create_access_token

    return create_access_token(sub=user_id, tenant_id=tenant_id, expires_in_s=900)


def _ms_since(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _client(args: argparse.Namespace, *, token: str) -> MemoryClient:
    return MemoryClient(
        args.gateway_url,
        tenant_id=args.tenant_id,
        workspace_id=args.workspace_id,
        access_token=token,
        shared_pool=True,
        timeout=args.timeout_s,
        max_retries=2,
    )


def _seed_memory(memory: MemoryClient, *, user_id: str, conversation_id: str, run_id: str) -> Dict[str, Any]:
    started = time.perf_counter()
    writes: List[Dict[str, Any]] = []
    writes.append(memory.store_ltm_preference(user_id, "answer_style", "短句、先结论"))
    writes.append(
        memory.store_stm(
            conversation_id,
            1,
            "上一轮确认 finance_mrr 要关注刷新 SLA、owner 和上游依赖。",
        )
    )
    writes.append(
        memory.memory_write(
            tier="semantic",
            scope="project",
            content="finance_mrr 的刷新 SLA 是每天 09:00 Asia/Shanghai 前完成，owner 是 Alice。",
            metadata={"source": "langchain_memory_layer_e2e", "run_id": run_id, "tags": ["dw", "sla"]},
        )
    )
    for subject, relation, obj in [
        ("finance_mrr", "depends_on", "raw_invoices"),
        ("finance_mrr", "depends_on", "raw_payments"),
    ]:
        writes.append(
            memory.memory_write(
                tier="graph",
                scope="project",
                content="",
                metadata={
                    "subject": subject,
                    "relation": relation,
                    "obj": obj,
                    "source": "langchain_memory_layer_e2e",
                    "run_id": run_id,
                },
            )
        )
    return {"write_count": len(writes), "latency_ms": _ms_since(started)}


def _message_content(messages: Iterable[Dict[str, str]]) -> str:
    return "\n\n".join(str(m.get("content") or "") for m in messages or [])


def deterministic_customer_llm(*, messages: List[Dict[str, str]], question: str) -> str:
    """Small deterministic stand-in for the customer's own LLM.

    It reads the same memory-context messages a real LangChain chat model would
    receive. This keeps the E2E deterministic while proving the SDK/API contract.
    """

    context = _message_content(messages)
    sla = "每天 09:00 Asia/Shanghai 前完成" if "09:00" in context else "未在记忆中找到"
    owner = "Alice" if "Alice" in context else "未在记忆中找到"
    upstream = []
    if "raw_invoices" in context:
        upstream.append("raw_invoices")
    if "raw_payments" in context:
        upstream.append("raw_payments")
    upstream_text = "、".join(upstream) if upstream else "未在记忆中找到"
    return (
        "从 Agent-MemoryForge 返回的上下文看：\n"
        f"- 刷新 SLA：{sla}\n"
        f"- owner：{owner}\n"
        f"- 上游依赖：{upstream_text}\n"
        f"- 问题：{question}"
    )


def _validate_answer(answer: str) -> Tuple[bool, List[str]]:
    missing = [item for item in EXPECTED_FACTS if item not in str(answer or "")]
    return not missing, missing


def _build_context(memory: MemoryClient, *, args: argparse.Namespace) -> List[Dict[str, str]]:
    return memory.build_context(
        query=args.question,
        user_id=args.user_id,
        conversation_id=args.conversation_id,
        system_prompt="You are a customer-owned LangChain data warehouse agent.",
        top_k=args.top_k,
        max_search_queries=args.max_search_queries,
    )


def _run_langchain_memory_layer(memory: MemoryClient, *, args: argparse.Namespace) -> Dict[str, Any]:
    try:
        from langchain_core.runnables import RunnableLambda
    except Exception as exc:  # pragma: no cover - environment dependent
        raise SystemExit("Install langchain-core to run this example: python -m pip install langchain-core") from exc

    timings: Dict[str, float] = {}

    def memory_stage(inputs: Dict[str, Any]) -> Dict[str, Any]:
        started = time.perf_counter()
        context_messages = _build_context(memory, args=args)
        timings["context_ms"] = _ms_since(started)
        return {**inputs, "context_messages": context_messages}

    def llm_stage(inputs: Dict[str, Any]) -> Dict[str, Any]:
        started = time.perf_counter()
        answer = deterministic_customer_llm(
            messages=[*inputs["context_messages"], {"role": "user", "content": inputs["question"]}],
            question=inputs["question"],
        )
        timings["llm_ms"] = _ms_since(started)
        return {**inputs, "answer": answer}

    def writeback_stage(inputs: Dict[str, Any]) -> Dict[str, Any]:
        started = time.perf_counter()
        memory.store_stm(args.conversation_id, 2, inputs["answer"])
        timings["writeback_ms"] = _ms_since(started)
        return inputs

    chain = RunnableLambda(memory_stage) | RunnableLambda(llm_stage) | RunnableLambda(writeback_stage)
    result = chain.invoke({"question": args.question})
    answer = str(result.get("answer") or "")
    passed, missing = _validate_answer(answer)
    return {
        "passed": passed,
        "missing": missing,
        "answer_preview": answer[:240],
        "context_chars": len(_message_content(result.get("context_messages") or [])),
        **timings,
    }


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = (len(ordered) - 1) * pct
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return round(ordered[lo] * (1 - frac) + ordered[hi] * frac, 3)


def _run_load_check(base_memory: MemoryClient, *, args: argparse.Namespace) -> Dict[str, Any]:
    total = max(0, int(args.load_requests or 0))
    if total <= 0:
        return {"enabled": False}

    latencies: List[float] = []
    failures: List[str] = []

    def one_call(i: int) -> float:
        memory = base_memory.clone()
        started = time.perf_counter()
        messages = _build_context(memory, args=args)
        content = _message_content(messages)
        missing = [item for item in EXPECTED_FACTS if item not in content]
        if missing:
            raise RuntimeError(f"missing expected memory facts: {missing}")
        return _ms_since(started)

    with ThreadPoolExecutor(max_workers=max(1, int(args.concurrency or 1))) as pool:
        futures = [pool.submit(one_call, i) for i in range(total)]
        for fut in as_completed(futures):
            try:
                latencies.append(float(fut.result()))
            except Exception as exc:
                failures.append(str(exc))

    return {
        "enabled": True,
        "requests": total,
        "concurrency": max(1, int(args.concurrency or 1)),
        "successes": len(latencies),
        "failures": len(failures),
        "failure_preview": failures[:3],
        "p50_ms": _percentile(latencies, 0.50),
        "p95_ms": _percentile(latencies, 0.95),
        "max_ms": round(max(latencies), 3) if latencies else 0.0,
        "mean_ms": round(statistics.fmean(latencies), 3) if latencies else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="LangChain memory-layer E2E")
    parser.add_argument("--gateway-url", default=os.getenv("AGENT_MEMORY_GATEWAY_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--tenant-id", default=os.getenv("AGENT_MEMORY_TENANT_ID", "t_zhouboyang"))
    parser.add_argument("--workspace-id", default=os.getenv("AGENT_MEMORY_WORKSPACE_ID", "ws_default"))
    parser.add_argument("--user-id", default=os.getenv("AGENT_MEMORY_USER_ID", "zhouboyang"))
    parser.add_argument("--conversation-id", default=f"conv_langchain_memory_layer_{uuid.uuid4().hex[:12]}")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-search-queries", type=int, default=2)
    parser.add_argument("--timeout-s", type=int, default=30)
    parser.add_argument("--load-requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--skip-seed", action="store_true")
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

    run_id = f"lc_mem_{uuid.uuid4().hex[:12]}"
    memory = _client(args, token=token)
    started = time.perf_counter()
    seed = {"skipped": True}
    if not args.skip_seed:
        seed = _seed_memory(memory, user_id=args.user_id, conversation_id=args.conversation_id, run_id=run_id)

    e2e = _run_langchain_memory_layer(memory, args=args)
    load = _run_load_check(memory, args=args)
    passed = bool(e2e.get("passed")) and (not load.get("enabled") or load.get("failures") == 0)
    output = {
        "passed": passed,
        "status": "success" if passed else "error",
        "run_id": run_id,
        "tenant_id": args.tenant_id,
        "workspace_id": args.workspace_id,
        "user_id": args.user_id,
        "conversation_id": args.conversation_id,
        "total_ms": _ms_since(started),
        "seed": seed,
        "e2e": e2e,
        "load": load,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
