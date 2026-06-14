from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from utils.exceptions import LLMClientError


@dataclass(frozen=True)
class LLMResult:
    """Normalized LLM output.

    This is intentionally minimal for STORY-001. Tool-call normalization is
    handled in STORY-002.
    """

    text: str
    raw: Any | None = None
    tool_calls: List[Dict[str, Any]] | None = None
    trace_id: str | None = None


class LLMProvider(Protocol):
    def generate(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: float = 0.2,
        trace_id: str | None = None,
    ) -> LLMResult: ...


class CallableLLMProvider:
    """Adapter for existing callables used in demo code."""

    def __init__(self, call_fn):
        self._call_fn = call_fn

    def generate(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: float = 0.2,
        trace_id: str | None = None,
    ) -> LLMResult:
        try:
            raw = self._call_fn(messages)
        except Exception as exc:
            raise LLMClientError(
                "LLM provider call failed",
                details={"trace_id": trace_id, "error": str(exc)},
            ) from exc

        text: Optional[str] = None
        # Azure responses API shape (used in this repo) typically exposes
        # output_text.
        text = getattr(raw, "output_text", None)
        if not text:
            try:
                choices = getattr(raw, "choices", None)
                if choices:
                    message = getattr(choices[0], "message", None)
                    content = getattr(message, "content", None)
                    if content:
                        text = str(content)
            except Exception:
                pass
        if not text:
            # best-effort fallback
            text = str(raw)
        tool_calls = normalize_tool_calls(raw, trace_id=trace_id)
        return LLMResult(text=text, raw=raw, tool_calls=tool_calls, trace_id=trace_id)


def normalize_tool_calls(
    raw: Any, *, trace_id: str | None = None
) -> List[Dict[str, Any]]:
    """Extract and normalize tool calls from common provider shapes.

    Returns a list of dicts with keys: id, name, arguments.
    Invalid shapes raise LLMClientError for safe handling by the execution loop.
    """

    if raw is None:
        return []

    tool_calls: List[Dict[str, Any]] = []

    if hasattr(raw, "output"):
        outputs = getattr(raw, "output")
        if outputs is None:
            return []
        for output in outputs:
            if getattr(output, "type", None) != "function_call":
                continue
            name = getattr(output, "name", None)
            arguments = getattr(output, "arguments", None)
            if not name:
                raise LLMClientError(
                    "Invalid tool call: missing name",
                    details={"trace_id": trace_id},
                )
            tool_calls.append(
                {
                    "id": getattr(output, "call_id", "") or "",
                    "name": name,
                    "arguments": arguments,
                }
            )
        return tool_calls

    if isinstance(raw, dict):
        tc_list = raw.get("tool_calls")
        if tc_list is None:
            choices = raw.get("choices")
            if isinstance(choices, list) and choices:
                first_choice = choices[0]
                if isinstance(first_choice, dict):
                    message = first_choice.get("message")
                    if isinstance(message, dict):
                        tc_list = message.get("tool_calls")
        if tc_list is None:
            return []
        if not isinstance(tc_list, list):
            raise LLMClientError(
                "Invalid tool_calls: expected list",
                details={"trace_id": trace_id, "tool_calls_type": str(type(tc_list))},
            )

        for tc in tc_list:
            if not isinstance(tc, dict):
                raise LLMClientError(
                    "Invalid tool call: expected dict",
                    details={"trace_id": trace_id},
                )
            fn = tc.get("function")
            if not isinstance(fn, dict):
                raise LLMClientError(
                    "Invalid tool call: missing function object",
                    details={"trace_id": trace_id},
                )
            name = fn.get("name")
            if not name:
                raise LLMClientError(
                    "Invalid tool call: missing function.name",
                    details={"trace_id": trace_id},
                )
            tool_calls.append(
                {
                    "id": tc.get("id", "") or "",
                    "name": name,
                    "arguments": fn.get("arguments"),
                }
            )

        return tool_calls

    choices = getattr(raw, "choices", None)
    if choices:
        first_choice = choices[0]
        message = getattr(first_choice, "message", None)
        tc_list = getattr(message, "tool_calls", None) if message is not None else None
        if tc_list is None:
            return []
        for tc in tc_list:
            fn = getattr(tc, "function", None)
            name = getattr(fn, "name", None)
            if not name:
                raise LLMClientError(
                    "Invalid tool call: missing function.name",
                    details={"trace_id": trace_id},
                )
            tool_calls.append(
                {
                    "id": getattr(tc, "id", "") or "",
                    "name": name,
                    "arguments": getattr(fn, "arguments", None),
                }
            )
        return tool_calls

    return []


__all__ = ["CallableLLMProvider", "LLMProvider", "LLMResult", "normalize_tool_calls"]
