import pytest

from agent_memory_framework.memory_runtime.context_planner import ContextPlan, _parse_plan


@pytest.mark.unit
def test_context_planner_parse_accepts_strict_json():
    defaults = ContextPlan(
        include_wm=True,
        preference_keys=["a"],
        stm_last_k=15,
        semantic_top_k=5,
    )

    raw = (
        '{"include":{'
        '"wm":false,'
        '"preferences":{"enabled":true,"keys":["x","y"]},'
        '"stm":{"enabled":true,"last_k":7},'
        '"semantic":{"enabled":true,"top_k":3}'
        '},"notes":"ok"}'
    )
    out = _parse_plan(raw, defaults)
    assert out.include_wm is False
    assert out.include_preferences is True
    assert out.preference_keys == ["x", "y"]
    assert out.stm_last_k == 7
    assert out.semantic_top_k == 3


@pytest.mark.unit
def test_context_planner_parse_fallback_on_garbage():
    defaults = ContextPlan(
        include_wm=True,
        preference_keys=["a"],
        stm_last_k=15,
        semantic_top_k=5,
    )
    out = _parse_plan("not json", defaults)
    assert out == defaults


@pytest.mark.unit
def test_context_planner_parse_preserves_explicit_preference_opt_out():
    defaults = ContextPlan(
        include_wm=True,
        preference_keys=[],
        stm_last_k=15,
        semantic_top_k=5,
    )

    out = _parse_plan(
        '{"include":{"preferences":{"enabled":false}}}',
        defaults,
    )

    assert out.include_preferences is False


@pytest.mark.unit
def test_context_planner_cannot_override_disabled_preference_policy():
    defaults = ContextPlan(
        include_wm=True,
        preference_keys=[],
        stm_last_k=15,
        semantic_top_k=5,
        include_preferences=False,
    )

    out = _parse_plan(
        '{"include":{"preferences":{"enabled":true,"keys":["secret"]}}}',
        defaults,
    )

    assert out.include_preferences is False


@pytest.mark.unit
def test_context_planner_cannot_widen_disabled_memory_limits():
    defaults = ContextPlan(
        include_wm=True,
        preference_keys=[],
        stm_last_k=0,
        semantic_top_k=0,
    )

    out = _parse_plan(
        '{"include":{"stm":{"enabled":true,"last_k":10},'
        '"semantic":{"enabled":true,"top_k":10}}}',
        defaults,
    )

    assert out.stm_last_k == 0
    assert out.semantic_top_k == 0
