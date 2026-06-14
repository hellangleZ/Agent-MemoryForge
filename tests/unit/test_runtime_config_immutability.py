"""Tests for immutable config property in runtime.py."""
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

import pytest

from agent_memory_framework.llm import CallableLLMProvider
from agent_memory_framework.runtime import Runtime
from agent_memory_framework.settings import Settings


class _FakeResponse:
    def __init__(self, output_text: str):
        self.output_text = output_text


def test_config_returns_mapping_proxy():
    """Verify that config returns a MappingProxyType (immutable)."""
    runtime = Runtime(
        agent_id="test_agent",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(lambda m: _FakeResponse("ok")),
        conversation_id="c_1",
        settings=Settings(),
    )

    config = runtime.config
    assert isinstance(config, MappingProxyType)


def test_config_is_read_only():
    """Verify that config cannot be modified."""
    runtime = Runtime(
        agent_id="test_agent",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(lambda m: _FakeResponse("ok")),
        conversation_id="c_1",
        settings=Settings(),
    )

    config = runtime.config

    # Attempting to modify should raise TypeError
    with pytest.raises(TypeError):
        config["new_key"] = "new_value"

    with pytest.raises(TypeError):
        config["max_tool_turns"] = 999

    with pytest.raises(TypeError):
        del config["max_tool_turns"]


def test_config_contains_expected_keys():
    """Verify config contains the expected keys from settings."""
    settings = Settings(max_tool_turns=5)
    settings.extras["custom_option"] = "value"

    runtime = Runtime(
        agent_id="test_agent",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(lambda m: _FakeResponse("ok")),
        conversation_id="c_1",
        settings=settings,
    )

    config = runtime.config
    assert "max_tool_turns" in config
    assert config["max_tool_turns"] == 5
    assert "custom_option" in config
    assert config["custom_option"] == "value"


def test_config_is_mapping_type():
    """Verify config is a Mapping (read-only view)."""
    runtime = Runtime(
        agent_id="test_agent",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(lambda m: _FakeResponse("ok")),
        conversation_id="c_1",
        settings=Settings(),
    )

    config = runtime.config
    assert isinstance(config, Mapping)


def test_config_independence():
    """Verify that each call to config returns a new proxy (not shared state)."""
    settings = Settings(max_tool_turns=3)
    runtime = Runtime(
        agent_id="test_agent",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(lambda m: _FakeResponse("ok")),
        conversation_id="c_1",
        settings=settings,
    )

    config1 = runtime.config
    config2 = runtime.config

    # Each access returns a NEW proxy object (no shared mutable state)...
    assert config1 is not config2
    # ...but with equal values.
    assert config1 == config2
    assert config1["max_tool_turns"] == 3
    assert config2["max_tool_turns"] == 3


def test_config_iteration():
    """Verify config supports iteration like a dict."""
    settings = Settings(max_tool_turns=2)
    settings.extras["extra_key"] = "extra_value"

    runtime = Runtime(
        agent_id="test_agent",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(lambda m: _FakeResponse("ok")),
        conversation_id="c_1",
        settings=settings,
    )

    config = runtime.config
    keys = list(config.keys())
    assert "max_tool_turns" in keys
    assert "extra_key" in keys

    # Test iteration
    for key, value in config.items():
        assert isinstance(key, str)
        assert value is not None
