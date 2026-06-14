from agent_memory_framework.memory_runtime.memory_safety import (
    allows_durable_distill_from_user_messages,
    contains_synthetic_marker,
    filter_preferences,
    is_user_grounded,
    should_persist_distilled_memory,
)


def test_synthetic_memory_markers_are_rejected():
    payload = {
        "text": "FAKE_MEMORY_BULK_ZBY_20260613: semantic_bulk_013",
        "metadata": {"source": "manual_bulk_fake_seed", "tags": ["fake"]},
    }

    assert contains_synthetic_marker(payload)
    assert not should_persist_distilled_memory(
        candidate_text=payload["text"],
        metadata=payload["metadata"],
        user_messages=["真实用户请求"],
    )


def test_filter_preferences_removes_internal_test_keys():
    prefs = {
        "response_style": "中文简洁",
        "bulk_pref_013": "FAKE_MEMORY_BULK_ZBY_20260613: preference noise",
        "preferred_name": "Zhou Boyang / 周博洋 (fake memory test)",
    }

    assert filter_preferences(prefs) == {"response_style": "中文简洁"}


def test_natural_language_test_markers_are_rejected():
    assert contains_synthetic_marker("这是测试记忆，不应该进入真实上下文")
    assert contains_synthetic_marker("Zhou Boyang / 周博洋 (fake memory test)")


def test_distilled_memory_requires_user_grounding():
    assert should_persist_distilled_memory(
        candidate_text="用户正在建设企业级 agent memory 平台",
        metadata={"source": "distill"},
        user_messages=["我们现在做的是企业级 agent memory 平台"],
    )

    assert not should_persist_distilled_memory(
        candidate_text="用户正在做电商/交易系统项目",
        metadata={"source": "distill"},
        user_messages=["你记得我现在在做什么产品吗？"],
    )


def test_uncertain_assistant_guess_is_not_durable_memory():
    assert not should_persist_distilled_memory(
        candidate_text="我猜你正在做一个电商/交易系统项目",
        metadata={"source": "distill"},
        user_messages=["你记得我现在在做什么产品吗？"],
        require_user_grounding=False,
    )


def test_user_grounding_allows_confirmed_chinese_preference():
    assert is_user_grounded(
        "用户偏好中文简洁回答",
        ["以后请用中文简洁回答"],
    )


def test_question_answer_should_not_promote_answer_values_to_durable_memory():
    user_messages = [
        "我现在这个 Northstar DW Ops 里，finance_mrr 的 freshness SLA 是什么？它上游依赖什么？"
    ]

    assert not allows_durable_distill_from_user_messages(user_messages)
    assert not should_persist_distilled_memory(
        candidate_text=(
            "marts.finance_mrr 的 freshness SLA 是每天 08:30 Asia/Shanghai 前完成刷新；"
            "上游依赖是 fact_orders。"
        ),
        metadata={"source": "distill"},
        user_messages=user_messages,
    )


def test_explicit_memory_directive_can_persist_grounded_specific_values():
    user_messages = [
        "请记住：marts.finance_mrr 的 freshness SLA 是每天 08:30 Asia/Shanghai，"
        "上游依赖 fact_orders。"
    ]

    assert allows_durable_distill_from_user_messages(user_messages)
    assert should_persist_distilled_memory(
        candidate_text=(
            "marts.finance_mrr 的 freshness SLA 是每天 08:30 Asia/Shanghai，"
            "上游依赖 fact_orders。"
        ),
        metadata={"source": "distill"},
        user_messages=user_messages,
    )
