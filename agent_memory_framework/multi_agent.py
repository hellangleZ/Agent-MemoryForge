from __future__ import annotations

import contextvars
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional

from agent_memory_framework.agent import Agent
from agent_memory_framework.replay import RunRecorder
from agent_memory_framework.runtime import Runtime
from agent_memory_framework.trace import TraceCollector, trace_span
from agent_memory_framework.feature_flags import parallel_workers

# Context-local storage for thread-safe trace management
_trace_collector_var: contextvars.ContextVar[Optional[TraceCollector]] = (
    contextvars.ContextVar("trace_collector", default=None)
)
_trace_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "trace_id", default=None
)


class CoordinationStrategy(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


@dataclass(frozen=True)
class RoutedTurn:
    role: str
    agent_id: str
    user_query: str
    response_text: str


@dataclass(frozen=True)
class RoutingTrace:
    strategy: CoordinationStrategy
    turns: List[RoutedTurn]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "turns": [
                {
                    "role": turn.role,
                    "agent_id": turn.agent_id,
                    "user_query": turn.user_query,
                    "response_text": turn.response_text,
                }
                for turn in self.turns
            ],
        }


class MultiAgentRuntime:
    """Minimal multi-agent coordinator.

    The goal is to provide a stable interface for collaboration without
    requiring a full UI or provider-specific behavior.
    """

    def __init__(
        self,
        *,
        agents: Mapping[str, Agent],
        roles: Optional[Mapping[str, str]] = None,
        strategy: CoordinationStrategy = CoordinationStrategy.SEQUENTIAL,
    ) -> None:
        if not agents:
            raise ValueError("agents must be non-empty")
        self._agents: Dict[str, Agent] = dict(agents)
        self._roles: Dict[str, str] = dict(roles or {})
        self._strategy = strategy

    @property
    def agent_ids(self) -> List[str]:
        return list(self._agents.keys())

    @property
    def agents(self) -> Mapping[str, Agent]:
        """Return the agent mapping (read-only view)."""

        return dict(self._agents)

    def run(
        self,
        user_query: str,
        *,
        trace_id: str | None = None,
        record: RunRecorder | None = None,
    ) -> Dict[str, Any]:
        turns: List[RoutedTurn] = []
        response_map: Dict[str, str] = {}

        collector = TraceCollector()

        # Set context-local variables for thread-safe access
        collector_token = _trace_collector_var.set(collector)
        trace_token = _trace_id_var.set(trace_id) if trace_id else None

        try:
            if self._strategy == CoordinationStrategy.PARALLEL:
                import concurrent.futures

                max_workers = parallel_workers(default=None)
                if max_workers is None:
                    max_workers = min(8, len(self._agents))
                else:
                    max_workers = min(max_workers, len(self._agents))

                # Capture current context values for thread safety
                captured_collector = collector
                captured_trace_id = trace_id

                def _run_one(agent_id: str, agent: Agent) -> RoutedTurn:
                    # Set context-local variables in this thread
                    local_collector_token = _trace_collector_var.set(captured_collector)
                    local_trace_token = (
                        _trace_id_var.set(captured_trace_id)
                        if captured_trace_id
                        else None
                    )
                    prev_trace_id = agent.runtime.trace_id
                    agent.runtime.trace_id = captured_trace_id
                    try:
                        local_collector = _trace_collector_var.get()
                        local_trace_id = _trace_id_var.get()
                        with trace_span(
                            local_collector,
                            "agent.turn",
                            agent_id=agent_id,
                            strategy=self._strategy.value,
                            trace_id=local_trace_id,
                        ):
                            text = agent.run_turn(user_query)
                    finally:
                        agent.runtime.trace_id = prev_trace_id
                        if local_trace_token is not None:
                            _trace_id_var.reset(local_trace_token)
                        _trace_collector_var.reset(local_collector_token)
                    role = self._roles.get(agent_id, agent_id)
                    return RoutedTurn(
                        role=role,
                        agent_id=agent_id,
                        user_query=user_query,
                        response_text=text,
                    )

                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                    futures = [
                        ex.submit(_run_one, agent_id, agent)
                        for agent_id, agent in self._agents.items()
                    ]
                    turns = [f.result() for f in futures]
                for turn in turns:
                    response_map[turn.agent_id] = turn.response_text
            else:
                local_trace_id = _trace_id_var.get()
                for agent_id, agent in self._agents.items():
                    prev_trace_id = agent.runtime.trace_id
                    agent.runtime.trace_id = trace_id
                    try:
                        with trace_span(
                            collector,
                            "agent.turn",
                            agent_id=agent_id,
                            strategy=self._strategy.value,
                            trace_id=local_trace_id,
                        ):
                            text = agent.run_turn(user_query)
                    finally:
                        agent.runtime.trace_id = prev_trace_id
                    role = self._roles.get(agent_id, agent_id)
                    turns.append(
                        RoutedTurn(
                            role=role,
                            agent_id=agent_id,
                            user_query=user_query,
                            response_text=text,
                        )
                    )
                    response_map[agent_id] = text
        finally:
            if trace_token is not None:
                _trace_id_var.reset(trace_token)
            _trace_collector_var.reset(collector_token)

        routing_trace = RoutingTrace(strategy=self._strategy, turns=turns)

        if record is not None:
            record.record_result(
                routing_trace=routing_trace.as_dict(), trace=collector.as_dict()
            )

        return {
            "strategy": self._strategy.value,
            "final": turns[-1].response_text,
            "responses": response_map,
            "routing_trace": routing_trace.as_dict(),
            "trace": collector.as_dict(),
        }


def build_team_runtime(
    *,
    base_runtime: Runtime,
    agent_factories: Mapping[str, Any],
    roles: Optional[Mapping[str, str]] = None,
    strategy: CoordinationStrategy | str = CoordinationStrategy.SEQUENTIAL,
) -> MultiAgentRuntime:
    agents: Dict[str, Agent] = {}
    for agent_id, factory in agent_factories.items():
        # Clone the memory client per agent to avoid sharing a single requests.Session
        # across threads in parallel execution.
        memory_client = base_runtime.memory_client
        try:
            if hasattr(memory_client, "clone"):
                memory_client = memory_client.clone()
            elif hasattr(memory_client, "with_scope"):
                tenant_id = getattr(memory_client, "tenant_id", None)
                workspace_id = getattr(memory_client, "workspace_id", None)
                if tenant_id and workspace_id:
                    memory_client = memory_client.with_scope(
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                    )
        except Exception:
            memory_client = base_runtime.memory_client

        runtime = Runtime(
            agent_id=agent_id,
            user_id=base_runtime.user_id,
            memory_client=memory_client,
            llm_provider=base_runtime.llm_provider,
            conversation_id=base_runtime.conversation_id,
            settings=base_runtime.settings,
            request_id=base_runtime.request_id,
            trace_id=base_runtime.trace_id,
        )
        agents[agent_id] = factory(runtime)
    if isinstance(strategy, str):
        try:
            strategy = CoordinationStrategy(strategy)
        except ValueError:
            strategy = CoordinationStrategy.SEQUENTIAL
    return MultiAgentRuntime(agents=agents, roles=roles, strategy=strategy)


__all__ = [
    "CoordinationStrategy",
    "MultiAgentRuntime",
    "RoutedTurn",
    "RoutingTrace",
    "build_team_runtime",
]
