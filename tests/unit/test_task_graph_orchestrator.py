from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent_memory_framework.orchestrator import TaskGraphOrchestrator
from agent_memory_framework.runtime import Runtime
from agent_memory_framework.settings import Settings
from agent_memory_framework.task_graph import (
    TaskArtifactSpec,
    TaskGraph,
    TaskGraphFinal,
    TaskInputs,
    TaskLimits,
    TaskNode,
)


class _FakeMemoryClient:
    def __init__(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        writes: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.workspace_id = workspace_id
        self._writes = writes if writes is not None else []

    def with_scope(self, *, tenant_id: str, workspace_id: str) -> "_FakeMemoryClient":
        return _FakeMemoryClient(
            tenant_id=tenant_id, workspace_id=workspace_id, writes=self._writes
        )

    def memory_write(
        self,
        *,
        tier: str,
        scope: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        target: Optional[str] = None,
        tenant_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._writes.append(
            {
                "tenant_id": tenant_id or self.tenant_id,
                "workspace_id": workspace_id or self.workspace_id,
                "tier": tier,
                "scope": scope,
                "content": content,
                "metadata": metadata or {},
                "target": target,
                "task_id": task_id,
            }
        )
        return {
            "status": "success",
            "data": {
                "entry_id": "e_" + (task_id or "x"),
                "path": f"wm/{task_id}.md" if task_id else "wm/x.md",
                "line_start": 1,
                "created_at": "2026-01-01T00:00:00Z",
            },
        }

    @property
    def writes(self) -> List[Dict[str, Any]]:
        return list(self._writes)


class _FakeAgent:
    def __init__(self, *, agent_id: str, memory_client: _FakeMemoryClient) -> None:
        self.agent_id = agent_id
        self.prompts: List[str] = []
        self.runtime = Runtime(
            agent_id=agent_id,
            user_id="u",
            memory_client=memory_client,  # type: ignore[arg-type]
            llm_provider=None,  # type: ignore[arg-type]
            conversation_id="c",
            settings=Settings(),
        )

    def run_turn(self, user_query: str) -> str:
        self.prompts.append(user_query)
        return f"{self.agent_id} OUTPUT"


def test_orchestrator_passes_upstream_artifacts_and_persists_wm_per_role() -> None:
    writes: List[Dict[str, Any]] = []
    base_client = _FakeMemoryClient(tenant_id="t1", workspace_id="ws1", writes=writes)

    agents = {
        "researcher": _FakeAgent(agent_id="researcher", memory_client=base_client),
        "implementer": _FakeAgent(agent_id="implementer", memory_client=base_client),
        "synthesizer": _FakeAgent(agent_id="synthesizer", memory_client=base_client),
    }

    graph = TaskGraph(
        version="v1",
        goal="do the thing",
        constraints=["persist artifacts"],
        tasks=[
            TaskNode(
                id="t1",
                role="research",
                agent_id="researcher",
                depends_on=[],
                instructions="research",
                inputs=TaskInputs(artifacts_from=[]),
                artifact=TaskArtifactSpec(name="research"),
                limits=TaskLimits(),
            ),
            TaskNode(
                id="t2",
                role="implement",
                agent_id="implementer",
                depends_on=["t1"],
                instructions="implement",
                inputs=TaskInputs(artifacts_from=["t1"]),
                artifact=TaskArtifactSpec(name="impl"),
                limits=TaskLimits(),
            ),
            TaskNode(
                id="t3",
                role="synthesize",
                agent_id="synthesizer",
                depends_on=["t2"],
                instructions="final",
                inputs=TaskInputs(artifacts_from=["t2"]),
                artifact=TaskArtifactSpec(name="final"),
                limits=TaskLimits(),
            ),
        ],
        final=TaskGraphFinal(task_id="t3", merge_tasks=["t1", "t2"], format="report"),
    )

    orch = TaskGraphOrchestrator(
        agents=agents,
        planner=None,
        artifacts_enabled=True,
        isolation_mode="per_role",
    )

    result = orch.execute(graph, user_query="hi").as_dict()
    assert result["final"] == "synthesizer OUTPUT"

    # Implementer should see the upstream research artifact content.
    implementer_prompt = agents["implementer"].prompts[-1]
    assert "Upstream artifacts" in implementer_prompt
    assert "researcher OUTPUT" in implementer_prompt

    # Artifacts are persisted as WM under per-role derived workspaces.
    artifact_writes = [w for w in writes if w.get("metadata", {}).get("kind") == "task_artifact"]
    snapshot_writes = [w for w in writes if w.get("metadata", {}).get("kind") == "task_run_snapshot"]

    assert len(artifact_writes) == 3
    workspaces = {w["workspace_id"] for w in artifact_writes}
    assert workspaces == {
        "ws1__role__researcher",
        "ws1__role__implementer",
        "ws1__role__synthesizer",
    }

    # Task list snapshots are persisted to the shared base workspace.
    assert snapshot_writes
    assert {w["workspace_id"] for w in snapshot_writes} == {"ws1"}
    assert "- [x] t1" in snapshot_writes[-1]["content"]
    assert "- [x] t3" in snapshot_writes[-1]["content"]

    # Citations are returned for persisted artifacts.
    citations = [a["citation"] for a in result["artifacts"] if a.get("citation")]
    assert citations
