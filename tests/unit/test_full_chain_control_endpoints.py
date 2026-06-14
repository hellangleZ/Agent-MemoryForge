from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agent_runtime.product.auth_tokens import create_access_token


def _headers() -> dict[str, str]:
    token = create_access_token(sub="platform_admin", tenant_id="admin", expires_in_s=60)
    return {
        "x-api-key": "k",
        "authorization": f"Bearer {token}",
        "x-workspace-id": "ws1",
    }


def _user_headers() -> dict[str, str]:
    token = create_access_token(sub="u1", tenant_id="t1", expires_in_s=60)
    return {
        "x-api-key": "k",
        "authorization": f"Bearer {token}",
        "x-workspace-id": "ws1",
    }


def test_full_chain_control_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FULL_CHAIN_CONTROL_ENABLED", raising=False)
    from agent_runtime.product.agent_gateway import app

    client = TestClient(app)
    resp = client.get("/v1/full-chain/status")
    assert resp.status_code in {401, 403}


def test_full_chain_status_requires_api_key_when_configured(monkeypatch):
    monkeypatch.setenv("AGENT_GATEWAY_API_KEY", "k")
    monkeypatch.setenv("FULL_CHAIN_CONTROL_ENABLED", "1")
    from agent_runtime.product.agent_gateway import app

    client = TestClient(app)
    resp = client.get("/v1/full-chain/status")
    assert resp.status_code == 401
    resp2 = client.get("/v1/full-chain/status", headers={"x-api-key": "k"})
    assert resp2.status_code in {400, 401}

    # Provide RBAC headers.
    resp3 = client.get("/v1/full-chain/status", headers=_headers())
    assert resp3.status_code == 200
    assert resp3.json()["status"] == "success"


def test_full_chain_status_requires_platform_admin(monkeypatch):
    monkeypatch.setenv("AGENT_GATEWAY_API_KEY", "k")
    monkeypatch.setenv("FULL_CHAIN_CONTROL_ENABLED", "1")
    from agent_runtime.product.agent_gateway import app

    client = TestClient(app)
    resp = client.get("/v1/full-chain/status", headers=_user_headers())

    assert resp.status_code == 403
    assert "platform admin" in resp.json()["detail"]


def test_full_chain_start_disabled_without_flag(monkeypatch):
    monkeypatch.setenv("AGENT_GATEWAY_API_KEY", "k")
    monkeypatch.delenv("FULL_CHAIN_CONTROL_ENABLED", raising=False)
    from agent_runtime.product.agent_gateway import app

    client = TestClient(app)
    resp = client.post("/v1/full-chain/start", headers=_headers(), json={"restart": True})
    assert resp.status_code == 403


def test_full_chain_start_rejects_invalid_ports(monkeypatch):
    monkeypatch.setenv("AGENT_GATEWAY_API_KEY", "k")
    monkeypatch.setenv("FULL_CHAIN_CONTROL_ENABLED", "1")
    from agent_runtime.product.agent_gateway import app

    client = TestClient(app)
    resp = client.post(
        "/v1/full-chain/start",
        headers=_headers(),
        json={"memory_port": 1, "gateway_port": 2, "restart": True, "require_dependencies_healthy": False},
    )
    assert resp.status_code == 400


def test_full_chain_services_requires_control_flag(monkeypatch):
    monkeypatch.setenv("AGENT_GATEWAY_API_KEY", "k")
    monkeypatch.delenv("FULL_CHAIN_CONTROL_ENABLED", raising=False)
    from agent_runtime.product.agent_gateway import app

    client = TestClient(app)
    resp = client.get("/v1/full-chain/services", headers=_headers())
    assert resp.status_code == 403


def test_full_chain_logs_requires_control_flag(monkeypatch):
    monkeypatch.setenv("AGENT_GATEWAY_API_KEY", "k")
    monkeypatch.delenv("FULL_CHAIN_CONTROL_ENABLED", raising=False)
    from agent_runtime.product.agent_gateway import app

    client = TestClient(app)
    resp = client.get("/v1/full-chain/logs", headers=_headers(), params={"service": "gateway"})
    assert resp.status_code == 403


def test_full_chain_logs_stream_disabled_without_flag(monkeypatch):
    monkeypatch.setenv("AGENT_GATEWAY_API_KEY", "k")
    monkeypatch.delenv("FULL_CHAIN_CONTROL_ENABLED", raising=False)
    from agent_runtime.product.agent_gateway import app

    client = TestClient(app)
    resp = client.get(
        "/v1/full-chain/logs/stream",
        headers=_headers(),
        params={"service": "gateway", "tail": 0},
    )
    assert resp.status_code == 403


def test_full_chain_logs_stream_emits_tail_lines(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_GATEWAY_API_KEY", "k")
    monkeypatch.setenv("FULL_CHAIN_CONTROL_ENABLED", "1")

    # Write a fake service log to the scoped location under repository root.
    # The gateway stores logs under logs/full_chain/t_<tenant>__ws_<workspace>/.
    repo_root = Path(__file__).resolve().parents[2]
    logs_dir = repo_root / "logs" / "full_chain" / "t_admin__ws_ws1"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "gateway.log"
    log_path.write_text("a\n" "b\n" "c\n", encoding="utf-8")

    from agent_runtime.product.agent_gateway import app

    client = TestClient(app)
    with client.stream(
        "GET",
        "/v1/full-chain/logs/stream",
        headers=_headers(),
        params={"service": "gateway", "tail": 2, "interval_s": 5.0, "max_events": 2},
    ) as resp:
        assert resp.status_code == 200
        body = resp.read()
        assert b"data: b" in body
        assert b"data: c" in body
