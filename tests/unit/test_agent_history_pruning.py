"""Tests for conversation history pruning in agent.py."""
from __future__ import annotations


from agent_memory_framework.agent import Agent, MAX_HISTORY_SIZE
from agent_memory_framework.llm import CallableLLMProvider
from agent_memory_framework.runtime import Runtime
from agent_memory_framework.settings import Settings


class _FakeResponse:
    def __init__(self, output_text: str):
        self.output_text = output_text


class _TestAgent(Agent):
    """Concrete agent implementation for testing."""

    def system_prompt(self) -> str:
        return "You are a test agent."

    def register_tools(self, registry) -> None:
        pass  # No tools for test agent


def test_history_pruning_keeps_recent_messages():
    """Verify that pruning keeps the most recent messages."""
    call_count = 0

    def llm_call(messages):
        nonlocal call_count
        call_count += 1
        return _FakeResponse(output_text=f"response_{call_count}")

    runtime = Runtime(
        agent_id="test_agent",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(llm_call),
        conversation_id="c_1",
        settings=Settings(),
    )

    agent = _TestAgent(runtime)

    # Run more turns than MAX_HISTORY_SIZE allows
    for i in range(MAX_HISTORY_SIZE + 20):
        agent.run_turn(f"query_{i}")

    # History should be pruned to MAX_HISTORY_SIZE or less
    assert len(agent.conversation_history) <= MAX_HISTORY_SIZE

    # The most recent messages should be preserved
    last_user_msg = agent.conversation_history[-2]  # Second to last is user
    last_assistant_msg = agent.conversation_history[-1]  # Last is assistant

    assert last_user_msg["role"] == "user"
    assert last_assistant_msg["role"] == "assistant"


def test_history_pruning_maintains_pairs():
    """Verify that pruning maintains user/assistant message pairs."""
    call_count = 0

    def llm_call(messages):
        nonlocal call_count
        call_count += 1
        return _FakeResponse(output_text=f"response_{call_count}")

    runtime = Runtime(
        agent_id="test_agent",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(llm_call),
        conversation_id="c_1",
        settings=Settings(),
    )

    agent = _TestAgent(runtime)

    # Run an odd number of turns
    for i in range(MAX_HISTORY_SIZE + 11):
        agent.run_turn(f"query_{i}")

    # History should have even number of messages (user/assistant pairs)
    assert len(agent.conversation_history) % 2 == 0

    # Verify alternation
    for i, msg in enumerate(agent.conversation_history):
        expected_role = "user" if i % 2 == 0 else "assistant"
        assert msg["role"] == expected_role, f"Message {i} has wrong role"


def test_history_no_pruning_when_within_limit():
    """Verify that pruning doesn't happen when within limit."""
    def llm_call(messages):
        return _FakeResponse(output_text="ok")

    runtime = Runtime(
        agent_id="test_agent",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(llm_call),
        conversation_id="c_1",
        settings=Settings(),
    )

    agent = _TestAgent(runtime)

    # Run fewer turns than MAX_HISTORY_SIZE
    turns = 10
    for i in range(turns):
        agent.run_turn(f"query_{i}")

    # History should have exactly turns * 2 messages (user + assistant per turn)
    assert len(agent.conversation_history) == turns * 2


def test_history_pruning_removes_oldest():
    """Verify that pruning removes the oldest messages first."""
    call_count = 0

    def llm_call(messages):
        nonlocal call_count
        call_count += 1
        return _FakeResponse(output_text=f"response_{call_count}")

    runtime = Runtime(
        agent_id="test_agent",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(llm_call),
        conversation_id="c_1",
        settings=Settings(),
    )

    agent = _TestAgent(runtime)

    # Run enough turns to trigger pruning
    total_turns = MAX_HISTORY_SIZE + 5
    for i in range(total_turns):
        agent.run_turn(f"query_{i}")

    # First message should NOT be query_0 (it should have been pruned)
    first_user_msg = agent.conversation_history[0]
    assert not first_user_msg["content"].startswith("query_0")

    # Last messages should be the most recent
    last_user_msg = agent.conversation_history[-2]
    assert last_user_msg["content"] == f"query_{total_turns - 1}"


def test_prune_history_is_private():
    """Verify that _prune_history is a private method."""
    from inspect import ismethod

    runtime = Runtime(
        agent_id="test_agent",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(lambda m: _FakeResponse("ok")),
        conversation_id="c_1",
        settings=Settings(),
    )

    agent = _TestAgent(runtime)
    assert hasattr(agent, "_prune_history")
    assert ismethod(agent._prune_history)
