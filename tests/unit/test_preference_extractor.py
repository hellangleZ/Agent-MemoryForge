import pytest

from agent_runtime.product.preference_extractor import (
    extract_preferences_rule_based,
    two_stage_preferences,
)


@pytest.mark.unit
def test_rule_extract_favorite_language_en():
    out = extract_preferences_rule_based("My favorite language is Python.")
    assert any(c.key == "favorite_language" and "Python" in str(c.value) for c in out)


@pytest.mark.unit
def test_two_stage_requires_llm_validation():
    # Rule hits, but validator must still pass; our fake validator will reject.
    def llm_call(_messages):
        class _Resp:
            output_text = '{"accept": false, "confidence": 0.1}'

        return _Resp()

    prefs = two_stage_preferences(
        user_text="My favorite language is Python.",
        llm_call_fn=llm_call,
        allowed_keys=["favorite_language"],
        extract_llm_when_no_rule=False,
        min_validation_confidence=0.7,
    )
    assert prefs == []
