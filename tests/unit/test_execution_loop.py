from agent_memory_framework.execution_loop import ExecutionLoop
from agent_memory_framework.tools import ToolRegistry


def test_execution_loop_stops_repeated_identical_tool_calls_before_max_turns():
    registry = ToolRegistry()
    executed = []

    registry.register(
        name="repeat_me",
        func=lambda value: executed.append(value) or {"status": "success"},
        category="test",
        schema={
            "description": "repeat test tool",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
    )

    def llm_call(_messages, previous_response_id=None):
        return {
            "tool_calls": [
                {
                    "id": "call_repeat",
                    "function": {
                        "name": "repeat_me",
                        "arguments": '{"value":"same"}',
                    },
                }
            ]
        }

    loop = ExecutionLoop(
        agent_id="test_agent",
        llm_call_fn=llm_call,
        tool_registry=registry,
        config={"max_tool_turns": 12, "repeated_tool_call_limit": 3},
    )

    result = loop.run_single_turn([{"role": "user", "content": "hi"}])

    assert len(executed) == 3
    assert "重复工具调用" in result
    assert "maximum number of tool calls" not in result.lower()


def test_execution_loop_extracts_chat_completion_object_text():
    message = type("Message", (), {"content": "chat text"})()
    choice = type("Choice", (), {"message": message})()
    response = type("ChatCompletion", (), {"choices": [choice]})()

    loop = ExecutionLoop(
        agent_id="test_agent",
        llm_call_fn=lambda _messages: response,
        tool_registry=ToolRegistry(),
    )

    assert loop.run_single_turn([{"role": "user", "content": "hi"}]) == "chat text"


def test_execution_loop_zero_max_retries_still_calls_llm_once():
    calls = []

    def llm_call(messages):
        calls.append(messages)
        return "ok"

    loop = ExecutionLoop(
        agent_id="test_agent",
        llm_call_fn=llm_call,
        tool_registry=ToolRegistry(),
        config={"max_retries": 0},
    )

    assert loop.run_single_turn([{"role": "user", "content": "hi"}]) == "ok"
    assert len(calls) == 1
