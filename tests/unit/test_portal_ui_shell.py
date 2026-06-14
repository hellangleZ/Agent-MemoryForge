from agent_runtime.product.agent_gateway import _portal_shell_html


def test_portal_shell_contains_expected_routes() -> None:
    html = _portal_shell_html()

    # Basic landmarks
    assert "Agent Portal" in html

    # Expected page routes from PRD
    assert "/portal/signup" in html
    assert "/portal/login" in html
    assert "/portal/workspaces" in html
    assert "/portal/agents" in html
    assert "/portal/chat/" in html
    assert "/portal/runs" in html
    assert "/portal/monitoring" in html

    # API integration points
    assert "/portal/v1/signup" in html
    assert "/portal/v1/login" in html
    assert "/portal/v1/me" in html
    assert "/v1/agents" in html
    assert "/v1/chat" in html
