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
