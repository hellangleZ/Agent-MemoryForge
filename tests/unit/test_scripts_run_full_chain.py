
from scripts import run_full_chain


class _FakeManager:
    def __init__(self, repo_root=None):
        self.started = []
        self.repo_root = repo_root

    def start(self, service, quiet=False):
        self.started.append((service.name, quiet))

    def stop_all(self):
        return None


def test_run_full_chain_once(monkeypatch, tmp_path):
    env_file = tmp_path / "main.env"
    env_file.write_text("FOO=bar\n", encoding="utf-8")

    manager = _FakeManager()
    monkeypatch.setattr(run_full_chain, "FullChainManager", lambda repo_root=None: manager)
    monkeypatch.setattr(run_full_chain, "_wait_http_ok", lambda *a, **k: None)
    monkeypatch.setattr(run_full_chain.subprocess, "check_call", lambda *a, **k: 0)
    monkeypatch.setattr(run_full_chain.signal, "signal", lambda *a, **k: None)

    args = run_full_chain.FullChainArgs(
        main_env=env_file,
        planner_env=tmp_path / "planner.env",
        distill_env=tmp_path / "distill.env",
        memory_url="http://127.0.0.1:8001",
        gateway_port=8080,
        no_planner=True,
        no_distill=True,
        no_demo=True,
        once=True,
        verbose=False,
    )

    result = run_full_chain.run_full_chain(args)
    assert result == 0
    assert any(name == "memory_service" for name, _ in manager.started)
    assert any(name == "gateway" for name, _ in manager.started)
