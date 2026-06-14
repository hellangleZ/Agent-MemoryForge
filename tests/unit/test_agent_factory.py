from __future__ import annotations

from agent_memory_framework.factory import (
    AgentBuildOptions,
    AutoBuildOverrides,
    build_agent,
    build_agent_from_config,
    build_team_from_config,
)
from agent_memory_framework.multi_agent import CoordinationStrategy
from agent_memory_framework.runtime import Runtime


class _FakeMemoryClient:
    def __init__(self, base_url: str = "http://example.invalid"):
        self.base_url = base_url


class _FakeLLMProvider:
    def generate(self, messages, trace_id=None):
        return type("Result", (), {"text": "ok", "tool_calls": [], "raw": {}})()


class _FakeAgent:
    def __init__(self, runtime: Runtime):
        self.runtime = runtime

    def run_turn(self, user_query: str) -> str:
        return "ok"


def test_build_agent_wires_runtime():
    agent = build_agent(
        _FakeAgent,
        options=AgentBuildOptions(
            agent_id="a1",
            user_id="u1",
            conversation_id="c1",
            memory_client=_FakeMemoryClient(),
            llm_provider=_FakeLLMProvider(),
        ),
    )

    assert agent.runtime.agent_id == "a1"
    assert agent.runtime.user_id == "u1"
    assert agent.runtime.conversation_id == "c1"


def test_build_agent_from_config_env_fallback(monkeypatch):
    monkeypatch.setenv("MEMORY_SERVICE_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("USER_ID", "u_env")
    monkeypatch.setenv("AGENT_ID", "a_env")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "http://example.invalid")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")

    class _FakeAzureClient:
        class responses:
            @staticmethod
            def create(model, input, temperature):
                return type("R", (), {"output_text": "ok"})()

    def _fake_create_azure_openai_client():
        return _FakeAzureClient(), "m"

    monkeypatch.setattr(
        "agent_memory_framework.llm_clients.create_azure_openai_client",
        _fake_create_azure_openai_client,
    )

    agent = build_agent_from_config(
        _FakeAgent,
        config=None,
        overrides=AutoBuildOverrides(conversation_id="c_auto"),
    )
    assert agent.runtime.user_id == "u_env"
    assert agent.runtime.agent_id == "a_env"
    assert agent.runtime.conversation_id == "c_auto"


def test_build_team_from_config(monkeypatch):
    monkeypatch.setenv("MEMORY_SERVICE_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("USER_ID", "u_env")
    monkeypatch.setenv("AGENT_ID", "a_env")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "http://example.invalid")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")

    class _FakeAzureClient:
        class responses:
            @staticmethod
            def create(model, input, temperature):
                return type("R", (), {"output_text": "ok"})()

    def _fake_create_azure_openai_client():
        return _FakeAzureClient(), "m"

    monkeypatch.setattr(
        "agent_memory_framework.llm_clients.create_azure_openai_client",
        _fake_create_azure_openai_client,
    )

    def _make_agent(runtime):
        return _FakeAgent(runtime)

    runtime = build_team_from_config(
        agent_factories={"a": _make_agent, "b": _make_agent},
        roles={"a": "a", "b": "b"},
        strategy=CoordinationStrategy.PARALLEL,
        overrides=AutoBuildOverrides(conversation_id="c_team"),
    )
    out = runtime.run("hi")
    assert out["routing_trace"]["strategy"] == "parallel"
    assert set(out["responses"].keys()) == {"a", "b"}


def test_build_agent_from_config_openai_like_responses(monkeypatch):
    monkeypatch.setenv("MEMORY_SERVICE_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_MODEL", "m")

    class _FakeOpenAIClient:
        class responses:
            @staticmethod
            def create(model, input, temperature):
                assert model == "m"
                return type("R", (), {"output_text": "ok"})()

        def __init__(self, api_key, **kwargs):
            assert api_key == "k"

    monkeypatch.setattr("agent_memory_framework.llm_resolver.OpenAI", _FakeOpenAIClient)

    agent = build_agent_from_config(
        _FakeAgent,
        config=None,
        overrides=AutoBuildOverrides(conversation_id="c_openai"),
    )
    out = agent.runtime.llm_provider.generate([{"role": "user", "content": "hi"}])
    assert out.text == "ok"


def test_build_agent_from_config_openai_like_chat_fallback(monkeypatch):
    monkeypatch.setenv("MEMORY_SERVICE_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_MODEL", "m")

    class _FakeOpenAIClient:
        class responses:
            @staticmethod
            def create(model, input, temperature):
                raise RuntimeError("responses not supported")

        class chat:
            class completions:
                @staticmethod
                def create(model, messages, temperature):
                    assert model == "m"
                    return type("R", (), {"output_text": "ok-chat"})()

        def __init__(self, api_key, **kwargs):
            assert api_key == "k"

    monkeypatch.setattr("agent_memory_framework.llm_resolver.OpenAI", _FakeOpenAIClient)

    agent = build_agent_from_config(
        _FakeAgent,
        config=None,
        overrides=AutoBuildOverrides(conversation_id="c_openai_chat"),
    )
    out = agent.runtime.llm_provider.generate([{"role": "user", "content": "hi"}])
    assert out.text == "ok-chat"


def test_build_agent_from_config_openai_like_forces_chat_api(monkeypatch):
    monkeypatch.setenv("MEMORY_SERVICE_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    monkeypatch.setenv("OPENAI_API_STYLE", "chat")

    class _FakeOpenAIClient:
        class responses:
            @staticmethod
            def create(*_args, **_kwargs):
                raise AssertionError("forced chat mode must not call responses")

        class chat:
            class completions:
                @staticmethod
                def create(model, messages, temperature):
                    assert model == "m"
                    assert messages == [{"role": "user", "content": "hi"}]
                    msg = type("Msg", (), {"content": "ok-chat-object"})()
                    choice = type("Choice", (), {"message": msg})()
                    return type("ChatResp", (), {"choices": [choice]})()

        def __init__(self, api_key, **kwargs):
            assert api_key == "k"

    monkeypatch.setattr("agent_memory_framework.llm_resolver.OpenAI", _FakeOpenAIClient)

    agent = build_agent_from_config(
        _FakeAgent,
        config=None,
        overrides=AutoBuildOverrides(conversation_id="c_openai_chat_forced"),
    )
    out = agent.runtime.llm_provider.generate([{"role": "user", "content": "hi"}])
    assert out.text == "ok-chat-object"


def test_build_agent_from_config_openai_like_auto_falls_back_on_responses_404(monkeypatch):
    monkeypatch.setenv("MEMORY_SERVICE_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    monkeypatch.setenv("OPENAI_API_STYLE", "auto")

    class _FakeOpenAIClient:
        class responses:
            @staticmethod
            def create(model, input, temperature):
                err = RuntimeError("404 page not found")
                setattr(err, "status_code", 404)
                raise err

        class chat:
            class completions:
                @staticmethod
                def create(model, messages, temperature):
                    msg = type("Msg", (), {"content": "ok-chat-404"})()
                    choice = type("Choice", (), {"message": msg})()
                    return type("ChatResp", (), {"choices": [choice]})()

        def __init__(self, api_key, **kwargs):
            assert api_key == "k"

    monkeypatch.setattr("agent_memory_framework.llm_resolver.OpenAI", _FakeOpenAIClient)

    agent = build_agent_from_config(
        _FakeAgent,
        config=None,
        overrides=AutoBuildOverrides(conversation_id="c_openai_chat_404"),
    )
    out = agent.runtime.llm_provider.generate([{"role": "user", "content": "hi"}])
    assert out.text == "ok-chat-404"


def test_build_agent_from_config_no_provider_errors(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    try:
        build_agent_from_config(
            _FakeAgent,
            config=None,
            overrides=AutoBuildOverrides(conversation_id="c_none"),
        )
        assert False, "expected error"
    except RuntimeError as exc:
        assert "No LLM provider configured" in str(exc)
