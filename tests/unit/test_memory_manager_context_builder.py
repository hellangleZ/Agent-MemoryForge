
from agent_memory_framework.memory_runtime.context_builder import ContextBuilder
from agent_memory_framework.memory_runtime.context_planner import ContextPlan
from agent_memory_framework.memory_runtime.memory_manager import MemoryManager


class _FakeMemoryClient:
    def __init__(self):
        self.calls = []
        self.last_search_kwargs = {}

    def store_stm(self, conversation_id, round_id, summary):
        self.calls.append(("store_stm", conversation_id, round_id, summary))
        return {"status": "success"}

    def retrieve_stm(self, conversation_id, last_k):
        self.calls.append(("retrieve_stm", conversation_id, last_k))
        return {"status": "success", "data": [{"summary": "s1", "round_id": 1}]}

    def store_wm(self, user_id, task_id, state, ttl_s=None):
        self.calls.append(("store_wm", user_id, task_id, state))
        return {"status": "success"}

    def retrieve_wm(self, user_id, task_id):
        self.calls.append(("retrieve_wm", user_id, task_id))
        # Default active WM shape.
        return {
            "status": "success",
            "data": {
                "wm_id": task_id,
                "status": "active",
                "goal": "g",
                "steps": [{"id": "1", "text": "t", "status": "todo"}],
            },
        }

    def store_ltm_preference(self, user_id, key, value):
        return {"status": "success"}

    def retrieve_ltm_preference(self, user_id, key):
        self.calls.append(("retrieve_ltm_preference", user_id, key))
        values = {
            "response_style": "中文简洁",
            "bulk_pref_013": "FAKE_MEMORY_BULK_ZBY_20260613: preference noise",
        }
        return {"status": "success", "data": values.get(key, "pref")}

    def list_ltm_preferences(self, user_id, limit=50):
        self.calls.append(("list_ltm_preferences", user_id, limit))
        return {
            "status": "success",
            "data": {
                "response_style": "中文简洁",
                "bulk_pref_013": "FAKE_MEMORY_BULK_ZBY_20260613: preference noise",
            },
        }

    def memory_search(self, **kwargs):
        self.calls.append(("memory_search", kwargs))
        self.last_search_kwargs = dict(kwargs)
        return {
            "status": "success",
            "data": {
                "hits": [
                    {
                        "snippet": "FAKE_MEMORY_BULK_ZBY_20260613: semantic_bulk_013",
                        "score": 0.99,
                        "metadata": {"source": "manual_bulk_fake_seed"},
                    },
                    {"snippet": "fact", "score": 0.9, "metadata": {"tags": ["real"]}},
                ]
            },
        }


def test_memory_manager_store_and_retrieve():
    client = _FakeMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1")
    assert manager.sync_conversation_to_stm(round_id=1, messages=[], summary="hi")["status"] == "success"
    assert manager.retrieve_stm_summaries()
    assert manager.store_wm_state("task", {"a": 1})["status"] == "success"
    assert isinstance(manager.retrieve_wm_state("task"), dict)
    assert manager.store_ltm_preference("lang", "en")["status"] == "success"
    assert manager.retrieve_ltm_preference("lang") == "pref"
    assert manager.retrieve_semantic_memories("q")


def test_memory_manager_zero_limits_skip_backend_reads():
    client = _FakeMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1")

    assert manager.retrieve_stm_summaries(last_k=0) == []
    assert manager.retrieve_semantic_memories("q", top_k=0) == []
    assert not any(call[0] == "retrieve_stm" for call in client.calls)
    assert not any(call[0] == "memory_search" for call in client.calls)


def test_memory_manager_zero_default_stm_limit_skips_backend_read():
    client = _FakeMemoryClient()
    manager = MemoryManager(
        memory_client=client,
        user_id="u1",
        config={"stm_max_summaries": 0},
    )

    assert manager.retrieve_stm_summaries() == []
    assert not any(call[0] == "retrieve_stm" for call in client.calls)


def test_memory_manager_zero_default_semantic_limit_skips_backend_read():
    client = _FakeMemoryClient()
    manager = MemoryManager(
        memory_client=client,
        user_id="u1",
        config={"semantic_top_k": 0},
    )

    assert manager.retrieve_semantic_memories("q", top_k=None) == []
    assert not any(call[0] == "memory_search" for call in client.calls)


def test_working_memory_lifecycle_start_cancel_complete():
    client = _FakeMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1", conversation_id="c1")

    # Simulate "no existing WM" by overriding retrieve_wm.
    client.retrieve_wm = lambda user_id, task_id: {"status": "error"}

    started = manager.start_long_task(goal="Build X", steps=[{"id": "1", "text": "Do A"}])
    assert started["status"] == "success"
    assert started["data"]["status"] == "active"

    # Now retrieval returns the stored WM state.
    last_state = {"data": started["data"]}
    client.retrieve_wm = lambda user_id, task_id: {"status": "success", "data": last_state["data"]}

    cancelled = manager.cancel_long_task(reason="user asked")
    assert cancelled["status"] == "success"
    assert cancelled["data"]["status"] == "cancelled"

    # Once cancelled, completing should be a no-op success.
    completed = manager.complete_long_task(summary="done")
    assert completed["status"] == "success"
    assert completed["data"]["status"] == "cancelled"


class _FakeTextProcessor:
    def extract_keywords(self, _text, top_k=10):
        return ["hello"]

    def calculate_relevance(self, text, keywords):
        return 1.0 if keywords and "hello" in keywords else 0.0


def test_context_builder_builds_enhanced_context():
    client = _FakeMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1")
    builder = ContextBuilder(memory_manager=manager, text_processor=_FakeTextProcessor())

    context = builder.build_enhanced_context(
        user_query="hello",
        conversation_history=[{"role": "user", "content": "hi"}],
        system_prompt="sys",
    )
    assert context[0]["role"] == "system"
    assert any("Relevant Semantic Facts" in msg["content"] for msg in context if msg["role"] == "system")
    assert client.last_search_kwargs["top_k"] > 5
    rendered = "\n".join(str(msg.get("content") or "") for msg in context)
    assert "response_style: 中文简洁" in rendered
    assert "bulk_pref_013" not in rendered
    assert "FAKE_MEMORY_BULK_ZBY_20260613" not in rendered


def test_context_builder_formats_sections():
    client = _FakeMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1")
    builder = ContextBuilder(memory_manager=manager, text_processor=_FakeTextProcessor())

    stm = builder._format_stm_context([{"round_id": 1, "summary": "s"}])
    assert "Round 1" in stm

    semantic = builder._format_semantic_context([{"text": "fact", "score": 0.5, "metadata": {"tags": ["x"]}}])
    assert "Relevant Semantic Facts" in semantic
    assert "score=" not in semantic
    assert "tags=" not in semantic

    # Event-history tier was removed; context builder no longer formats that section.


def test_context_builder_estimate_tokens():
    client = _FakeMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1")
    builder = ContextBuilder(memory_manager=manager, text_processor=_FakeTextProcessor())
    tokens = builder.estimate_context_tokens([{"content": "hello"}])
    assert tokens >= 1


def test_context_builder_respects_zero_stm_limit():
    client = _FakeMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1")
    builder = ContextBuilder(memory_manager=manager, text_processor=_FakeTextProcessor())

    assert builder._get_stm_context(user_query="anything", last_k=0) == ""
    assert not any(call[0] == "retrieve_stm" for call in client.calls)


def test_context_builder_respects_explicit_preference_opt_out(mocker):
    client = _FakeMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1")
    builder = ContextBuilder(memory_manager=manager, text_processor=_FakeTextProcessor())
    mocker.patch(
        "agent_memory_framework.memory_runtime.context_builder.LLMContextPlanner.plan",
        return_value=ContextPlan(
            include_wm=False,
            include_preferences=False,
            preference_keys=[],
            stm_last_k=0,
            semantic_top_k=0,
        ),
    )

    context = builder.build_enhanced_context(
        user_query="hello",
        conversation_history=[],
    )

    assert "## User Preferences" not in "\n".join(
        str(message.get("content") or "") for message in context
    )
    assert not any(call[0] == "list_ltm_preferences" for call in client.calls)


def test_context_builder_zero_config_skips_disabled_memory_reads(mocker, monkeypatch):
    client = _FakeMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1")
    builder = ContextBuilder(
        memory_manager=manager,
        text_processor=_FakeTextProcessor(),
        config={
            "include_preferences": False,
            "stm_max_summaries": 0,
            "semantic_top_k": 0,
        },
    )
    monkeypatch.setenv("AGENT_GRAPH_CONTEXT_TOP_K", "0")
    mocker.patch(
        "agent_memory_framework.memory_runtime.context_builder.LLMContextPlanner.plan",
        side_effect=lambda user_query, defaults: defaults,
    )

    builder.build_enhanced_context(user_query="hello", conversation_history=[])

    assert not any(
        call[0] in {"retrieve_stm", "memory_search", "list_ltm_preferences"}
        for call in client.calls
    )
    assert any(call[0] == "retrieve_wm" for call in client.calls)


def test_context_builder_filters_and_truncates_selected_preferences(mocker, monkeypatch):
    client = _FakeMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1")
    builder = ContextBuilder(memory_manager=manager, text_processor=_FakeTextProcessor())
    monkeypatch.setenv("AGENT_PREF_VALUE_MAXLEN", "4")
    mocker.patch(
        "agent_memory_framework.memory_runtime.context_builder.LLMContextPlanner.plan",
        return_value=ContextPlan(
            include_wm=False,
            preference_keys=[" response_style ", "bulk_pref_013"],
            stm_last_k=0,
            semantic_top_k=0,
        ),
    )

    context = builder.build_enhanced_context(user_query="hello", conversation_history=[])
    rendered = "\n".join(str(message.get("content") or "") for message in context)

    assert "response_style: 中文简洁" in rendered
    assert "bulk_pref_013" not in rendered
    assert ("retrieve_ltm_preference", "u1", "response_style") in client.calls
    assert ("retrieve_ltm_preference", "u1", "bulk_pref_013") in client.calls
    assert not any(call[0] == "list_ltm_preferences" for call in client.calls)


def test_context_builder_graph_retrieval_is_independent_of_semantic_limit(mocker, monkeypatch):
    client = _FakeMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1")
    builder = ContextBuilder(memory_manager=manager, text_processor=_FakeTextProcessor())
    monkeypatch.setenv("AGENT_GRAPH_CONTEXT_TOP_K", "2")
    mocker.patch(
        "agent_memory_framework.memory_runtime.context_builder.LLMContextPlanner.plan",
        return_value=ContextPlan(
            include_wm=False,
            include_preferences=False,
            preference_keys=[],
            stm_last_k=0,
            semantic_top_k=0,
        ),
    )

    builder.build_enhanced_context(user_query="hello", conversation_history=[])

    graph_calls = [
        call for call in client.calls
        if call[0] == "memory_search" and call[1].get("tiers") == ["graph"]
    ]
    assert graph_calls
    assert all(call[1]["top_k"] == 7 for call in graph_calls)


def test_context_builder_explicit_zero_search_limits_skip_backend_reads():
    client = _FakeMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1")
    builder = ContextBuilder(memory_manager=manager, text_processor=_FakeTextProcessor())

    assert builder._get_relevant_semantic_facts("hello", top_k=0) == []
    assert builder._get_relevant_graph_facts("hello", top_k=0) == []
    assert not any(call[0] == "memory_search" for call in client.calls)


def test_context_builder_uses_semantic_fallback_queries_for_long_questions():
    class _FallbackMemoryClient(_FakeMemoryClient):
        def memory_search(self, **kwargs):
            self.calls.append(("memory_search", kwargs))
            query = kwargs.get("query")
            if query == "finance_mrr":
                return {
                    "status": "success",
                    "data": {
                        "hits": [
                            {
                                "snippet": "marts.finance_mrr 的刷新 SLA 是每天 08:30 Asia/Shanghai。",
                                "score": 1.0,
                                "entry_id": "finance-sla",
                            }
                        ]
                    },
                }
            return {"status": "success", "data": {"hits": []}}

    client = _FallbackMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1")
    builder = ContextBuilder(memory_manager=manager, text_processor=_FakeTextProcessor())

    facts = builder._get_relevant_semantic_facts(
        "我现在这个 Northstar DW Ops 里，finance_mrr 的 freshness SLA 是什么？",
        top_k=5,
    )

    assert facts
    assert "08:30" in facts[0]["text"]
    queries = [
        call[1]["query"] for call in client.calls if call[0] == "memory_search"
    ]
    assert "finance_mrr" in queries
    assert queries.index("finance_mrr") == 1


def test_context_builder_injects_graph_context_with_fallback_queries():
    class _GraphMemoryClient(_FakeMemoryClient):
        def memory_search(self, **kwargs):
            self.calls.append(("memory_search", kwargs))
            if kwargs.get("tiers") == ["graph"] and kwargs.get("query") == "finance_mrr":
                return {
                    "status": "success",
                    "data": {
                        "hits": [
                            {
                                "snippet": "marts.finance_mrr -[depends_on]-> fact_orders",
                                "score": 1.0,
                                "entry_id": "finance-graph",
                            }
                        ]
                    },
                }
            return {"status": "success", "data": {"hits": []}}

    client = _GraphMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1")
    builder = ContextBuilder(memory_manager=manager, text_processor=_FakeTextProcessor())

    facts = builder._get_relevant_graph_facts(
        "我现在这个 Northstar DW Ops 里，finance_mrr 的上游依赖是什么？",
        top_k=5,
    )

    assert facts
    rendered = builder._format_graph_context(facts)
    assert "Knowledge Graph" in rendered
    assert "depends_on" in rendered
    assert "score=" not in rendered


def test_context_builder_cleans_memory_snippets_before_prompt_injection():
    class _DirtyMemoryClient(_FakeMemoryClient):
        def memory_search(self, **kwargs):
            if kwargs.get("tiers") == ["graph"]:
                return {
                    "status": "success",
                    "data": {
                        "hits": [
                            {
                                "snippet": '<!-- am:entry {"source":"demo_fixture_20260613"} --> [bad]',
                                "metadata": {
                                    "subject": "marts.finance_mrr",
                                    "relation": "depends_on",
                                    "obj": "fact_orders",
                                },
                            }
                        ]
                    },
                }
            return {
                "status": "success",
                "data": {
                    "hits": [
                        {
                            "snippet": '<!-- am:entry {"source":"demo_fixture_20260613"} --> [Northstar] fact'
                        },
                        {
                            "snippet": '"memory_kind":"semantic_fact","tenant_id":"t"'
                        }
                    ]
                },
            }

    dirty = _DirtyMemoryClient()
    manager = MemoryManager(memory_client=dirty, user_id="u1")
    builder = ContextBuilder(memory_manager=manager, text_processor=_FakeTextProcessor())

    facts = builder._get_relevant_semantic_facts("Northstar", top_k=1)
    graph = builder._get_relevant_graph_facts("finance_mrr", top_k=1)

    assert len(facts) == 1
    assert facts[0]["text"] == "Northstar fact"
    assert graph[0]["text"] == "marts.finance_mrr -[depends_on]-> fact_orders"
    assert "am:entry" not in facts[0]["text"]
    assert "demo_fixture" not in graph[0]["text"]


def test_context_builder_skips_synthetic_working_memory():
    client = _FakeMemoryClient()
    manager = MemoryManager(memory_client=client, user_id="u1")
    builder = ContextBuilder(memory_manager=manager, text_processor=_FakeTextProcessor())

    state = {
        "status": "active",
        "goal": "FAKE_MEMORY_BULK_ZBY_20260613: fake active WM",
        "steps": [{"id": "1", "text": "semantic_bulk_001", "status": "todo"}],
    }
    enhanced = []
    builder._append_working_memory_context(enhanced)
    assert enhanced

    client.retrieve_wm = lambda user_id, task_id: {"status": "success", "data": state}
    enhanced = []
    builder._append_working_memory_context(enhanced)
    assert enhanced == []
