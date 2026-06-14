from __future__ import annotations

import pytest

from agent_memory_framework.task_graph import (
    TaskArtifactSpec,
    TaskGraph,
    TaskGraphFinal,
    TaskGraphValidationError,
    TaskGraphValidator,
    TaskInputs,
    TaskLimits,
    TaskNode,
)


def _graph(tasks, *, final_task_id: str = "t_final") -> TaskGraph:
    return TaskGraph(
        version="v1",
        goal="ship it",
        constraints=["must be deterministic"],
        tasks=list(tasks),
        final=TaskGraphFinal(task_id=final_task_id, merge_tasks=[], format="report"),
    )


def test_validator_rejects_unknown_role() -> None:
    graph = _graph(
        [
            TaskNode(
                id="t1",
                role="unknown",
                agent_id="a",
                depends_on=[],
                instructions="do it",
                inputs=TaskInputs(artifacts_from=[]),
                artifact=TaskArtifactSpec(name="a1"),
                limits=TaskLimits(),
            )
        ],
        final_task_id="t1",
    )
    with pytest.raises(TaskGraphValidationError):
        TaskGraphValidator().validate(graph)


def test_validator_rejects_unknown_dependency() -> None:
    graph = _graph(
        [
            TaskNode(
                id="t1",
                role="research",
                agent_id="a",
                depends_on=["missing"],
                instructions="do it",
                inputs=TaskInputs(artifacts_from=[]),
                artifact=TaskArtifactSpec(name="a1"),
                limits=TaskLimits(),
            )
        ],
        final_task_id="t1",
    )
    with pytest.raises(TaskGraphValidationError):
        TaskGraphValidator().validate(graph)


def test_validator_rejects_cycles() -> None:
    graph = _graph(
        [
            TaskNode(
                id="a",
                role="research",
                agent_id="a",
                depends_on=["b"],
                instructions="a",
                inputs=TaskInputs(artifacts_from=[]),
                artifact=TaskArtifactSpec(name="a1"),
                limits=TaskLimits(),
            ),
            TaskNode(
                id="b",
                role="research",
                agent_id="b",
                depends_on=["a"],
                instructions="b",
                inputs=TaskInputs(artifacts_from=[]),
                artifact=TaskArtifactSpec(name="b1"),
                limits=TaskLimits(),
            ),
        ],
        final_task_id="a",
    )
    with pytest.raises(TaskGraphValidationError):
        TaskGraphValidator().validate(graph)
