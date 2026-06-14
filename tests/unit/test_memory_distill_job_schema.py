import pytest

from agent_runtime.memory_distill.job_schema import (
    content_fingerprint,
    new_job,
    stable_job_id,
)


@pytest.mark.unit
def test_stable_job_id_is_deterministic():
    a = stable_job_id(
        tenant_id="t1", workspace_id="w1", conversation_id="c1", round_id=1
    )
    b = stable_job_id(
        tenant_id="t1", workspace_id="w1", conversation_id="c1", round_id=1
    )
    assert a == b


@pytest.mark.unit
def test_new_job_contains_required_fields():
    job = new_job(
        tenant_id="t1",
        workspace_id="w1",
        user_id="u1",
        conversation_id="c1",
        round_id=3,
        messages=[{"role": "user", "content": "hi"}],
        last_user="hi",
        assistant_answer="hello",
        trace_id="tr",
    )
    assert job.job_id
    assert job.round_id == 3
    assert job.last_user == "hi"
    assert job.assistant_answer == "hello"


@pytest.mark.unit
def test_new_job_stable_id_changes_when_round_content_changes():
    base = {
        "tenant_id": "t1",
        "workspace_id": "w1",
        "user_id": "u1",
        "conversation_id": "c1",
        "round_id": 3,
    }
    first = new_job(
        **base,
        messages=[{"role": "user", "content": "remember answer in short Chinese"}],
        last_user="remember answer in short Chinese",
        assistant_answer="ok",
    )
    duplicate = new_job(
        **base,
        messages=[{"role": "user", "content": "remember answer in short Chinese"}],
        last_user="remember answer in short Chinese",
        assistant_answer="ok",
    )
    changed = new_job(
        **base,
        messages=[{"role": "user", "content": "finance_mrr SLA is 09:00"}],
        last_user="finance_mrr SLA is 09:00",
        assistant_answer="noted",
    )

    assert first.job_id == duplicate.job_id
    assert first.job_id != changed.job_id


@pytest.mark.unit
def test_content_fingerprint_is_stable_for_equivalent_payloads():
    a = content_fingerprint(
        messages=[{"content": "hi", "role": "user"}],
        last_user="hi",
        assistant_answer="hello",
        chunk_rounds=1,
    )
    b = content_fingerprint(
        messages=[{"role": "user", "content": "hi"}],
        last_user="hi",
        assistant_answer="hello",
        chunk_rounds=1,
    )
    c = content_fingerprint(
        messages=[{"role": "user", "content": "hi"}],
        last_user="hi",
        assistant_answer="different",
        chunk_rounds=1,
    )

    assert a == b
    assert a != c
