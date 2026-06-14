from __future__ import annotations

import pytest

from agent_runtime.product.usage_store import (
    SQLiteUsageStore,
    estimate_message_tokens,
)


@pytest.mark.unit
def test_usage_store_records_and_summarizes_monthly_tokens(tmp_path):
    store = SQLiteUsageStore(db_path=str(tmp_path / "usage.db"))

    store.record_usage(
        tenant_id="t1",
        workspace_id="w1",
        user_id="alice",
        agent_id="pm-minimal",
        model="gpt-test",
        input_tokens=4,
        output_tokens=6,
        status="success",
        trace_id="trace-1",
        month="2026-06",
        ts_s=1,
    )
    store.record_usage(
        tenant_id="t1",
        workspace_id="w1",
        user_id="alice",
        agent_id="pm-minimal",
        model="gpt-test",
        input_tokens=2,
        output_tokens=3,
        status="success",
        trace_id="trace-2",
        month="2026-06",
        ts_s=2,
    )

    rows = store.list_usage_summary(
        tenant_id="t1", workspace_id="w1", month="2026-06"
    )

    assert len(rows) == 1
    assert rows[0].user_id == "alice"
    assert rows[0].request_count == 2
    assert rows[0].input_tokens == 6
    assert rows[0].output_tokens == 9
    assert rows[0].total_tokens == 15


@pytest.mark.unit
def test_usage_store_enforces_user_workspace_quota(tmp_path):
    store = SQLiteUsageStore(db_path=str(tmp_path / "usage.db"))
    store.set_quota(
        tenant_id="t1",
        workspace_id="w1",
        user_id="alice",
        monthly_token_quota=10,
        enabled=True,
    )
    store.record_usage(
        tenant_id="t1",
        workspace_id="w1",
        user_id="alice",
        agent_id="pm-minimal",
        model="gpt-test",
        input_tokens=4,
        output_tokens=4,
        status="success",
        month="2026-06",
        ts_s=1,
    )

    allowed = store.check_quota(
        tenant_id="t1",
        workspace_id="w1",
        user_id="alice",
        estimated_tokens=2,
        month="2026-06",
    )
    blocked = store.check_quota(
        tenant_id="t1",
        workspace_id="w1",
        user_id="alice",
        estimated_tokens=3,
        month="2026-06",
    )

    assert allowed.allowed is True
    assert allowed.remaining_tokens == 2
    assert blocked.allowed is False
    assert blocked.remaining_tokens == 2
    assert blocked.blocked is True


@pytest.mark.unit
def test_usage_store_disabled_quota_does_not_block(tmp_path):
    store = SQLiteUsageStore(db_path=str(tmp_path / "usage.db"))
    store.set_quota(
        tenant_id="t1",
        workspace_id="w1",
        user_id="alice",
        monthly_token_quota=1,
        enabled=False,
    )

    decision = store.check_quota(
        tenant_id="t1",
        workspace_id="w1",
        user_id="alice",
        estimated_tokens=100,
        month="2026-06",
    )

    assert decision.allowed is True
    assert decision.quota_enabled is False


@pytest.mark.unit
def test_estimate_message_tokens_counts_content_and_roles():
    count = estimate_message_tokens(
        [
            {"role": "user", "content": "hello world"},
            {"role": "assistant", "content": "你好世界"},
        ]
    )

    assert count >= 4
