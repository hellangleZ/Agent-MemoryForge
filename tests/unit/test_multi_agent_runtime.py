from __future__ import annotations


from agent_memory_framework.llm import CallableLLMProvider
from agent_memory_framework.multi_agent import CoordinationStrategy, MultiAgentRuntime
from agent_memory_framework.replay import RepoContext, RunRecorder
from agent_memory_framework.runtime import Runtime
from agent_memory_framework.settings import Settings
from agent_runtime.product.templates.code_assistant import CodeAssistantAgent
from agent_memory_framework.factory import build_team_from_config


class _FakeResponse:
    def __init__(self, output_text: str):
        self.output_text = output_text


def test_multi_agent_runtime_sequential_routing_trace_recorded(tmp_path):
    def llm_call(messages):
        assert messages
        return _FakeResponse(output_text="ok")

    runtime = Runtime(
        agent_id="planner",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(llm_call),
        conversation_id="c_1",
        settings=Settings(),
    )

    agents = {
        "planner": CodeAssistantAgent(runtime),
        "reviewer": CodeAssistantAgent(
            Runtime(
                agent_id="reviewer",
                user_id=runtime.user_id,
                memory_client=runtime.memory_client,
                llm_provider=runtime.llm_provider,
                conversation_id=runtime.conversation_id,
                settings=runtime.settings,
            )
        ),
    }
    recorder = RunRecorder(
        name="multi-agent",
        request={"messages": [{"role": "user", "content": "hi"}]},
        repo=RepoContext(root=str(tmp_path), head_sha="test", dirty=True),
    )

    out = MultiAgentRuntime(agents=agents).run(
        "hi", trace_id="trace_1", record=recorder
    )

    assert out["final"] == "ok"
    assert out["routing_trace"]["strategy"] == "sequential"
    assert [t["agent_id"] for t in out["routing_trace"]["turns"]] == [
        "planner",
        "reviewer",
    ]

    bundle = recorder.to_bundle()
    assert bundle.result["routing_trace"]["turns"][0]["agent_id"] == "planner"


def test_multi_agent_runtime_parallel_routing_trace_recorded(tmp_path):
    def llm_call(messages):
        assert messages
        return _FakeResponse(output_text="ok")

    runtime = Runtime(
        agent_id="planner",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(llm_call),
        conversation_id="c_1",
        settings=Settings(),
    )

    agents = {
        "planner": CodeAssistantAgent(runtime),
        "reviewer": CodeAssistantAgent(
            Runtime(
                agent_id="reviewer",
                user_id=runtime.user_id,
                memory_client=runtime.memory_client,
                llm_provider=runtime.llm_provider,
                conversation_id=runtime.conversation_id,
                settings=runtime.settings,
            )
        ),
    }
    recorder = RunRecorder(
        name="multi-agent",
        request={"messages": [{"role": "user", "content": "hi"}]},
        repo=RepoContext(root=str(tmp_path), head_sha="test", dirty=True),
    )

    out = MultiAgentRuntime(agents=agents, strategy=CoordinationStrategy.PARALLEL).run(
        "hi", trace_id="trace_1", record=recorder
    )

    assert out["final"] == "ok"
    assert out["routing_trace"]["strategy"] == "parallel"
    assert set(t["agent_id"] for t in out["routing_trace"]["turns"]) == {
        "planner",
        "reviewer",
    }


def test_parallel_workers_cap_respected(monkeypatch):
    monkeypatch.setenv("AGENT_MEMORY_PARALLEL_WORKERS", "1")

    def llm_call(messages):
        return _FakeResponse(output_text="ok")

    runtime = Runtime(
        agent_id="planner",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(llm_call),
        conversation_id="c_1",
        settings=Settings(),
    )

    agents = {
        "planner": CodeAssistantAgent(runtime),
        "reviewer": CodeAssistantAgent(
            Runtime(
                agent_id="reviewer",
                user_id=runtime.user_id,
                memory_client=runtime.memory_client,
                llm_provider=runtime.llm_provider,
                conversation_id=runtime.conversation_id,
                settings=runtime.settings,
            )
        ),
    }

    out = MultiAgentRuntime(agents=agents, strategy=CoordinationStrategy.PARALLEL).run(
        "hi"
    )
    assert out["routing_trace"]["strategy"] == "parallel"


def test_build_team_from_config_respects_disable_parallel_flag(monkeypatch):
    monkeypatch.setenv("AGENT_MEMORY_ENABLE_PARALLEL", "0")
    monkeypatch.setenv("MEMORY_SERVICE_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_MODEL", "m")

    class _FakeOpenAIClient:
        class responses:
            @staticmethod
            def create(model, input, temperature):
                return type("R", (), {"output_text": "ok"})()

        def __init__(self, api_key, **kwargs):
            assert api_key == "k"

    monkeypatch.setattr("agent_memory_framework.llm_resolver.OpenAI", _FakeOpenAIClient)

    class _Agent:
        def __init__(self, runtime):
            self.runtime = runtime

        def run_turn(self, user_query: str) -> str:  # pragma: no cover
            return "ok"

    team = build_team_from_config(
        agent_factories={"a": lambda rt: _Agent(rt), "b": lambda rt: _Agent(rt)},
        config=None,
    )
    assert team.run("hi")["strategy"] == "sequential"
