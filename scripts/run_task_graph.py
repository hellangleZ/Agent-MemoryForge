from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_memory_lib import MemoryClient
from agent_memory_framework.llm_resolver import resolve_llm_provider
from agent_memory_framework.multi_agent import CoordinationStrategy, build_team_runtime
from agent_memory_framework.orchestrator import LLMTaskGraphPlanner, TaskGraphOrchestrator
from agent_memory_framework.runtime import Runtime
from agent_memory_framework.settings import Settings
from agent_runtime.product.templates.code_assistant import CodeAssistantAgent


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run dynamic TaskGraph orchestration.")
    parser.add_argument("--message", required=True, help="User request to orchestrate.")
    parser.add_argument(
        "--memory-url",
        default="http://127.0.0.1:8001",
        help="Memory service base URL.",
    )
    parser.add_argument("--tenant-id", default="t_default", help="Tenant id.")
    parser.add_argument("--workspace-id", default="ws_default", help="Workspace id.")
    parser.add_argument(
        "--isolation",
        default="shared",
        choices=["shared", "per_role"],
        help="Isolation mode for artifacts (shared or per_role).",
    )
    parser.add_argument(
        "--no-artifacts",
        action="store_true",
        help="Disable persisting step artifacts to File-First memory.",
    )
    parser.add_argument(
        "--planner-md",
        default="workflows/AUTO_TASK_GRAPH.md",
        help="Path to coordinator instructions (Markdown).",
    )
    args = parser.parse_args()

    provider = resolve_llm_provider(config=None, explicit_llm_provider=None, temperature=0.2).provider

    memory_client = MemoryClient(args.memory_url).with_scope(
        tenant_id=args.tenant_id, workspace_id=args.workspace_id
    )

    base_runtime = Runtime(
        agent_id="coordinator",
        user_id="user_default",
        memory_client=memory_client,
        llm_provider=provider,
        conversation_id="conv_task_graph",
        settings=Settings(),
    )

    agent_factories = {
        "planner": lambda rt: CodeAssistantAgent(rt),
        "researcher_1": lambda rt: CodeAssistantAgent(rt),
        "researcher_2": lambda rt: CodeAssistantAgent(rt),
        "implementer": lambda rt: CodeAssistantAgent(rt),
        "reviewer": lambda rt: CodeAssistantAgent(rt),
        "tester": lambda rt: CodeAssistantAgent(rt),
        "synthesizer": lambda rt: CodeAssistantAgent(rt),
    }

    team = build_team_runtime(
        base_runtime=base_runtime,
        agent_factories=agent_factories,
        roles=None,
        strategy=CoordinationStrategy.PARALLEL,
    )

    planner_instructions = _read_text(Path(args.planner_md))
    planner = LLMTaskGraphPlanner(
        llm_provider=provider,
        system_instructions=planner_instructions,
    )

    orchestrator = TaskGraphOrchestrator(
        agents=team.agents,
        planner=planner,
        artifacts_enabled=not args.no_artifacts,
        isolation_mode=args.isolation,
    )

    result = orchestrator.run(args.message)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

