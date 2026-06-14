from fastapi.testclient import TestClient

import agent_memory_service.app as app_mod


class _FakeOrchestrator:
    def stats(self, tenant_id, workspace_id):
        return {"tenant_id": tenant_id, "workspace_id": workspace_id}

    def write_memory(self, tenant_id, workspace_id, payload):
        return {"entry_id": "e1", "path": "memory/test.md"}

    def search_memory(self, tenant_id, workspace_id, payload):
        return {"hits": [], "payload": payload}

    def read_memory(self, tenant_id, workspace_id, payload):
        return {"tier": payload["tier"]}

    def get_memory(self, tenant_id, workspace_id, payload):
        return {"path": payload["path"], "content": "ok"}

    def rebuild_index(self, tenant_id, workspace_id):
        return {"rebuild": True}

    def status(self):
        return {"file_root": "/tmp/memory"}


def test_memory_service_canonical_endpoints(monkeypatch):
    monkeypatch.setattr(app_mod, "MemoryOrchestrator", _FakeOrchestrator)
    monkeypatch.setenv("AGENT_MEMORY_SERVICE_ALLOW_UNAUTHENTICATED_LOCAL_DEV", "1")
    app = app_mod.create_app()
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.post("/store", json={}).status_code == 404
    assert client.post("/retrieve", json={}).status_code == 404
    assert client.post("/clear", json={}).status_code == 404

    stats_resp = client.post(
        "/v1/memory/stats",
        json={"tenant_id": "t", "workspace_id": "w"},
    )
    assert stats_resp.json()["data"]["tenant_id"] == "t"

    write_resp = client.post(
        "/v1/memory/write",
        json={
            "tenant_id": "t",
            "workspace_id": "w",
            "tier": "semantic",
            "scope": "project",
            "content": "hello",
            "metadata": {},
        },
    )
    assert write_resp.json()["data"]["entry_id"] == "e1"

    search_resp = client.post(
        "/v1/memory/search",
        json={
            "tenant_id": "t",
            "workspace_id": "w",
            "query": "hello",
            "memory_kinds": ["semantic_fact"],
            "path_prefixes": ["memory/"],
        },
    )
    payload = search_resp.json()["data"]["payload"]
    assert payload["memory_kinds"] == ["semantic_fact"]
    assert payload["path_prefixes"] == ["memory/"]

    read_resp = client.post(
        "/v1/memory/read",
        json={"tenant_id": "t", "workspace_id": "w", "tier": "preferences", "key": "lang"},
    )
    assert read_resp.json()["data"]["tier"] == "preferences"

    get_resp = client.post(
        "/v1/memory/get",
        json={"tenant_id": "t", "workspace_id": "w", "path": "memory/test.md"},
    )
    assert get_resp.json()["data"]["content"] == "ok"

    rebuild_resp = client.post(
        "/v1/memory/index/rebuild",
        json={"tenant_id": "t", "workspace_id": "w"},
    )
    assert rebuild_resp.json()["status"] == "success"


def test_memory_service_internal_api_key_is_enforced(monkeypatch):
    monkeypatch.setattr(app_mod, "MemoryOrchestrator", _FakeOrchestrator)
    monkeypatch.setenv("MEMORY_SERVICE_API_KEY", "internal-test-key")
    app = app_mod.create_app()
    client = TestClient(app)

    denied = client.post(
        "/v1/memory/stats",
        json={"tenant_id": "t", "workspace_id": "w"},
    )
    assert denied.status_code == 401

    allowed = client.post(
        "/v1/memory/stats",
        headers={"x-agent-memory-service-key": "internal-test-key"},
        json={"tenant_id": "t", "workspace_id": "w"},
    )
    assert allowed.status_code == 200

    status_denied = client.get("/v1/memory/status")
    assert status_denied.status_code == 401

    status_allowed = client.get(
        "/v1/memory/status",
        headers={"x-agent-memory-service-key": "internal-test-key"},
    )
    assert status_allowed.status_code == 200


def test_memory_service_requires_internal_api_key_by_default(monkeypatch):
    monkeypatch.setattr(app_mod, "MemoryOrchestrator", _FakeOrchestrator)
    monkeypatch.delenv("MEMORY_SERVICE_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_MEMORY_SERVICE_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_MEMORY_SERVICE_ALLOW_UNAUTHENTICATED_LOCAL_DEV", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    app = app_mod.create_app()
    client = TestClient(app)

    resp = client.post(
        "/v1/memory/stats",
        json={"tenant_id": "t", "workspace_id": "w"},
    )

    assert resp.status_code == 500
    assert "AGENT_MEMORY_SERVICE_API_KEY" in resp.json()["detail"]


def test_memory_service_requires_internal_api_key_in_production(monkeypatch):
    monkeypatch.setattr(app_mod, "MemoryOrchestrator", _FakeOrchestrator)
    monkeypatch.delenv("MEMORY_SERVICE_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_MEMORY_SERVICE_API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    app = app_mod.create_app()
    client = TestClient(app)

    resp = client.post(
        "/v1/memory/stats",
        json={"tenant_id": "t", "workspace_id": "w"},
    )

    assert resp.status_code == 500
    assert "AGENT_MEMORY_SERVICE_API_KEY" in resp.json()["detail"]
