def test_memory_service_does_not_expose_agent_or_tool_discovery() -> None:
    from agent_memory_service.app import create_app

    paths = {getattr(route, "path", None) for route in create_app().routes}
    assert "/v1/agents" not in paths
    assert "/v1/tools" not in paths
    assert "/v1/tools/flat" not in paths
