import types

from scripts import run_task_graph


class _FakeProvider:
    def __init__(self):
        self.provider = "fake"


class _FakeMemoryClient:
    def __init__(self, url):
        self.url = url

    def with_scope(self, tenant_id, workspace_id):
        self.scope = (tenant_id, workspace_id)
        return self


class _FakeTeam:
    def __init__(self):
        self.agents = {"planner": "agent"}


class _FakePlanner:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs


class _FakeOrchestrator:
    def __init__(self, agents=None, planner=None, artifacts_enabled=True, isolation_mode=None):
        self.agents = agents
        self.planner = planner
        self.artifacts_enabled = artifacts_enabled
        self.isolation_mode = isolation_mode

    def run(self, message):
        return {"status": "ok", "message": message}


def test_run_task_graph_main(monkeypatch, tmp_path, capfd):
    planner_md = tmp_path / "planner.md"
    planner_md.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(run_task_graph, "resolve_llm_provider", lambda *a, **k: _FakeProvider())
    monkeypatch.setattr(run_task_graph, "MemoryClient", _FakeMemoryClient)
    monkeypatch.setattr(run_task_graph, "build_team_runtime", lambda *a, **k: _FakeTeam())
    monkeypatch.setattr(run_task_graph, "LLMTaskGraphPlanner", _FakePlanner)
    monkeypatch.setattr(run_task_graph, "TaskGraphOrchestrator", _FakeOrchestrator)
    monkeypatch.setattr(run_task_graph, "Runtime", lambda *a, **k: types.SimpleNamespace())
    monkeypatch.setattr(run_task_graph, "Settings", lambda: types.SimpleNamespace())

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_task_graph.py",
            "--message",
            "hi",
            "--planner-md",
            str(planner_md),
            "--no-artifacts",
        ],
    )

    result = run_task_graph.main()
    assert result == 0
    out = capfd.readouterr().out
    assert "status" in out
