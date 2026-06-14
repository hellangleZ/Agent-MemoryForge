import json

from agent_runtime.product import agent_gateway
from agent_runtime.product.auth_store import InMemoryAuthStore
from agent_runtime.product.auth_tokens import create_access_token


def test_custom_agent_crud(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_gateway, "_auth_store", InMemoryAuthStore())
    monkeypatch.setattr(agent_gateway, "_PORTAL_CONFIG_PATH", tmp_path / "portal_config.json")
    agent_gateway._PORTAL_CONFIG_PATH.write_text(
        json.dumps(
            {
                "workspace_members": {
                    "t_alice": {"ws1": [{"user_id": "alice", "role": "owner"}]}
                }
            }
        ),
        encoding="utf-8",
    )

    token = create_access_token(sub="alice", tenant_id="t_alice", expires_in_s=60)

    req = agent_gateway.PortalAgentUpsertRequest(
        id="agent_one",
        name="Agent One",
        description="Custom agent",
        system_prompt="You are a custom agent.",
        tools=["mcp.search"],
    )

    created = agent_gateway.portal_upsert_agent(
        req,
        token=token,
        workspace_id="ws1",
    )
    assert created["status"] == "success"
    assert created["data"]["id"] == "agent_one"

    listed = agent_gateway.portal_list_agents(token=token, workspace_id="ws1")
    assert "agent_one" in listed["agents"]
    assert listed["agents"]["agent_one"]["custom"] is True

    deleted = agent_gateway.portal_delete_agent(
        "agent_one",
        token=token,
        workspace_id="ws1",
    )
    assert deleted["status"] == "success"

    listed_after = agent_gateway.portal_list_agents(token=token, workspace_id="ws1")
    assert "agent_one" not in listed_after["agents"]
