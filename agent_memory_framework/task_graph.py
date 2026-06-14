from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set


@dataclass(frozen=True)
class TaskArtifactSpec:
    name: str
    persist: bool = True
    tier: str = "wm"
    scope: str = "orchestration"


@dataclass(frozen=True)
class TaskLimits:
    max_tool_turns: Optional[int] = None
    timeout_s: Optional[int] = None


@dataclass(frozen=True)
class TaskInputs:
    artifacts_from: List[str]


@dataclass(frozen=True)
class TaskNode:
    id: str
    role: str
    agent_id: str
    depends_on: List[str]
    instructions: str
    inputs: TaskInputs
    parallel_group: Optional[str] = None
    artifact: Optional[TaskArtifactSpec] = None
    limits: TaskLimits = TaskLimits()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TaskNode":
        artifact = payload.get("artifact")
        artifact_spec: TaskArtifactSpec | None = None
        if isinstance(artifact, Mapping):
            artifact_spec = TaskArtifactSpec(
                name=str(artifact.get("name") or "").strip() or "artifact",
                persist=bool(artifact.get("persist", True)),
                tier=str(artifact.get("tier") or "wm").strip() or "wm",
                scope=str(artifact.get("scope") or "orchestration").strip()
                or "orchestration",
            )

        limits = payload.get("limits") or {}
        limits_spec = TaskLimits(
            max_tool_turns=int(limits["max_tool_turns"])
            if isinstance(limits, Mapping) and limits.get("max_tool_turns") is not None
            else None,
            timeout_s=int(limits["timeout_s"])
            if isinstance(limits, Mapping) and limits.get("timeout_s") is not None
            else None,
        )

        inputs = payload.get("inputs") or {}
        artifacts_from: List[str] = []
        if isinstance(inputs, Mapping):
            raw = inputs.get("artifacts_from") or []
            if isinstance(raw, list):
                artifacts_from = [str(x) for x in raw if str(x).strip()]

        depends_on = payload.get("depends_on") or []
        if not isinstance(depends_on, list):
            depends_on = []
        depends_on_list = [str(x) for x in depends_on if str(x).strip()]

        return cls(
            id=str(payload.get("id") or "").strip(),
            role=str(payload.get("role") or "").strip(),
            agent_id=str(payload.get("agent_id") or "").strip(),
            depends_on=depends_on_list,
            instructions=str(payload.get("instructions") or "").strip(),
            inputs=TaskInputs(artifacts_from=artifacts_from),
            parallel_group=str(payload.get("parallel_group") or "").strip() or None,
            artifact=artifact_spec,
            limits=limits_spec,
        )


@dataclass(frozen=True)
class TaskGraphFinal:
    task_id: str
    merge_tasks: List[str]
    format: str = "report"


@dataclass(frozen=True)
class TaskGraph:
    version: str
    goal: str
    constraints: List[str]
    tasks: List[TaskNode]
    final: TaskGraphFinal

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TaskGraph":
        constraints_raw = payload.get("constraints") or []
        constraints: List[str] = []
        if isinstance(constraints_raw, list):
            constraints = [str(x) for x in constraints_raw if str(x).strip()]

        tasks_raw = payload.get("tasks") or []
        tasks: List[TaskNode] = []
        if isinstance(tasks_raw, list):
            tasks = [TaskNode.from_dict(x) for x in tasks_raw if isinstance(x, Mapping)]

        final_raw = payload.get("final") or {}
        if not isinstance(final_raw, Mapping):
            final_raw = {}
        merge_raw = final_raw.get("merge_tasks") or []
        merge_tasks: List[str] = []
        if isinstance(merge_raw, list):
            merge_tasks = [str(x) for x in merge_raw if str(x).strip()]
        final = TaskGraphFinal(
            task_id=str(final_raw.get("task_id") or "").strip(),
            merge_tasks=merge_tasks,
            format=str(final_raw.get("format") or "report").strip() or "report",
        )

        return cls(
            version=str(payload.get("version") or "").strip(),
            goal=str(payload.get("goal") or "").strip(),
            constraints=constraints,
            tasks=tasks,
            final=final,
        )

    @classmethod
    def from_json(cls, text: str) -> "TaskGraph":
        payload = json.loads(text)
        if not isinstance(payload, Mapping):
            raise ValueError("TaskGraph JSON must be an object")
        return cls.from_dict(payload)


class TaskGraphValidationError(ValueError):
    pass


class TaskGraphValidator:
    def __init__(
        self,
        *,
        allowed_roles: Optional[Sequence[str]] = None,
        max_tasks: int = 12,
        max_parallel: int = 6,
    ) -> None:
        self.allowed_roles: Set[str] = set(allowed_roles or [])
        self.max_tasks = int(max_tasks)
        self.max_parallel = int(max_parallel)

    @staticmethod
    def default_allowed_roles() -> List[str]:
        return [
            "coordinator",
            "planner",
            "research",
            "implement",
            "review",
            "test",
            "synthesize",
        ]

    def validate(self, graph: TaskGraph) -> None:
        errors: List[str] = []

        if graph.version != "v1":
            errors.append("version must be 'v1'")

        if not graph.goal:
            errors.append("goal is required")

        if not graph.tasks:
            errors.append("tasks must be non-empty")

        if self.max_tasks > 0 and len(graph.tasks) > self.max_tasks:
            errors.append(f"too many tasks: {len(graph.tasks)} > {self.max_tasks}")

        task_ids = [t.id for t in graph.tasks if t.id]
        if len(task_ids) != len(set(task_ids)):
            errors.append("task ids must be unique and non-empty")

        task_map = {t.id: t for t in graph.tasks if t.id}

        roles_allow = self.allowed_roles or set(self.default_allowed_roles())

        for task in graph.tasks:
            if not task.id:
                errors.append("task.id is required")
                continue
            if not task.role:
                errors.append(f"task {task.id}: role is required")
            elif task.role not in roles_allow:
                errors.append(
                    f"task {task.id}: unsupported role {task.role!r} (allowed: {sorted(roles_allow)})"
                )
            if not task.agent_id:
                errors.append(f"task {task.id}: agent_id is required")
            if not task.instructions:
                errors.append(f"task {task.id}: instructions is required")
            for dep in task.depends_on:
                if dep not in task_map:
                    errors.append(f"task {task.id}: unknown depends_on {dep!r}")

        if graph.final.task_id and graph.final.task_id not in task_map:
            errors.append(f"final.task_id not found: {graph.final.task_id!r}")

        if graph.final.merge_tasks:
            for tid in graph.final.merge_tasks:
                if tid not in task_map:
                    errors.append(f"final.merge_tasks contains unknown task id: {tid!r}")

        if errors:
            raise TaskGraphValidationError("; ".join(errors))

        _assert_acyclic(task_map)
        _assert_parallel_groups_within_limit(graph.tasks, max_parallel=self.max_parallel)


def _assert_acyclic(task_map: Mapping[str, TaskNode]) -> None:
    indegree: Dict[str, int] = {tid: 0 for tid in task_map}
    outgoing: Dict[str, List[str]] = {tid: [] for tid in task_map}

    for tid, task in task_map.items():
        for dep in task.depends_on:
            outgoing.setdefault(dep, []).append(tid)
            indegree[tid] = indegree.get(tid, 0) + 1

    queue = [tid for tid, deg in indegree.items() if deg == 0]
    visited = 0
    while queue:
        current = queue.pop()
        visited += 1
        for nxt in outgoing.get(current, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if visited != len(task_map):
        raise TaskGraphValidationError("task graph contains a cycle")


def _assert_parallel_groups_within_limit(
    tasks: Iterable[TaskNode], *, max_parallel: int
) -> None:
    if max_parallel <= 0:
        return
    groups: Dict[str, int] = {}
    for t in tasks:
        if t.parallel_group:
            groups[t.parallel_group] = groups.get(t.parallel_group, 0) + 1
    for group, count in groups.items():
        if count > max_parallel:
            raise TaskGraphValidationError(
                f"parallel_group {group!r} too large: {count} > {max_parallel}"
            )


__all__ = [
    "TaskArtifactSpec",
    "TaskGraph",
    "TaskGraphFinal",
    "TaskGraphValidationError",
    "TaskGraphValidator",
    "TaskInputs",
    "TaskLimits",
    "TaskNode",
]

