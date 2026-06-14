import types

import pytest

from agent_runtime.product.gateway import portal_helpers as ph


def test_portal_config_load_save(monkeypatch, tmp_path):
    cfg_path = tmp_path / "portal.json"
    monkeypatch.setattr(ph, "_portal_config_path", lambda: cfg_path)
    ph._save_portal_config({"custom_agents": {"t": {"a": {"id": "a"}}}})
    loaded = ph._load_portal_config()
    assert loaded["custom_agents"]["t"]["a"]["id"] == "a"


def test_custom_agents_and_tool_policy():
    cfg = {}
    ph._save_custom_agent(cfg, tenant_id="t", agent_id="a", payload={"id": "a"})
    assert "a" in ph._custom_agents_for_tenant(cfg, "t")

    policy = ph._tool_policy_for_workspace(cfg, tenant_id="t", workspace_id="w")
    assert policy["allowlist"] == []

    ph._save_tool_policy(cfg, tenant_id="t", workspace_id="w", policy={"allowlist": ["x"]})
    policy = ph._tool_policy_for_workspace(cfg, tenant_id="t", workspace_id="w")
    assert policy["allowlist"] == ["x"]


def test_workspace_members():
    cfg = {}
    ph._save_workspace_members(cfg, tenant_id="t", members=[{"id": "u1"}])
    members = ph._workspace_members_for_tenant(cfg, "t")
    assert members[0]["id"] == "u1"


def test_bearer_token_from_headers():
    assert ph._bearer_token_from_headers("Bearer token", None) == "token"
    with pytest.raises(Exception):
        ph._bearer_token_from_headers("bad", None)


def test_me_from_access_token(monkeypatch):
    monkeypatch.setattr(ph, "decode_access_token", lambda *_: {"sub": "u1", "tenant_id": "t1"})
    me = ph._me_from_access_token("token")
    assert me.sub == "u1"
    assert me.tenant_id == "t1"


def test_dependency_health(monkeypatch):
    class _FakeRedis:
        def ping(self):
            return True

    class _FakeRedisHelper:
        @staticmethod
        def get_redis_client(*a, **k):
            return _FakeRedis()

    monkeypatch.setattr(ph, "RedisHelper", _FakeRedisHelper)
    cfg = types.SimpleNamespace(redis_host="h", redis_port=1, redis_db=0, memory_service_url="http://mem")

    class _FakeClient:
        def __init__(self, base_url=None):
            self.base_url = base_url

        def health(self):
            return {"status": "ok"}

    monkeypatch.setattr("agent_runtime.product.agent_gateway.MemoryClient", _FakeClient)

    class _FakeEmbed:
        def health(self):
            return {"status": "ok"}

    monkeypatch.setattr(
        "agent_memory_lib.embedding_client.embedding_client_from_env_like_config",
        lambda: _FakeEmbed(),
    )

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def run(self, *a, **k):
            return None

    class _FakeDriver:
        def session(self):
            return _FakeSession()

        def close(self):
            return None

    fake_neo4j = types.SimpleNamespace(GraphDatabase=types.SimpleNamespace(driver=lambda *a, **k: _FakeDriver()))
    monkeypatch.setitem(__import__("sys").modules, "neo4j", fake_neo4j)

    assert ph._redis_health(cfg)["ok"] is True
    assert ph._memory_service_health(cfg)["ok"] is True
    assert ph._embedding_service_health(cfg)["ok"] is True
    assert ph._neo4j_health(types.SimpleNamespace(neo4j_uri="bolt://x", neo4j_user="u", neo4j_password="p"))["ok"] is True


def test_llm_call_factory_forces_chat_completions(monkeypatch):
    monkeypatch.setenv("OPENAI_API_STYLE", "chat")
    calls = []

    class _ChatCompletions:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs)
            msg = types.SimpleNamespace(content="chat answer", tool_calls=None)
            choice = types.SimpleNamespace(message=msg)
            return types.SimpleNamespace(choices=[choice])

    client = types.SimpleNamespace(
        responses=types.SimpleNamespace(
            create=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("forced chat mode must not call responses")
            )
        ),
        chat=types.SimpleNamespace(completions=_ChatCompletions()),
    )

    call = ph._llm_call_factory(
        client,
        "gpt-test",
        0.1,
        tools=[
            {
                "type": "function",
                "name": "memory_search",
                "description": "Search memory",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
    )

    response = call([{"role": "user", "content": "hi"}])

    assert response.choices[0].message.content == "chat answer"
    assert calls[0]["model"] == "gpt-test"
    assert calls[0]["messages"] == [{"role": "user", "content": "hi"}]
    assert calls[0]["tools"][0]["function"]["name"] == "memory_search"
