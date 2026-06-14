import pytest

from agent_memory_framework.llm import normalize_tool_calls
from utils.exceptions import LLMClientError


class _AzureFunctionCall:
    type = "function_call"

    def __init__(self, name: str | None, arguments, call_id: str = "c1"):
        self.name = name
        self.arguments = arguments
        self.call_id = call_id


class _AzureResponse:
    def __init__(self, outputs):
        self.output = outputs


def test_normalize_tool_calls_azure_shape():
    raw = _AzureResponse([_AzureFunctionCall("search", {"q": "x"}, call_id="id_1")])
    out = normalize_tool_calls(raw, trace_id="t1")
    assert out == [{"id": "id_1", "name": "search", "arguments": {"q": "x"}}]


def test_normalize_tool_calls_chat_completions_shape():
    raw = {
        "tool_calls": [
            {"id": "id_2", "function": {"name": "lookup", "arguments": {"k": 1}}}
        ]
    }
    out = normalize_tool_calls(raw)
    assert out == [{"id": "id_2", "name": "lookup", "arguments": {"k": 1}}]


def test_normalize_tool_calls_nested_chat_completions_shape():
    raw = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "id_3",
                            "function": {
                                "name": "lookup",
                                "arguments": '{"k": 1}',
                            },
                        }
                    ]
                }
            }
        ]
    }

    out = normalize_tool_calls(raw)

    assert out == [{"id": "id_3", "name": "lookup", "arguments": '{"k": 1}'}]


def test_normalize_tool_calls_chat_completion_object_shape():
    function = type(
        "Function",
        (),
        {"name": "lookup", "arguments": '{"k": 2}'},
    )()
    tool_call = type(
        "ToolCall",
        (),
        {"id": "id_4", "function": function},
    )()
    message = type("Message", (), {"tool_calls": [tool_call]})()
    choice = type("Choice", (), {"message": message})()
    raw = type("ChatCompletion", (), {"choices": [choice]})()

    out = normalize_tool_calls(raw)

    assert out == [{"id": "id_4", "name": "lookup", "arguments": '{"k": 2}'}]


def test_normalize_tool_calls_invalid_missing_name_raises():
    raw = _AzureResponse([_AzureFunctionCall(None, {"q": "x"})])
    with pytest.raises(LLMClientError):
        normalize_tool_calls(raw, trace_id="t2")
