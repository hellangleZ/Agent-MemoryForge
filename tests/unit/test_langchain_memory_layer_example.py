from examples.langchain_memory_layer_agent import (
    _percentile,
    _validate_answer,
    deterministic_customer_llm,
)


def test_deterministic_customer_llm_uses_memory_context():
    messages = [
        {
            "role": "system",
            "content": "finance_mrr SLA 09:00 owner Alice raw_invoices raw_payments",
        }
    ]

    answer = deterministic_customer_llm(messages=messages, question="finance_mrr?")

    assert "09:00" in answer
    assert "Alice" in answer
    assert "raw_invoices" in answer
    assert "raw_payments" in answer
    passed, missing = _validate_answer(answer)
    assert passed is True
    assert missing == []


def test_validate_answer_reports_missing_facts():
    passed, missing = _validate_answer("owner Alice")

    assert passed is False
    assert "09:00" in missing
    assert "raw_invoices" in missing


def test_percentile_interpolates():
    assert _percentile([10, 20, 30], 0.5) == 20
    assert _percentile([10, 20], 0.95) == 19.5
    assert _percentile([], 0.95) == 0.0
