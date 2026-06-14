import pytest


@pytest.mark.unit
def test_discover_product_agents_includes_pm_minimal():
    from agent_runtime.product.agent_registry import discover_product_agents

    agents = discover_product_agents()
    assert "pm-minimal" in agents
    assert agents["pm-minimal"].spec


@pytest.mark.unit
def test_load_agent_class_accepts_pm_minimal_key():
    from agent_runtime.product.cli import _load_agent_class
    from agent_memory_framework.demo_agent import DemoAgent

    cls = _load_agent_class("pm-minimal")
    assert isinstance(cls, type)
    assert issubclass(cls, DemoAgent)
