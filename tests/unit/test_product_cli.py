import types
from pathlib import Path

from agent_runtime.product import cli


class _FakeResponse:
    def __init__(self, payload=None, lines=None):
        self._payload = payload or {}
        self._lines = lines or []

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=True):
        for line in self._lines:
            yield line


class _FakeRequests:
    def __init__(self, payload=None, lines=None):
        self.payload = payload or {}
        self.lines = lines or []
        self.last = None

    def get(self, url, headers=None, params=None, timeout=None, stream=False):
        self.last = ("get", url, headers, params, timeout, stream)
        return _FakeResponse(payload=self.payload, lines=self.lines)

    def post(self, url, headers=None, json=None, timeout=None):
        self.last = ("post", url, headers, json, timeout)
        return _FakeResponse(payload=self.payload)


class _FakeManager:
    def __init__(self, repo_root=None):
        self._repo_root = repo_root
        self._logs = {}

    def status(self):
        return {"gateway": types.SimpleNamespace(pid=123, log_path=Path("/tmp/log"))}

    def stop_all(self):
        return None

    def logs_path(self, service):
        return self._logs.get(service)

    def known_services(self):
        return ["gateway", "memory_service"]


def _install_fake_requests(monkeypatch, payload=None, lines=None):
    fake = _FakeRequests(payload=payload, lines=lines)
    monkeypatch.setitem(__import__("sys").modules, "requests", fake)
    return fake



def test_cli_full_chain_status_remote(monkeypatch, capfd):
    payload = {"data": {"gateway": {"pid": 1, "log_path": "/tmp/log"}}}
    _install_fake_requests(monkeypatch, payload=payload)
    result = cli.main(["full-chain-status"])
    assert result == 0
    out = capfd.readouterr().out
    assert "gateway" in out
    assert "pid=1" in out


def test_cli_full_chain_logs_stream_remote(monkeypatch, capfd):
    lines = ["data: hello", "event: error"]
    _install_fake_requests(monkeypatch, payload={}, lines=lines)
    result = cli.main(["full-chain-logs-stream", "gateway"])
    assert result == 0
    out = capfd.readouterr().out
    assert "hello" in out
    assert "event: error" in out


def test_cli_full_chain_logs_local(monkeypatch, tmp_path, capfd):
    log_path = tmp_path / "gateway.log"
    log_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    manager = _FakeManager()
    manager._logs["gateway"] = log_path

    monkeypatch.setattr(
        "agent_runtime.product.full_chain_manager.FullChainManager",
        lambda repo_root=None: manager,
    )

    result = cli.main(["full-chain-logs", "gateway", "--local", "--tail", "2"])
    assert result == 0
    out = capfd.readouterr().out
    assert "two" in out
    assert "three" in out


def test_cli_full_chain_services_local(monkeypatch, capfd):
    manager = _FakeManager()
    monkeypatch.setattr(
        "agent_runtime.product.full_chain_manager.FullChainManager",
        lambda repo_root=None: manager,
    )
    result = cli.main(["full-chain-services", "--local"])
    assert result == 0
    out = capfd.readouterr().out
    assert "gateway" in out
