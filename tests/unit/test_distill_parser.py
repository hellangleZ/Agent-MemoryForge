import pytest

from agent_memory_framework.memory_distill.distiller import parse_distill_output


@pytest.mark.unit
def test_parse_distill_output_accepts_strict_json():
    raw = '{"stm_summary":{"user_request":"x","final_answer":"y"},"semantic_facts":[],"preferences":[],"kg_relations":[]}'
    out = parse_distill_output(raw)
    assert out.stm_summary["user_request"] == "x"
    assert out.semantic_facts == []


@pytest.mark.unit
def test_parse_distill_output_strips_code_fences():
    raw = "```json\n{\"stm_summary\":{\"user_request\":\"x\",\"final_answer\":\"y\"},\"semantic_facts\":[],\"preferences\":[],\"kg_relations\":[]}\n```"
    out = parse_distill_output(raw)
    assert out.stm_summary["final_answer"] == "y"


@pytest.mark.unit
def test_parse_distill_output_fallback_on_garbage():
    out = parse_distill_output("not json")
    assert isinstance(out.stm_summary, dict)
    assert out.stm_summary.get("final_answer") == "not json"
    assert out.semantic_facts == []
