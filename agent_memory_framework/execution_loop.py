"""Execution loop (SDK core).

Drives the agent tool-calling loop: call the LLM, parse tool calls, execute
tools, handle retries. Lives in the framework SDK so runtime/product layers
depend on the SDK, not the reverse.
"""

import json
import os
import time
from typing import Any, Callable, Dict, List, Optional

from utils.exceptions import LLMClientError
from utils.logging_config import get_logger

logger = get_logger(__name__)


class ExecutionLoop:
    """
    执行循环
    管理Agent的工具调用循环，负责：
    - 调用LLM
    - 解析工具调用
    - 执行工具
    - 处理错误和重试
    """

    def __init__(
        self,
        agent_id: str,
        llm_call_fn: Callable,
        tool_registry,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化执行循环

        Args:
            agent_id: Agent ID
            llm_call_fn: LLM调用函数
            tool_registry: 工具注册表
            config: 可选的配置字典
        """
        self.agent_id = agent_id
        self.llm_call_fn = llm_call_fn
        self.tool_registry = tool_registry
        self.config = config or {}

        self.max_tool_turns = self.config.get("max_tool_turns", 15)
        self.max_retries = self.config.get("max_retries", 3)
        try:
            self.repeated_tool_call_limit = max(
                0, int(self.config.get("repeated_tool_call_limit", 3))
            )
        except Exception:
            self.repeated_tool_call_limit = 3

        # Optional tool call hook for observability/UX (e.g. portal tool-usage).
        # Signature: hook(event_type: str, payload: Dict[str, Any]) -> None
        self.tool_call_hook = self.config.get("tool_call_hook")

        self.logger = get_logger(f"execution_loop.{agent_id}")

    def run_single_turn(
        self,
        messages: List[Dict[str, Any]],
        conversation_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        执行单轮对话

        Args:
            messages: 消息历史
            conversation_context: 可选的对话上下文

        Returns:
            Agent的最终响应

        Raises:
            LLMClientError: 执行失败
        """
        self.logger.debug("Starting single turn execution")

        turn_count = 0
        max_turns = self.max_tool_turns
        last_tool_signature = None
        repeated_tool_signature_count = 0

        # Responses API chaining (`previous_response_id`) is only valid within a
        # single turn's tool loop. Reset it here so a reused ExecutionLoop does
        # not leak a stale response id from a previous conversation round into a
        # fresh request (which the API rejects).
        self._previous_response_id = None

        while turn_count < max_turns:
            turn_count += 1
            self.logger.debug(f"Turn {turn_count}/{max_turns}")

            previous_response_id = getattr(self, "_previous_response_id", None)

            try:
                # 调用LLM
                call_exc: Exception | None = None
                response = None
                max_attempts = max(1, int(self.max_retries))

                for attempt in range(1, max_attempts + 1):
                    try:
                        if previous_response_id:
                            response = self.llm_call_fn(
                                messages, previous_response_id=previous_response_id
                            )
                        else:
                            response = self.llm_call_fn(messages)
                        call_exc = None
                        break
                    except Exception as exc:  # noqa: BLE001
                        call_exc = exc
                        msg = str(exc).lower()
                        retriable = any(
                            s in msg
                            for s in [
                                "error code: 500",
                                "server_error",
                                "error code: 429",
                                "rate_limit",
                                "timeout",
                                "temporarily",
                            ]
                        )
                        if not retriable or attempt >= max_attempts:
                            break
                        time.sleep(min(0.25 * attempt, 1.0))

                if call_exc is not None:
                    raise call_exc
                if os.getenv("EXECUTION_LOOP_DEBUG") == "1":
                    self.logger.info("LLM raw response type=%s", type(response))

                # Responses API tool loops require `previous_response_id` and
                # `function_call_output`. Keep a per-turn response_id if present.
                response_id = getattr(response, "id", None)

                # 检查是否有工具调用
                tool_calls = self._extract_tool_calls(response)
                if os.getenv("EXECUTION_LOOP_DEBUG") == "1":
                    self.logger.info("Extracted tool_calls=%s", tool_calls)

                if not tool_calls:
                    # 没有工具调用，返回文本响应
                    final_response = self._extract_text_response(response)
                    self.logger.info(
                        f"Completed in {turn_count} turns, "
                        f"response length: {len(final_response)}"
                    )
                    return final_response

                # 执行工具调用
                for tool_call in tool_calls:
                    tool_name = tool_call.get("name")
                    tool_args = tool_call.get("arguments", {})

                    # Some providers return tool arguments as a JSON string.
                    if isinstance(tool_args, str):
                        try:
                            import json

                            tool_args = json.loads(tool_args)
                        except Exception:
                            tool_args = {}

                    if not tool_name:
                        self.logger.warning("Skipping invalid tool call without name")
                        continue

                    if tool_args is None:
                        tool_args = {}

                    tool_signature = self._tool_call_signature(tool_name, tool_args)
                    if tool_signature == last_tool_signature:
                        repeated_tool_signature_count += 1
                    else:
                        last_tool_signature = tool_signature
                        repeated_tool_signature_count = 1
                    if (
                        self.repeated_tool_call_limit
                        and repeated_tool_signature_count
                        > self.repeated_tool_call_limit
                    ):
                        self.logger.warning(
                            "Stopping repeated tool call loop: %s repeated %s times",
                            tool_name,
                            repeated_tool_signature_count,
                        )
                        return (
                            "我停止了重复工具调用，避免继续空转。"
                            f"重复的工具是：{tool_name}。请换个更具体的问题再试。"
                        )

                    self.logger.debug(f"Executing tool: {tool_name}")

                    if callable(self.tool_call_hook):
                        try:
                            self.tool_call_hook(
                                "tool.start",
                                {
                                    "tool_name": tool_name,
                                    "tool_args": tool_args,
                                    "tool_call_id": tool_call.get("id", ""),
                                },
                            )
                        except Exception:
                            pass

                    # 执行工具
                    tool_started_s = time.monotonic()
                    try:
                        tool_result = self.tool_registry.execute(tool_name, **tool_args)
                    except TypeError as exc:
                        self.logger.warning(
                            "Tool args validation failed for %s: %s",
                            tool_name,
                            exc,
                        )
                        tool_result = {
                            "status": "error",
                            "error": f"invalid tool arguments for {tool_name}",
                        }
                    except Exception as exc:  # noqa: BLE001
                        # A single tool failure must not abort the whole agent
                        # loop; surface it as an error result so the model can
                        # react and the conversation can continue.
                        self.logger.warning(
                            "Tool %s raised %s: %s",
                            tool_name,
                            type(exc).__name__,
                            exc,
                        )
                        tool_result = {
                            "status": "error",
                            "error": f"tool {tool_name} failed: {exc}",
                        }

                    if callable(self.tool_call_hook):
                        try:
                            tool_ok = not (
                                isinstance(tool_result, dict)
                                and str(tool_result.get("status") or "").lower()
                                == "error"
                            )
                            self.tool_call_hook(
                                "tool.end",
                                {
                                    "tool_name": tool_name,
                                    "tool_call_id": tool_call.get("id", ""),
                                    "ok": tool_ok,
                                    "duration_ms": round(
                                        (time.monotonic() - tool_started_s) * 1000, 3
                                    ),
                                    "result_summary": self._tool_result_summary(
                                        tool_result
                                    ),
                                },
                            )
                        except Exception:
                            pass

                    # 将工具结果添加到消息历史
                    tool_call_id = tool_call.get("id", "") or ""
                    # Preferred Responses API continuation: provide tool output
                    # as a `function_call_output` input and link it via
                    # `previous_response_id`.
                    if response_id and tool_call_id:
                        self._previous_response_id = response_id
                        messages.append(
                            {
                                "type": "function_call_output",
                                "call_id": tool_call_id,
                                "output": str(tool_result),
                            }
                        )
                    else:
                        # Fallback for Chat Completions style loops.
                        messages.append(
                            {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": tool_call_id,
                                        "type": "function",
                                        "function": {
                                            "name": tool_name,
                                            "arguments": (
                                                tool_call.get("arguments")
                                                if isinstance(
                                                    tool_call.get("arguments"), str
                                                )
                                                else __import__("json").dumps(
                                                    tool_call.get("arguments") or {}
                                                )
                                            ),
                                        },
                                    }
                                ],
                            }
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "content": str(tool_result),
                            }
                        )

            except LLMClientError as e:
                self.logger.error(f"LLM error on turn {turn_count}: {e}")
                raise
            except Exception as e:
                self.logger.error(f"Unexpected error on turn {turn_count}: {e}")
                raise LLMClientError(
                    f"Execution failed on turn {turn_count}",
                    details={"turn": turn_count, "error": str(e)},
                ) from e

        # 达到最大轮次
        self.logger.warning(f"Reached max tool turns: {max_turns}")
        return "我停止了工具调用，因为连续执行太多轮仍没有产出答案。请换个更具体的问题再试。"

    @staticmethod
    def _tool_result_summary(result: Any) -> Dict[str, Any]:
        """Summarize tool results without leaking returned memory content."""

        summary: Dict[str, Any] = {"type": type(result).__name__}
        if not isinstance(result, dict):
            if isinstance(result, list):
                summary["item_count"] = len(result)
            return summary

        summary["status"] = result.get("status")
        summary["keys"] = sorted(str(k) for k in result.keys())
        if "error" in result or "message" in result:
            summary["has_error"] = bool(result.get("error") or result.get("message"))

        data = result.get("data")
        if isinstance(data, list):
            summary["item_count"] = len(data)
            summary["hit_count"] = len(data)
            return summary
        if isinstance(data, dict):
            summary["data_keys"] = sorted(str(k) for k in data.keys())
            hits = data.get("hits")
            if isinstance(hits, list):
                summary["hit_count"] = len(hits)
            else:
                summary["item_count"] = len(data)
            return summary
        if data is None:
            summary["item_count"] = 0
        else:
            summary["data_type"] = type(data).__name__
        return summary

    @staticmethod
    def _tool_call_signature(tool_name: str, tool_args: Any) -> str:
        try:
            normalized_args = json.dumps(
                tool_args or {}, sort_keys=True, ensure_ascii=True, default=str
            )
        except Exception:
            normalized_args = str(tool_args)
        return f"{tool_name}:{normalized_args}"

    def _extract_tool_calls(self, response: Any) -> List[Dict[str, Any]]:
        """
        从LLM响应中提取工具调用

        Args:
            response: LLM响应

        Returns:
            工具调用列表
        """
        try:
            from agent_memory_framework.llm import normalize_tool_calls

            return normalize_tool_calls(response)
        except LLMClientError as exc:
            self.logger.warning("Invalid tool call payload from LLM: %s", exc)
            return []

    def _extract_text_response(self, response: Any) -> str:
        """
        从LLM响应中提取文本

        Args:
            response: LLM响应

        Returns:
            响应文本
        """
        # Azure OpenAI responses API格式
        if hasattr(response, "output"):
            for output in response.output:
                if hasattr(output, "type") and output.type == "message":
                    # 提取消息内容
                    content = []
                    for block in output.content:
                        if hasattr(block, "text"):
                            content.append(block.text)
                    return "\n".join(content)

        # OpenAI chat completions格式
        elif isinstance(response, dict):
            return (
                response.get("choices", [{}])[0].get("message", {}).get("content", "")
            )

        choices = getattr(response, "choices", None)
        if choices:
            try:
                message = getattr(choices[0], "message", None)
                content = getattr(message, "content", None)
                if content:
                    return str(content)
            except Exception:
                pass

        # 降级：尝试转为字符串
        return str(response)
