from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Type, TypeVar

from agent_memory_lib import MemoryClient

from agent_memory_framework.runtime import Runtime
from agent_memory_framework.settings import Settings
from agent_memory_framework.trace import TraceCollector

from agent_memory_framework.multi_agent import (
    CoordinationStrategy,
    MultiAgentRuntime,
    build_team_runtime,
)
from agent_memory_framework.feature_flags import enable_parallel
from agent_memory_framework.orchestrator import LLMTaskGraphPlanner, TaskGraphOrchestrator
from agent_memory_framework.task_graph import TaskGraphValidator


TAgent = TypeVar("TAgent")


@dataclass(frozen=True)
class AgentBuildOptions:
    agent_id: str
    user_id: str
    conversation_id: str

    memory_client: MemoryClient
    llm_provider: Any
    settings: Settings = Settings()

    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    trace: Optional[TraceCollector] = None


def build_agent(agent_cls: Type[TAgent], *, options: AgentBuildOptions) -> TAgent:
    """Build a framework Agent with a fully wired Runtime.

    This keeps user code minimal and avoids repeating boilerplate Runtime wiring.
    """

    runtime = Runtime(
        agent_id=options.agent_id,
        user_id=options.user_id,
        memory_client=options.memory_client,
        llm_provider=options.llm_provider,
        conversation_id=options.conversation_id,
        settings=options.settings,
        request_id=options.request_id,
        trace_id=options.trace_id,
        trace=options.trace,
    )
    return agent_cls(runtime)


@dataclass(frozen=True)
class AutoBuildOverrides:
    agent_id: Optional[str] = None
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    memory_service_url: Optional[str] = None
    trace_id: Optional[str] = None


def build_agent_from_config(
    agent_cls: Type[TAgent],
    *,
    config: Any = None,
    overrides: Optional[AutoBuildOverrides] = None,
    settings: Optional[Settings] = None,
    request_id: Optional[str] = None,
) -> TAgent:
    """One-line agent builder.

    Preference order (C):
    - values from `config` if present
    - otherwise env vars
    - otherwise safe defaults
    """

    import os
    import uuid

    overrides = overrides or AutoBuildOverrides()

    # Prefer config fields; fall back to env; finally fallback defaults.
    memory_service_url = (
        overrides.memory_service_url
        or getattr(config, "memory_service_url", None)
        or os.getenv("MEMORY_SERVICE_URL")
        or "http://127.0.0.1:8001"
    )
    user_id = (
        overrides.user_id
        or getattr(config, "user_id", None)
        or os.getenv("USER_ID")
        or "user_default"
    )
    agent_id = (
        overrides.agent_id
        or getattr(config, "agent_id", None)
        or os.getenv("AGENT_ID")
        or agent_cls.__name__
    )

    conversation_id = overrides.conversation_id or f"conv_{uuid.uuid4().hex}"
    trace_id = overrides.trace_id or os.getenv("TRACE_ID")

    memory_client = MemoryClient(base_url=memory_service_url)

    # LLMProvider: config first (instance), then provider selection (config/env),
    # then env detection. Never default to Azure if nothing is configured.
    from agent_memory_framework.llm_resolver import resolve_llm_provider

    resolved = resolve_llm_provider(
        config=config,
        explicit_llm_provider=getattr(config, "llm_provider", None),
        temperature=0.2,
    )
    llm_provider = resolved.provider

    return build_agent(
        agent_cls,
        options=AgentBuildOptions(
            agent_id=str(agent_id),
            user_id=str(user_id),
            conversation_id=str(conversation_id),
            memory_client=memory_client,
            llm_provider=llm_provider,
            settings=settings or Settings(),
            request_id=request_id,
            trace_id=trace_id,
            trace=None,
        ),
    )


def build_team_from_config(
    *,
    agent_factories: Dict[str, Any],
    roles: Optional[Dict[str, str]] = None,
    strategy: CoordinationStrategy | str = CoordinationStrategy.PARALLEL,
    config: Any = None,
    overrides: Optional[AutoBuildOverrides] = None,
    settings: Optional[Settings] = None,
    request_id: Optional[str] = None,
) -> MultiAgentRuntime:
    """One-line multi-agent builder.

    - Auto-wires MemoryClient + LLMProvider from config/env
    - Builds a base Runtime and expands into per-agent runtimes
    - Defaults to parallel execution
    """

    # Use a minimal placeholder agent class for the base runtime; the runtime is cloned per role.
    class _BaseAgent:
        def __init__(self, runtime: Runtime):
            self.runtime = runtime

    base_agent = build_agent_from_config(
        _BaseAgent,
        config=config,
        overrides=overrides,
        settings=settings,
        request_id=request_id,
    )

    resolved_strategy = strategy
    if enable_parallel(default=True) is False:
        resolved_strategy = CoordinationStrategy.SEQUENTIAL

    return build_team_runtime(
        base_runtime=base_agent.runtime,
        agent_factories=agent_factories,
        roles=roles,
        strategy=resolved_strategy,
    )


def build_orchestrated_team_from_config(
    *,
    agent_factories: Dict[str, Any],
    planner_instructions: str,
    roles: Optional[Dict[str, str]] = None,
    strategy: CoordinationStrategy | str = CoordinationStrategy.PARALLEL,
    isolation_mode: str = "shared",
    artifacts_enabled: bool = True,
    config: Any = None,
    overrides: Optional[AutoBuildOverrides] = None,
    settings: Optional[Settings] = None,
    request_id: Optional[str] = None,
) -> TaskGraphOrchestrator:
    """Build a TaskGraphOrchestrator wired from config/env.

    Notes:
    - Artifact persistence requires a scoped MemoryClient (tenant_id + workspace_id).
      In product usage, build runtimes via the Gateway which provides scoped clients.
    - This helper is primarily for demos/tests and expects `planner_instructions`
      to be provided (Markdown text).
    """

    team = build_team_from_config(
        agent_factories=agent_factories,
        roles=roles,
        strategy=strategy,
        config=config,
        overrides=overrides,
        settings=settings,
        request_id=request_id,
    )

    # Planner uses the first agent's LLM provider (shared across the team).
    first_agent = next(iter(team.agents.values()))
    planner = LLMTaskGraphPlanner(
        llm_provider=first_agent.runtime.llm_provider,
        system_instructions=planner_instructions,
    )

    validator = TaskGraphValidator()
    return TaskGraphOrchestrator(
        agents=team.agents,
        planner=planner,
        validator=validator,
        artifacts_enabled=artifacts_enabled,
        isolation_mode=isolation_mode,
    )


__all__ = [
    "AgentBuildOptions",
    "AutoBuildOverrides",
    "build_agent",
    "build_agent_from_config",
    "build_team_from_config",
    "build_orchestrated_team_from_config",
]
