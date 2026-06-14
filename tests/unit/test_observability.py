from agent_runtime.product.observability import (
    AuditEvent,
    InMemoryObservabilityStore,
    MetricPoint,
    RedisObservabilityStore,
    redact,
)


class _FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    def rpush(self, key, value):
        self.ops.append(("rpush", key, value))
        return self

    def ltrim(self, key, start, end):
        self.ops.append(("ltrim", key, start, end))
        return self

    def execute(self):
        for op in self.ops:
            name, *args = op
            getattr(self.redis, name)(*args)


class _FakeRedis:
    def __init__(self):
        self.lists = {}

    def pipeline(self, transaction=True):
        return _FakePipeline(self)

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def ltrim(self, key, start, end):
        items = self.lists.get(key, [])
        if start < 0:
            start = max(0, len(items) + start)
        if end < 0:
            end = len(items) + end
        self.lists[key] = items[start : end + 1]

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        if start < 0:
            start = max(0, len(items) + start)
        if end < 0:
            end = len(items) + end
        return items[start : end + 1]


def test_redact_masks_secret_keys_and_bearer_tokens() -> None:
    payload = {
        "api_key": "sk-123",
        "nested": {"token": "tok_456", "ok": True},
        "auth": "Bearer abc.def.ghi",
        "prompt": "key sk-abc1234567890 should be hidden and password=supersecret",
        "keep": "hello",
    }
    redacted = redact(payload)
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert redacted["nested"]["ok"] is True
    assert redacted["auth"] == "Bearer [REDACTED]"
    assert "sk-abc" not in redacted["prompt"]
    assert "supersecret" not in redacted["prompt"]
    assert redacted["keep"] == "hello"


def test_observability_store_filters_by_tenant_and_workspace() -> None:
    store = InMemoryObservabilityStore(max_events=10, max_metrics=10)

    store.record_metric(
        MetricPoint(
            ts_s=1.0,
            tenant_id="t1",
            workspace_id="w1",
            name="chat.requests",
            value=1.0,
            tags={"agent": "a"},
        )
    )
    store.record_metric(
        MetricPoint(
            ts_s=2.0,
            tenant_id="t2",
            workspace_id="w1",
            name="chat.requests",
            value=1.0,
            tags={"agent": "a"},
        )
    )
    points = store.query_metrics(tenant_id="t1", workspace_id="w1")
    assert [p.tenant_id for p in points] == ["t1"]

    store.record_audit(
        AuditEvent(
            ts_s=3.0,
            tenant_id="t1",
            workspace_id="w1",
            actor="u",
            action="chat.request",
            resource="agent:a",
            ok=True,
            detail={"token": "secret"},
        )
    )
    store.record_audit(
        AuditEvent(
            ts_s=4.0,
            tenant_id="t1",
            workspace_id="w2",
            actor="u",
            action="chat.request",
            resource="agent:a",
            ok=True,
        )
    )
    events = store.query_audit(tenant_id="t1", workspace_id="w1")
    assert len(events) == 1
    assert events[0].workspace_id == "w1"


def test_redis_observability_store_roundtrips_audit_and_metrics() -> None:
    store = RedisObservabilityStore(redis_client=_FakeRedis(), max_events=10, max_metrics=10)

    store.record_audit(
        AuditEvent(
            ts_s=1.0,
            tenant_id="t1",
            workspace_id="w1",
            actor="u",
            action="chat.request",
            resource="agent:a",
            ok=True,
            detail={"trace_id": "tr1"},
        )
    )
    store.record_metric(
        MetricPoint(
            ts_s=2.0,
            tenant_id="t1",
            workspace_id="w1",
            name="chat.requests",
            value=1.0,
            tags={"agent": "a"},
        )
    )

    assert store.query_audit(tenant_id="t1", workspace_id="w1")[0].detail == {"trace_id": "tr1"}
    assert store.query_metrics(tenant_id="t1", workspace_id="w1")[0].name == "chat.requests"
