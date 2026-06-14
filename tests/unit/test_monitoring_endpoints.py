import types

from agent_runtime.product.agent_gateway import portal_audit, portal_metrics
from agent_runtime.product.observability import AuditEvent, InMemoryObservabilityStore, MetricPoint


def test_monitoring_endpoints_return_sanitized_payload(monkeypatch) -> None:
    from agent_runtime.product import agent_gateway
    from agent_runtime.product.gateway import portal_helpers as ph
    from agent_runtime.product.gateway import portal_routes as pr

    user = types.SimpleNamespace(sub="u1", tenant_id="t_alice")
    monkeypatch.setattr(pr, "_me_from_access_token", lambda *_: user)
    monkeypatch.setattr(ph, "_role_for_me", lambda _me: "user")

    store = InMemoryObservabilityStore()
    monkeypatch.setattr(pr, "_obs_store", store)
    store.record_metric(
        MetricPoint(
            ts_s=1.0,
            tenant_id="t_alice",
            workspace_id="ws_default",
            name="chat.requests",
            value=1.0,
            tags={"agent": "code-assistant"},
        )
    )
    store.record_audit(
        AuditEvent(
            ts_s=2.0,
            tenant_id="t_alice",
            workspace_id="ws_default",
            actor="u1",
            action="chat.request",
            resource="agent:code-assistant",
            ok=True,
            detail={"authorization": "Bearer abc.def"},
        )
    )

    metrics = portal_metrics(token="t", tenant_id="t_alice", workspace_id="ws_default")
    assert metrics.metrics[0].value == 1.0

    audit = portal_audit(token="t", tenant_id="t_alice", workspace_id="ws_default")
    assert audit.audits[0].metadata["authorization"] == "Bearer [REDACTED]"
