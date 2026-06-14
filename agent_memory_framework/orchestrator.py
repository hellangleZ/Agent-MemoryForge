from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from agent_memory_framework.llm import LLMProvider
from agent_memory_framework.subagents import SubAgentRunner
from agent_memory_framework.task_graph import (
    TaskGraph,
    TaskGraphValidationError,
    TaskGraphValidator,
    TaskNode,
)


@dataclass(frozen=True)
class ArtifactRef:
    task_id: str
    name: str
    role: str
    agent_id: str
    content: str
    entry_id: Optional[str] = None
    path: Optional[str] = None
    line_start: Optional[int] = None

    @property
    def citation(self) -> Optional[str]:
        if self.path and self.line_start:
            return f"{self.path}#L{self.line_start}"
        return None


class TaskGraphPlanError(RuntimeError):
    pass


class TaskGraphExecutionError(RuntimeError):
    pass


class LLMTaskGraphPlanner:
    def __init__(self, *, llm_provider: LLMProvider, system_instructions: str) -> None:
        self._llm = llm_provider
        self._system_instructions = system_instructions

    def plan(self, user_query: str, *, trace_id: str | None = None) -> TaskGraph:
        messages = [
            {"role": "system", "content": self._system_instructions},
            {"role": "user", "content": user_query},
        ]
        result = self._llm.generate(messages, temperature=0.2, trace_id=trace_id)
        text = (result.text or "").strip()
        json_text = _extract_json_object(text)
        try:
            return TaskGraph.from_json(json_text)
        except Exception as exc:
            raise TaskGraphPlanError(
                f"Failed to parse TaskGraph JSON: {exc}"
            ) from exc

    def replan(
        self, user_query: str, *, error: str, trace_id: str | None = None
    ) -> TaskGraph:
        prompt = (
            f"{user_query}\n\n"
            f"Planner error:\n{error}\n\n"
            "Return a corrected TaskGraph JSON only."
        )
        return self.plan(prompt, trace_id=trace_id)


@dataclass(frozen=True)
class OrchestrationResult:
    run_id: str
    goal: str
    final_text: str
    artifacts: List[ArtifactRef]
    steps: List[Dict[str, Any]]
    orchestration_trace: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "final": self.final_text,
            "artifacts": [
                {
                    "task_id": a.task_id,
                    "name": a.name,
                    "role": a.role,
                    "agent_id": a.agent_id,
                    "entry_id": a.entry_id,
                    "path": a.path,
                    "line_start": a.line_start,
                    "citation": a.citation,
                    "content": a.content,
                }
                for a in self.artifacts
            ],
            "steps": list(self.steps),
            "orchestration_trace": dict(self.orchestration_trace),
        }


class TaskGraphOrchestrator:
    """Dynamic TaskGraph orchestration.

    - Planner (LLM) emits a TaskGraph JSON program.
    - Executor validates and runs the DAG, with optional parallel groups.
    - Each step may persist its artifact to File-First memory (Markdown truth).
    """

    def __init__(
        self,
        *,
        agents: Mapping[str, Any],
        planner: Optional[LLMTaskGraphPlanner] = None,
        validator: Optional[TaskGraphValidator] = None,
        artifacts_enabled: bool = True,
        tracking_enabled: bool = True,
        isolation_mode: str = "shared",
        max_replans: int = 1,
    ) -> None:
        if not agents:
            raise ValueError("agents must be non-empty")
        self._agents = dict(agents)
        self._planner = planner
        self._validator = validator or TaskGraphValidator()
        self._artifacts_enabled = bool(artifacts_enabled)
        self._tracking_enabled = bool(tracking_enabled)
        self._isolation_mode = isolation_mode
        self._max_replans = int(max_replans)

    def run(
        self,
        user_query: str,
        *,
        trace_id: str | None = None,
    ) -> Dict[str, Any]:
        if self._planner is None:
            raise TaskGraphPlanError("No planner configured")

        last_error: str | None = None
        for attempt in range(self._max_replans + 1):
            graph = (
                self._planner.replan(user_query, error=last_error or "", trace_id=trace_id)
                if attempt > 0 and last_error
                else self._planner.plan(user_query, trace_id=trace_id)
            )
            try:
                self._validator.validate(graph)
                result = self.execute(graph, user_query=user_query, trace_id=trace_id)
                return result.as_dict()
            except (TaskGraphValidationError, TaskGraphExecutionError) as exc:
                last_error = str(exc)
                if attempt >= self._max_replans:
                    raise

        raise TaskGraphPlanError("Failed to plan a valid TaskGraph")

    def execute(
        self,
        graph: TaskGraph,
        *,
        user_query: str,
        trace_id: str | None = None,
    ) -> OrchestrationResult:
        run_id = uuid.uuid4().hex
        started_at = time.time()

        task_map: Dict[str, TaskNode] = {t.id: t for t in graph.tasks}
        done: Dict[str, str] = {}
        artifacts: Dict[str, ArtifactRef] = {}
        steps: List[Dict[str, Any]] = []
        snapshots: List[ArtifactRef] = []

        runner = SubAgentRunner()

        def _tracking_client() -> Any | None:
            if not self._tracking_enabled:
                return None
            for agent in self._agents.values():
                runtime = getattr(agent, "runtime", None)
                memory_client = getattr(runtime, "memory_client", None) if runtime else None
                if memory_client is None or not hasattr(memory_client, "memory_write"):
                    continue
                tenant_id = getattr(memory_client, "tenant_id", None)
                workspace_id = getattr(memory_client, "workspace_id", None)
                if not tenant_id or not workspace_id:
                    continue
                if self._isolation_mode == "per_role":
                    base_ws = workspace_id.split("__role__", 1)[0]
                    if hasattr(memory_client, "with_scope"):
                        return memory_client.with_scope(tenant_id=tenant_id, workspace_id=base_ws)
                return memory_client
            return None

        def _task_status_md(status: Mapping[str, str]) -> str:
            lines: List[str] = []
            lines.append(f"# Task Run {run_id}")
            lines.append("")
            lines.append(f"Goal: {graph.goal}")
            lines.append(f"Isolation: {self._isolation_mode}")
            lines.append(f"Artifacts enabled: {self._artifacts_enabled}")
            lines.append("")
            lines.append("## Tasks")
            for task_id in sorted(task_map.keys()):
                task = task_map[task_id]
                state = status.get(task_id, "pending")
                checkbox = "[x]" if state == "done" else "[~]" if state == "running" else "[ ]"
                suffix = ""
                if state == "done" and task_id in artifacts and artifacts[task_id].citation:
                    suffix = f" ({artifacts[task_id].citation})"
                lines.append(
                    f"- {checkbox} {task_id} ({task.role}/{task.agent_id}){suffix}"
                )
            lines.append("")
            return "\n".join(lines)

        def _persist_snapshot(seq: int, status: Mapping[str, str]) -> None:
            client = _tracking_client()
            if client is None:
                return
            meta = {
                "kind": "task_run_snapshot",
                "run_id": run_id,
                "seq": seq,
                "tasks": len(task_map),
                "isolation_mode": self._isolation_mode,
            }
            task_id = _safe_id(f"orchestr_{run_id}__task_list__{seq:04d}")
            res = client.memory_write(
                tier="wm",
                scope="orchestration",
                content=_task_status_md(status),
                metadata=meta,
                target="wm",
                task_id=task_id,
            )
            data = res.get("data") if isinstance(res, dict) else None
            if isinstance(data, dict):
                snapshots.append(
                    ArtifactRef(
                        task_id=task_id,
                        name="task_list",
                        role="orchestrator",
                        agent_id="orchestrator",
                        content=_task_status_md(status),
                        entry_id=str(data.get("entry_id") or "") or None,
                        path=str(data.get("path") or "") or None,
                        line_start=int(data.get("line_start") or 0) or None,
                    )
                )

        def _task_prompt(task: TaskNode) -> str:
            upstream: List[ArtifactRef] = []
            for src in task.inputs.artifacts_from:
                if src in artifacts:
                    upstream.append(artifacts[src])

            parts: List[str] = []
            parts.append(f"Goal: {graph.goal}")
            if graph.constraints:
                parts.append("Constraints:\n- " + "\n- ".join(graph.constraints))
            parts.append(f"Role: {task.role}")
            parts.append(f"Task: {task.id}")
            parts.append(f"Instructions:\n{task.instructions}")
            if upstream:
                parts.append("Upstream artifacts:")
                for a in upstream:
                    cite = f" ({a.citation})" if a.citation else ""
                    parts.append(f"- {a.task_id}/{a.name}{cite}:\n{a.content}".rstrip())
            parts.append(f"User query:\n{user_query}")
            return "\n\n".join(parts).strip() + "\n"

        def _persist_artifact(task: TaskNode, output_text: str) -> ArtifactRef:
            spec = task.artifact or None
            name = spec.name if spec else "artifact"
            ref = ArtifactRef(
                task_id=task.id,
                name=name,
                role=task.role,
                agent_id=task.agent_id,
                content=output_text,
            )
            if not self._artifacts_enabled or not spec or not spec.persist:
                return ref

            agent = self._agents.get(task.agent_id)
            if agent is None or not hasattr(agent, "runtime"):
                raise TaskGraphExecutionError(f"agent {task.agent_id!r} missing runtime")
            memory_client = getattr(agent.runtime, "memory_client", None)
            if memory_client is None or not hasattr(memory_client, "memory_write"):
                raise TaskGraphExecutionError("memory_write is required for artifacts")

            tenant_id = getattr(memory_client, "tenant_id", None)
            workspace_id = getattr(memory_client, "workspace_id", None)
            if not tenant_id or not workspace_id:
                raise TaskGraphExecutionError(
                    "memory client must be scoped with tenant_id/workspace_id for artifacts"
                )

            write_client = memory_client
            if self._isolation_mode == "per_role":
                base_ws = workspace_id.split("__role__", 1)[0]
                derived_ws = f"{base_ws}__role__{task.agent_id}"
                if hasattr(memory_client, "with_scope"):
                    write_client = memory_client.with_scope(
                        tenant_id=tenant_id, workspace_id=derived_ws
                    )

            wm_task_id = _safe_id(f"orchestr_{run_id}__{task.id}__{name}")
            meta = {
                "kind": "task_artifact",
                "run_id": run_id,
                "task_id": task.id,
                "role": task.role,
                "agent_id": task.agent_id,
                "depends_on": list(task.depends_on),
                "artifact_name": name,
            }
            res = write_client.memory_write(
                tier=str(spec.tier or "wm"),
                scope=str(spec.scope or "orchestration"),
                content=output_text,
                metadata=meta,
                target="wm",
                task_id=wm_task_id,
            )
            data = res.get("data") if isinstance(res, dict) else None
            if isinstance(data, dict):
                return ArtifactRef(
                    task_id=task.id,
                    name=name,
                    role=task.role,
                    agent_id=task.agent_id,
                    content=output_text,
                    entry_id=str(data.get("entry_id") or "") or None,
                    path=str(data.get("path") or "") or None,
                    line_start=int(data.get("line_start") or 0) or None,
                )
            return ref

        seq = 0
        status: Dict[str, str] = {tid: "pending" for tid in task_map}
        _persist_snapshot(seq, status)

        while len(done) < len(task_map):
            runnable = [
                t
                for t in task_map.values()
                if t.id not in done and all(dep in done for dep in t.depends_on)
            ]
            if not runnable:
                missing = [tid for tid in task_map if tid not in done]
                raise TaskGraphExecutionError(
                    f"deadlock: remaining tasks not runnable: {missing}"
                )

            # Deterministic batching: group by parallel_group, then by id.
            runnable.sort(key=lambda t: (t.parallel_group or "", t.id))
            group_key = runnable[0].parallel_group
            batch = [t for t in runnable if t.parallel_group == group_key]

            for t in batch:
                status[t.id] = "running"
            seq += 1
            _persist_snapshot(seq, status)

            prompts = [(t.id, t.role, t.agent_id, _task_prompt(t)) for t in batch]
            t0 = time.time()
            if len(batch) == 1:
                # Avoid threadpool overhead for singletons.
                t = batch[0]
                agent = self._agents.get(t.agent_id)
                if agent is None:
                    raise TaskGraphExecutionError(f"unknown agent_id={t.agent_id!r}")
                output = str(agent.run_turn(prompts[0][3]))
                results = [
                    (t, output),
                ]
            else:
                out = runner.run_many(prompts, agents=self._agents)
                results = [(task_map[r.task_id], r.output_text) for r in out]

            dt = time.time() - t0

            for task, output_text in results:
                done[task.id] = "ok"
                artifact = _persist_artifact(task, output_text)
                artifacts[task.id] = artifact
                status[task.id] = "done"
                steps.append(
                    {
                        "task_id": task.id,
                        "role": task.role,
                        "agent_id": task.agent_id,
                        "depends_on": list(task.depends_on),
                        "parallel_group": task.parallel_group,
                        "duration_s": dt,
                        "artifact": {
                            "name": artifact.name,
                            "entry_id": artifact.entry_id,
                            "path": artifact.path,
                            "line_start": artifact.line_start,
                            "citation": artifact.citation,
                        },
                    }
                )
            seq += 1
            _persist_snapshot(seq, status)

        final_task_id = graph.final.task_id
        if not final_task_id:
            # Fallback: pick a synthesize role task if present, else the last by id.
            synth = [t.id for t in graph.tasks if t.role == "synthesize"]
            final_task_id = sorted(synth)[-1] if synth else sorted(task_map.keys())[-1]

        final_artifact = artifacts.get(final_task_id)
        if final_artifact is None:
            raise TaskGraphExecutionError(f"final task not executed: {final_task_id!r}")

        trace = {
            "trace_id": trace_id,
            "isolation_mode": self._isolation_mode,
            "artifacts_enabled": self._artifacts_enabled,
            "tracking_enabled": self._tracking_enabled,
            "task_list_snapshots": [
                {
                    "entry_id": s.entry_id,
                    "path": s.path,
                    "line_start": s.line_start,
                    "citation": s.citation,
                }
                for s in snapshots
                if s.entry_id or s.path
            ],
            "tasks": len(task_map),
            "duration_s": time.time() - started_at,
        }
        return OrchestrationResult(
            run_id=run_id,
            goal=graph.goal,
            final_text=final_artifact.content,
            artifacts=[artifacts[tid] for tid in sorted(artifacts.keys())],
            steps=steps,
            orchestration_trace=trace,
        )


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_object(text: str) -> str:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    m = _JSON_BLOCK_RE.search(text)
    if m:
        return m.group(1).strip()
    # Best-effort: find first {...} block.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1].strip()
    return text


_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_\\-]+")


def _safe_id(value: str, *, max_len: int = 120) -> str:
    cleaned = _SAFE_ID_RE.sub("_", value).strip("_")
    if not cleaned:
        cleaned = uuid.uuid4().hex
    return cleaned[:max_len]


__all__ = [
    "ArtifactRef",
    "LLMTaskGraphPlanner",
    "OrchestrationResult",
    "TaskGraphExecutionError",
    "TaskGraphOrchestrator",
    "TaskGraphPlanError",
]
