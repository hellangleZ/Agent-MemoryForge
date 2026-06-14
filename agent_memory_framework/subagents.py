from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from agent_memory_framework.feature_flags import parallel_workers


@dataclass(frozen=True)
class SubAgentResult:
    agent_id: str
    task_id: str
    role: str
    output_text: str


class SubAgentError(RuntimeError):
    pass


class SubAgentRunner:
    """Small helper for running multiple agent turns concurrently.

    This is intentionally synchronous and in-process. It provides an interface
    similar in spirit to OpenClaw "subagents", but without sessions/announce.
    """

    def __init__(self, *, max_workers: Optional[int] = None) -> None:
        self._max_workers = max_workers

    def run_many(
        self,
        tasks: Sequence[Tuple[str, str, str, str]],
        *,
        agents: Mapping[str, Any],
    ) -> List[SubAgentResult]:
        """Run many tasks.

        Args:
            tasks: list of (task_id, role, agent_id, prompt)
            agents: agent mapping (agent_id -> agent with run_turn)
        """

        if not tasks:
            return []

        resolved_max = self._max_workers
        if resolved_max is None:
            resolved_max = parallel_workers(default=None)
        if resolved_max is None:
            resolved_max = min(8, len(tasks))
        else:
            resolved_max = min(int(resolved_max), len(tasks))

        def _run_one(task_id: str, role: str, agent_id: str, prompt: str) -> SubAgentResult:
            agent = agents.get(agent_id)
            if agent is None:
                raise SubAgentError(f"Unknown agent_id={agent_id!r}")
            text = agent.run_turn(prompt)
            return SubAgentResult(
                agent_id=agent_id,
                task_id=task_id,
                role=role,
                output_text=str(text),
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=resolved_max) as ex:
            futures = [
                ex.submit(_run_one, task_id, role, agent_id, prompt)
                for task_id, role, agent_id, prompt in tasks
            ]
            results = [f.result() for f in futures]

        # Preserve caller order for determinism.
        result_map = {(r.task_id, r.agent_id): r for r in results}
        ordered: List[SubAgentResult] = []
        for task_id, _, agent_id, _ in tasks:
            ordered.append(result_map[(task_id, agent_id)])
        return ordered


__all__ = ["SubAgentError", "SubAgentResult", "SubAgentRunner"]

