import time

import pytest

from agent_memory_framework.subagents import SubAgentError, SubAgentRunner


class _FakeAgent:
    def __init__(self, *, name: str, delay_s: float = 0.0, boom: bool = False):
        self._name = name
        self._delay_s = float(delay_s)
        self._boom = bool(boom)
        self.seen: list[str] = []

    def run_turn(self, prompt: str) -> str:
        self.seen.append(prompt)
        if self._delay_s:
            time.sleep(self._delay_s)
        if self._boom:
            raise RuntimeError("boom")
        return f"{self._name}:{prompt}"


@pytest.mark.unit
def test_subagent_runner_preserves_caller_order(monkeypatch):
    # Make max_workers deterministic.
    monkeypatch.setenv("AGENT_MEMORY_PARALLEL_WORKERS", "2")

    runner = SubAgentRunner()
    agents = {
        "a1": _FakeAgent(name="a1", delay_s=0.02),
        "a2": _FakeAgent(name="a2", delay_s=0.0),
    }
    tasks = [
        ("t1", "research", "a1", "p1"),
        ("t2", "implement", "a2", "p2"),
        ("t3", "review", "a1", "p3"),
    ]

    results = runner.run_many(tasks, agents=agents)
    assert [r.task_id for r in results] == ["t1", "t2", "t3"]
    assert [r.agent_id for r in results] == ["a1", "a2", "a1"]
    assert results[0].output_text == "a1:p1"
    assert results[1].output_text == "a2:p2"
    assert results[2].output_text == "a1:p3"


@pytest.mark.unit
def test_subagent_runner_unknown_agent_raises():
    runner = SubAgentRunner(max_workers=1)
    with pytest.raises(SubAgentError):
        runner.run_many([("t1", "research", "missing", "p")], agents={})


@pytest.mark.unit
def test_subagent_runner_propagates_agent_errors():
    runner = SubAgentRunner(max_workers=1)
    agents = {"a1": _FakeAgent(name="a1", boom=True)}
    with pytest.raises(RuntimeError):
        runner.run_many([("t1", "research", "a1", "p")], agents=agents)
