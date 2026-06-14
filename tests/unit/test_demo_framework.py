import uuid


from agent_memory_framework.demo_agent import DemoAgent, DemoRuntime
from agent_memory_lib import MemoryClient


class _FakeAgent(DemoAgent):
    def get_system_prompt(self) -> str:
        return "You are a test agent."

    def register_domain_tools(self, registry):
        pass


class _FakeResponse:
    def __init__(self, text: str):
        class _Block:
            def __init__(self, t):
                self.text = t

        class _Out:
            type = "message"

            def __init__(self, t):
                self.content = [_Block(t)]

        self.output = [_Out(text)]


def test_demo_agent_runs_single_turn(mocker):
    # MemoryManager uses MemoryClient.retrieve_stm under the hood
    memory_client = mocker.Mock(spec=MemoryClient)
    memory_client.retrieve_stm.return_value = {"status": "success", "data": []}

    def llm_call(_messages):
        return _FakeResponse("OK")

    runtime = DemoRuntime(
        agent_id="a",
        user_id="u",
        memory_client=memory_client,
        llm_call_fn=llm_call,
        conversation_id=f"t_{uuid.uuid4().hex}",
        trace_id="trace_test",
        config={},
    )

    agent = _FakeAgent(runtime)
    out = agent.run_turn("hi")
    assert out == "OK"


def _runtime_for_memory_tests(memory_client, llm_call_fn):
    return DemoRuntime(
        agent_id="a",
        user_id="u",
        memory_client=memory_client,
        llm_call_fn=llm_call_fn,
        conversation_id=f"t_{uuid.uuid4().hex}",
        trace_id="trace_memory_test",
        config={},
    )


def test_demo_agent_exposes_read_only_memory_tools(mocker):
    memory_client = mocker.Mock(spec=MemoryClient)
    memory_client.retrieve_stm.return_value = {"status": "success", "data": []}
    memory_client.retrieve_wm.return_value = {"status": "success", "data": None}
    memory_client.list_ltm_preferences.return_value = {
        "status": "success",
        "data": {"timezone": "Asia/Shanghai"},
    }
    memory_client.retrieve_ltm_preference.return_value = {
        "status": "success",
        "data": "Asia/Shanghai",
    }
    memory_client.memory_search.return_value = {
        "status": "success",
        "data": {
            "hits": [
                {
                    "tier": "semantic",
                    "snippet": "semantic hit",
                    "memory_kind": "semantic_fact",
                }
            ]
        },
    }

    agent = _FakeAgent(
        _runtime_for_memory_tests(memory_client, lambda _messages: _FakeResponse("OK"))
    )

    memory_tool_names = {t["name"] for t in agent.tool_registry.list_tools("memory")}
    assert "retrieve_ltm_preferences" in memory_tool_names
    assert "search_semantic_memories" in memory_tool_names
    assert "search_graph_memories" in memory_tool_names

    prefs = agent.tool_registry.execute("retrieve_ltm_preferences", key="timezone")
    assert prefs == {"status": "success", "data": {"timezone": "Asia/Shanghai"}}

    semantic = agent.tool_registry.execute("search_semantic_memories", query="q", top_k=3)
    assert semantic["status"] == "success"
    assert semantic["data"][0]["snippet"] == "semantic hit"

    graph = agent.tool_registry.execute("search_graph_memories", query="q", top_k=3)
    assert graph["status"] == "success"
    memory_client.memory_search.assert_any_call(query="q", top_k=3, tiers=["graph"])


def test_demo_agent_answers_safe_explicit_ltm_preference_without_llm(mocker):
    memory_client = mocker.Mock(spec=MemoryClient)
    memory_client.retrieve_stm.return_value = {"status": "success", "data": []}
    memory_client.retrieve_wm.return_value = {"status": "success", "data": None}
    memory_client.list_ltm_preferences.return_value = {
        "status": "success",
        "data": {
            "timezone": "Asia/Shanghai",
            "bulk_pref_013": "FAKE_MEMORY_BULK_ZBY_20260613: preference noise 013",
        },
    }
    memory_client.memory_search.return_value = {"status": "success", "data": {"hits": []}}

    def fail_if_called(_messages):
        raise AssertionError("explicit preference lookup should not need an LLM call")

    agent = _FakeAgent(_runtime_for_memory_tests(memory_client, fail_if_called))

    out = agent.run_turn("timezone 是什么？")

    assert "timezone" in out
    assert "Asia/Shanghai" in out
    memory_client.retrieve_stm.assert_not_called()
    memory_client.memory_search.assert_not_called()


def test_demo_agent_does_not_expose_synthetic_preference_keys(mocker):
    memory_client = mocker.Mock(spec=MemoryClient)
    memory_client.retrieve_stm.return_value = {"status": "success", "data": []}
    memory_client.retrieve_wm.return_value = {"status": "success", "data": None}
    memory_client.list_ltm_preferences.return_value = {
        "status": "success",
        "data": {
            "bulk_pref_013": "FAKE_MEMORY_BULK_ZBY_20260613: preference noise 013"
        },
    }
    memory_client.memory_search.return_value = {"status": "success", "data": {"hits": []}}

    def fail_if_called(_messages):
        raise AssertionError("synthetic preference lookup should not need an LLM call")

    agent = _FakeAgent(_runtime_for_memory_tests(memory_client, fail_if_called))

    out = agent.run_turn("bulk_pref_013 是什么？")

    assert "内部测试记忆标识" in out
    assert "preference noise" not in out
    assert "FAKE_MEMORY_BULK" not in out


def _tool_names_for_turn(agent, user_query):
    return {t["name"] for t in agent.tools_for_turn(user_query)}


def test_demo_agent_hides_core_memory_tools_for_plain_greeting(mocker):
    memory_client = mocker.Mock(spec=MemoryClient)
    memory_client.retrieve_stm.return_value = {"status": "success", "data": []}
    memory_client.retrieve_wm.return_value = {"status": "success", "data": None}

    agent = _FakeAgent(
        _runtime_for_memory_tests(memory_client, lambda _messages: _FakeResponse("OK"))
    )

    tool_names = _tool_names_for_turn(agent, "hi")

    assert "retrieve_stm_summaries" not in tool_names
    assert "retrieve_ltm_preferences" not in tool_names
    assert "search_semantic_memories" not in tool_names
    assert "search_graph_memories" not in tool_names
    assert "manage_working_memory" not in tool_names


def test_demo_agent_exposes_memory_lookup_tools_for_explicit_memory_question(mocker):
    memory_client = mocker.Mock(spec=MemoryClient)
    memory_client.retrieve_stm.return_value = {"status": "success", "data": []}
    memory_client.retrieve_wm.return_value = {"status": "success", "data": None}

    agent = _FakeAgent(
        _runtime_for_memory_tests(memory_client, lambda _messages: _FakeResponse("OK"))
    )

    tool_names = _tool_names_for_turn(agent, "你记得我的偏好吗？")

    assert "retrieve_stm_summaries" in tool_names
    assert "retrieve_ltm_preferences" in tool_names
    assert "search_semantic_memories" in tool_names
    assert "search_graph_memories" in tool_names
    assert "manage_working_memory" not in tool_names


def test_demo_agent_hides_context7_for_business_memory_question(mocker):
    memory_client = mocker.Mock(spec=MemoryClient)
    memory_client.retrieve_stm.return_value = {"status": "success", "data": []}
    memory_client.retrieve_wm.return_value = {"status": "success", "data": None}

    agent = _FakeAgent(
        _runtime_for_memory_tests(memory_client, lambda _messages: _FakeResponse("OK"))
    )
    agent.tool_registry.register(
        name="context7.resolve-library-id",
        func=lambda **_kwargs: None,
        schema={
            "description": "Resolve a package name to a Context7 library id.",
            "parameters": {"type": "object", "properties": {}},
        },
        category="context7",
    )

    query = (
        "我现在这个 Northstar DW Ops 里，"
        "finance_mrr 的 freshness SLA 是什么？它上游依赖什么？"
    )
    tool_names = _tool_names_for_turn(agent, query)

    assert "context7.resolve-library-id" not in tool_names


def test_demo_agent_exposes_context7_for_documentation_question(mocker):
    memory_client = mocker.Mock(spec=MemoryClient)
    memory_client.retrieve_stm.return_value = {"status": "success", "data": []}
    memory_client.retrieve_wm.return_value = {"status": "success", "data": None}

    agent = _FakeAgent(
        _runtime_for_memory_tests(memory_client, lambda _messages: _FakeResponse("OK"))
    )
    agent.tool_registry.register(
        name="context7.resolve-library-id",
        func=lambda **_kwargs: None,
        schema={
            "description": "Resolve a package name to a Context7 library id.",
            "parameters": {"type": "object", "properties": {}},
        },
        category="context7",
    )

    tool_names = _tool_names_for_turn(agent, "查一下 React useEffect 的官方文档")

    assert "context7.resolve-library-id" in tool_names


def test_demo_agent_exposes_database_mcp_for_database_question(mocker):
    memory_client = mocker.Mock(spec=MemoryClient)
    memory_client.retrieve_stm.return_value = {"status": "success", "data": []}
    memory_client.retrieve_wm.return_value = {"status": "success", "data": None}

    agent = _FakeAgent(
        _runtime_for_memory_tests(memory_client, lambda _messages: _FakeResponse("OK"))
    )
    agent.tool_registry.register(
        name="supabase.execute-sql",
        func=lambda **_kwargs: None,
        schema={
            "description": "Execute SQL against a Supabase Postgres database.",
            "parameters": {"type": "object", "properties": {}},
        },
        category="supabase",
    )

    tool_names = _tool_names_for_turn(agent, "帮我查一下 Supabase 的表结构和 SQL")

    assert "supabase.execute-sql" in tool_names


def test_demo_agent_exposes_working_memory_tool_for_active_step_mode(mocker):
    memory_client = mocker.Mock(spec=MemoryClient)
    memory_client.retrieve_stm.return_value = {"status": "success", "data": []}
    memory_client.retrieve_wm.return_value = {
        "status": "success",
        "data": {
            "mode": "step_mode",
            "status": "active",
            "steps": [{"id": "1", "text": "Do the next step", "status": "todo"}],
        },
    }

    agent = _FakeAgent(
        _runtime_for_memory_tests(memory_client, lambda _messages: _FakeResponse("OK"))
    )

    tool_names = _tool_names_for_turn(agent, "继续")

    assert "manage_working_memory" in tool_names
