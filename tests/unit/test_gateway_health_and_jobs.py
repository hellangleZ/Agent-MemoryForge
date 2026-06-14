import pytest
from fastapi.testclient import TestClient

from agent_runtime.product import agent_gateway


def test_healthz_ok():
    assert agent_gateway.healthz() == {"ok": True}


def test_readyz_all_ok(mocker):
    mocker.patch.object(agent_gateway, "_redis_health", return_value={"ok": True})
    mocker.patch.object(agent_gateway, "_neo4j_health", return_value={"ok": True})
    mocker.patch.object(
        agent_gateway, "_embedding_service_health", return_value={"ok": True}
    )
    mocker.patch.object(
        agent_gateway, "_memory_service_health", return_value={"ok": True}
    )
    resp = agent_gateway.readyz()
    assert resp["ok"] is True
    assert resp["dependencies"]["redis"]["ok"] is True


def test_readyz_returns_503_when_dependency_fails(mocker):
    mocker.patch.object(
        agent_gateway, "_redis_health", return_value={"ok": False, "detail": "down"}
    )
    mocker.patch.object(agent_gateway, "_neo4j_health", return_value={"ok": True})
    mocker.patch.object(
        agent_gateway, "_embedding_service_health", return_value={"ok": True}
    )
    mocker.patch.object(
        agent_gateway, "_memory_service_health", return_value={"ok": True}
    )
    with pytest.raises(Exception) as excinfo:
        agent_gateway.readyz()
    assert getattr(excinfo.value, "status_code", None) == 503


def test_fake_jobs_api_is_not_exposed(monkeypatch):
    monkeypatch.setenv("AGENT_GATEWAY_API_KEY", "k")
    client = TestClient(agent_gateway.app)

    resp = client.post("/v1/jobs", headers={"x-api-key": "k"}, json={"action": "noop"})

    assert resp.status_code == 404
