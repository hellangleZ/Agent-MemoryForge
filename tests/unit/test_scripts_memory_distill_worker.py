import types

from agent_runtime.memory_distill.job_schema import new_job
from scripts import memory_distill_worker


class _FakeMemoryClient:
    def __init__(self, base_url):
        self.base_url = base_url
        self.calls = []

    def with_scope(self, tenant_id, workspace_id):
        self.scope = (tenant_id, workspace_id)
        return self

    def memory_write(self, **kwargs):
        self.calls.append(("memory_write", kwargs))
        return {"status": "success"}


class _ParsedResult:
    def __init__(self):
        self.stm_summary = {
            "user_request": "remember something",
            "final_answer": "summary",
            "memories_used": [],
            "timestamp": 1710000000,
            "conversation_length": 2,
        }
        self.semantic_facts = [
            {"text": "project_alpha has service_contract", "importance": 0.9}
        ]
        self.preferences = [{"key": "lang", "value": "en", "confidence": 0.9}]
        self.kg_relations = [
            {
                "subject": "project_alpha",
                "relation": "has_contract",
                "obj": "service_contract",
                "confidence": 0.9,
            }
        ]


def test_store_distilled_memories(monkeypatch):
    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="u",
        conversation_id="c",
        round_id=1,
        messages=[
            {
                "role": "user",
                "content": "Please remember project_alpha has service_contract.",
            }
        ],
        last_user="Please remember project_alpha has service_contract.",
        assistant_answer="ok",
    )
    client = _FakeMemoryClient("http://mem")
    monkeypatch.setattr(memory_distill_worker, "MemoryClient", lambda base_url: client)

    summary = memory_distill_worker._store_distilled_memories(
        base_url="http://mem",
        job=job,
        result=_ParsedResult(),
    )
    # STM write should always provide string content (memory service validates this).
    stm_calls = [
        call[1]
        for call in client.calls
        if call[0] == "memory_write" and call[1].get("tier") == "stm"
    ]
    assert stm_calls
    assert isinstance(stm_calls[0].get("content"), str)
    tiers = [call[1].get("tier") for call in client.calls if call[0] == "memory_write"]
    assert "stm" in tiers
    assert "semantic" in tiers
    # Episodic is not persisted from distill (events should come from audit/trace evidence).
    # This preference candidate is not grounded in the user message, so it is skipped.
    assert "preferences" not in tiers
    assert "graph" in tiers
    assert "kg_relation" not in tiers
    assert summary["written"]["stm"] == 1
    assert summary["written"]["semantic"] == 1
    assert summary["written"]["graph"] == 1
    assert summary["skipped"]["preferences.no_user_evidence"] == 1


def test_store_distilled_memories_persists_grounded_preferences_by_default(monkeypatch):
    monkeypatch.delenv("MEMORY_DISTILL_STORE_PREFERENCES", raising=False)
    monkeypatch.delenv("MEMORY_DISTILL_PREFERENCE_REQUIRE_CONFIRMATION", raising=False)
    monkeypatch.setenv("MEMORY_DISTILL_PREFERENCE_MIN_CONFIDENCE", "0.8")

    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="u",
        conversation_id="c",
        round_id=1,
        messages=[
            {
                "role": "user",
                "content": "Please remember project_alpha has service_contract and lang en.",
            }
        ],
        last_user="Please remember project_alpha has service_contract and lang en.",
        assistant_answer="ok",
    )
    client = _FakeMemoryClient("http://mem")
    monkeypatch.setattr(memory_distill_worker, "MemoryClient", lambda base_url: client)

    memory_distill_worker._store_distilled_memories(
        base_url="http://mem",
        job=job,
        result=_ParsedResult(),
    )

    tiers = [call[1].get("tier") for call in client.calls if call[0] == "memory_write"]
    assert "preferences" in tiers
    pref_calls = [
        call[1]
        for call in client.calls
        if call[0] == "memory_write" and call[1].get("tier") == "preferences"
    ]
    assert pref_calls[0]["target"] == "preferences"


def test_store_distilled_memories_accepts_grounded_normalized_preference_key(
    monkeypatch,
):
    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="u",
        conversation_id="c",
        round_id=1,
        messages=[{"role": "user", "content": "以后回答我都用中文短句。"}],
        last_user="以后回答我都用中文短句。",
        assistant_answer="好的。",
    )

    class _ChineseStyleParsed(_ParsedResult):
        def __init__(self):
            super().__init__()
            self.stm_summary = {}
            self.semantic_facts = []
            self.preferences = [
                {"key": "answer_style", "value": "中文短句", "confidence": 0.95}
            ]
            self.kg_relations = []

    client = _FakeMemoryClient("http://mem")
    monkeypatch.setattr(memory_distill_worker, "MemoryClient", lambda base_url: client)

    memory_distill_worker._store_distilled_memories(
        base_url="http://mem",
        job=job,
        result=_ChineseStyleParsed(),
    )

    pref_calls = [
        call[1]
        for call in client.calls
        if call[0] == "memory_write" and call[1].get("tier") == "preferences"
    ]
    assert len(pref_calls) == 1
    assert pref_calls[0]["content"] == "answer_style: 中文短句"


def test_store_distilled_memories_summary_counts_durable_skip(monkeypatch):
    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="u",
        conversation_id="c",
        round_id=1,
        messages=[{"role": "user", "content": "hello"}],
        last_user="hello",
        assistant_answer="ok",
    )
    client = _FakeMemoryClient("http://mem")
    monkeypatch.setattr(memory_distill_worker, "MemoryClient", lambda base_url: client)
    monkeypatch.setattr(
        memory_distill_worker,
        "allows_durable_distill_from_user_messages",
        lambda *_args, **_kwargs: False,
    )

    summary = memory_distill_worker._store_distilled_memories(
        base_url="http://mem",
        job=job,
        result=_ParsedResult(),
    )

    assert summary["allow_durable_distill"] is False
    assert summary["written"]["stm"] == 1
    assert summary["written"]["semantic"] == 0
    assert summary["skipped"]["semantic.durable_not_allowed"] == 1
    assert summary["skipped"]["graph.durable_not_allowed"] == 1


def test_response_style_preference_does_not_leak_to_workspace_memory(monkeypatch):
    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="zhouboyang",
        conversation_id="c",
        round_id=2,
        messages=[{"role": "user", "content": "以后回答我都用中文短句。"}],
        last_user="以后回答我都用中文短句。",
        assistant_answer="好的。",
    )

    class _PreferenceParsed(_ParsedResult):
        def __init__(self):
            super().__init__()
            self.stm_summary = {}
            self.semantic_facts = [
                {"text": "后续回复应使用中文短句。", "importance": 0.95}
            ]
            self.preferences = [
                {"key": "answer_style", "value": "中文短句", "confidence": 0.95}
            ]
            self.kg_relations = [
                {
                    "subject": "用户",
                    "relation": "prefers_response_style",
                    "obj": "中文短句",
                    "confidence": 0.95,
                }
            ]

    client = _FakeMemoryClient("http://mem")
    monkeypatch.setattr(memory_distill_worker, "MemoryClient", lambda base_url: client)

    memory_distill_worker._store_distilled_memories(
        base_url="http://mem",
        job=job,
        result=_PreferenceParsed(),
    )

    tiers = [call[1].get("tier") for call in client.calls if call[0] == "memory_write"]
    assert tiers == ["preferences"]
    assert client.calls[0][1]["scope"] == "user"


def test_response_style_semantic_without_preference_is_not_workspace_memory(
    monkeypatch,
):
    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="zhouboyang",
        conversation_id="c",
        round_id=2,
        messages=[{"role": "user", "content": "以后回答我都用中文短句。"}],
        last_user="以后回答我都用中文短句。",
        assistant_answer="好的。",
    )

    class _PreferenceAsFactParsed(_ParsedResult):
        def __init__(self):
            super().__init__()
            self.stm_summary = {}
            self.semantic_facts = [
                {"text": "后续回复应使用中文短句。", "importance": 0.95}
            ]
            self.preferences = []
            self.kg_relations = [
                {
                    "subject": "用户",
                    "relation": "prefers_response_style",
                    "obj": "中文短句",
                    "confidence": 0.95,
                }
            ]

    client = _FakeMemoryClient("http://mem")
    monkeypatch.setattr(memory_distill_worker, "MemoryClient", lambda base_url: client)

    memory_distill_worker._store_distilled_memories(
        base_url="http://mem",
        job=job,
        result=_PreferenceAsFactParsed(),
    )

    tiers = [call[1].get("tier") for call in client.calls if call[0] == "memory_write"]
    assert tiers == []


def test_store_distilled_memories_filters_synthetic_and_ungrounded(monkeypatch):
    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="u",
        conversation_id="c",
        round_id=1,
        messages=[{"role": "user", "content": "你记得我现在在做什么产品吗？"}],
        last_user="你记得我现在在做什么产品吗？",
        assistant_answer="我猜你在做电商/交易系统。",
    )

    class _PollutedParsed(_ParsedResult):
        def __init__(self):
            super().__init__()
            self.stm_summary = {"final_answer": "我猜你在做电商/交易系统。"}
            self.semantic_facts = [
                {"text": "用户正在做电商/交易系统项目", "importance": 0.95},
                {
                    "text": "FAKE_MEMORY_BULK_ZBY_20260613: semantic_bulk_013",
                    "importance": 0.99,
                    "tags": ["fake"],
                },
            ]
            self.kg_relations = [
                {
                    "subject": "user",
                    "relation": "is_working_on",
                    "obj": "ecommerce transaction system",
                    "confidence": 0.95,
                }
            ]

    client = _FakeMemoryClient("http://mem")
    monkeypatch.setattr(memory_distill_worker, "MemoryClient", lambda base_url: client)

    memory_distill_worker._store_distilled_memories(
        base_url="http://mem",
        job=job,
        result=_PollutedParsed(),
    )

    tiers = [call[1].get("tier") for call in client.calls if call[0] == "memory_write"]
    assert "semantic" not in tiers
    assert "graph" not in tiers
    assert "stm" not in tiers


def test_question_answer_distill_keeps_only_conversation_checkpoint(monkeypatch):
    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="zhouboyang",
        conversation_id="conv_dw",
        round_id=1,
        messages=[
            {
                "role": "user",
                "content": (
                    "我现在这个 Northstar DW Ops 里，finance_mrr 的 freshness SLA 是什么？"
                    "它上游依赖什么？"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "marts.finance_mrr 的 SLA 是每天 08:30 Asia/Shanghai，"
                    "上游依赖 fact_orders。"
                ),
            },
        ],
        last_user=(
            "我现在这个 Northstar DW Ops 里，finance_mrr 的 freshness SLA 是什么？"
            "它上游依赖什么？"
        ),
        assistant_answer=(
            "marts.finance_mrr 的 SLA 是每天 08:30 Asia/Shanghai，"
            "上游依赖 fact_orders。"
        ),
    )

    class _QuestionAnswerParsed(_ParsedResult):
        def __init__(self):
            super().__init__()
            self.stm_summary = {
                "user_request": job.last_user,
                "final_answer": job.assistant_answer,
                "memories_used": ["semantic", "graph"],
            }
            self.semantic_facts = [
                {
                    "text": (
                        "marts.finance_mrr 的 freshness SLA 是每天 08:30 Asia/Shanghai，"
                        "上游依赖 fact_orders。"
                    ),
                    "importance": 0.99,
                }
            ]
            self.kg_relations = [
                {
                    "subject": "marts.finance_mrr",
                    "relation": "depends_on",
                    "obj": "fact_orders",
                    "confidence": 0.99,
                }
            ]

    client = _FakeMemoryClient("http://mem")
    monkeypatch.setattr(memory_distill_worker, "MemoryClient", lambda base_url: client)

    memory_distill_worker._store_distilled_memories(
        base_url="http://mem",
        job=job,
        result=_QuestionAnswerParsed(),
    )

    tiers = [call[1].get("tier") for call in client.calls if call[0] == "memory_write"]
    assert tiers == ["stm"]


def test_worker_main_once(monkeypatch):
    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="u",
        conversation_id="c",
        round_id=1,
        messages=[],
        last_user="hi",
        assistant_answer="ok",
    )

    settings = types.SimpleNamespace(
        enabled=True,
        provider="openai",
        model="gpt",
        temperature=0.1,
        max_output_tokens=100,
        queue_key="distill:q",
        llm_max_attempts=2,
        llm_retry_base_sleep_s=0.1,
        openai_api_key=None,
        openai_base_url=None,
        azure_api_key=None,
        azure_endpoint=None,
        azure_deployment=None,
        azure_api_version="2024",
    )

    monkeypatch.setattr(
        memory_distill_worker.MemoryDistillSettings, "from_env", lambda: settings
    )
    monkeypatch.setattr(memory_distill_worker, "pop_distill_job", lambda *a, **k: job)
    monkeypatch.setattr(
        memory_distill_worker, "build_distill_messages", lambda *a, **k: []
    )
    calls = {"n": 0}

    def _fake_call_distill_llm(*_a, **_k):
        # First call: structured distill (pretend provider returns '{}', which parses to empty stm_summary).
        # Second call: plain-text STM checkpoint fallback.
        calls["n"] += 1
        return "{}" if calls["n"] == 1 else "checkpoint text"

    monkeypatch.setattr(
        memory_distill_worker, "call_distill_llm", _fake_call_distill_llm
    )

    class _EmptyParsed(_ParsedResult):
        def __init__(self):
            super().__init__()
            self.stm_summary = {}

    monkeypatch.setattr(
        memory_distill_worker, "parse_distill_output", lambda *_: _EmptyParsed()
    )
    monkeypatch.setattr(
        memory_distill_worker, "record_job_result", lambda *a, **k: None
    )
    monkeypatch.setattr(
        memory_distill_worker, "requeue_with_backoff", lambda *a, **k: None
    )
    monkeypatch.setattr(memory_distill_worker, "MemoryClient", _FakeMemoryClient)

    monkeypatch.setattr(
        "sys.argv",
        ["memory_distill_worker.py", "--once"],
    )
    result = memory_distill_worker.main()
    assert result == 0


def test_worker_falls_back_to_deterministic_summary_when_llm_returns_empty(monkeypatch):
    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="u",
        conversation_id="c",
        round_id=10,
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok"},
        ],
        last_user="hi",
        assistant_answer="ok",
        prior_stm_summaries=[{"final_answer": "prev"}],
        chunk_rounds=10,
    )

    settings = types.SimpleNamespace(
        enabled=True,
        provider="openai",
        model="gpt",
        temperature=0.1,
        max_output_tokens=100,
        queue_key="distill:q",
        llm_max_attempts=2,
        llm_retry_base_sleep_s=0.1,
        openai_api_key=None,
        openai_base_url=None,
        azure_api_key=None,
        azure_endpoint=None,
        azure_deployment=None,
        azure_api_version="2024",
    )

    calls = {"n": 0}

    def _fake_call_distill_llm(*_a, **_k):
        calls["n"] += 1
        return "{}" if calls["n"] == 1 else ""

    class _EmptyParsed(_ParsedResult):
        def __init__(self):
            super().__init__()
            self.stm_summary = {}

    client = _FakeMemoryClient("http://mem")
    monkeypatch.setattr(
        memory_distill_worker.MemoryDistillSettings, "from_env", lambda: settings
    )
    monkeypatch.setattr(memory_distill_worker, "pop_distill_job", lambda *a, **k: job)
    monkeypatch.setattr(
        memory_distill_worker, "build_distill_messages", lambda *a, **k: []
    )
    monkeypatch.setattr(
        memory_distill_worker, "call_distill_llm", _fake_call_distill_llm
    )
    monkeypatch.setattr(
        memory_distill_worker, "parse_distill_output", lambda *_: _EmptyParsed()
    )
    monkeypatch.setattr(
        memory_distill_worker, "record_job_result", lambda *a, **k: None
    )
    monkeypatch.setattr(
        memory_distill_worker, "requeue_with_backoff", lambda *a, **k: None
    )
    monkeypatch.setattr(memory_distill_worker, "MemoryClient", lambda base_url: client)

    monkeypatch.setattr(
        "sys.argv",
        ["memory_distill_worker.py", "--once"],
    )
    assert memory_distill_worker.main() == 0
    stm_calls = [
        call[1]
        for call in client.calls
        if call[0] == "memory_write" and call[1].get("tier") == "stm"
    ]
    assert stm_calls
    assert "(empty summary)" not in stm_calls[0].get("content", "")


def test_worker_disabled(monkeypatch):
    settings = types.SimpleNamespace(enabled=False)
    monkeypatch.setattr(
        memory_distill_worker.MemoryDistillSettings, "from_env", lambda: settings
    )
    monkeypatch.setattr(
        "sys.argv",
        ["memory_distill_worker.py", "--once"],
    )
    assert memory_distill_worker.main() == 2
