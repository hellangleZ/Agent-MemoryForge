"""Reusable agent shell (SDK).

A batteries-included agent base for quickly building demos and product agents.
Subclasses provide a system prompt and a small set of domain tools; everything
else (memory/context integration, LLM call plumbing, tool execution loop) is
shared. Lives in the framework SDK so the product layer depends on the SDK.
"""

from __future__ import annotations

import os
import re

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from agent_memory_lib import MemoryClient

from agent_memory_framework.agent import Agent
from agent_memory_framework.execution_loop import ExecutionLoop
from agent_memory_framework.llm import CallableLLMProvider
from agent_memory_framework.tools import ToolRegistry
from agent_memory_lib.text_processing import TextProcessor, estimate_tokens
from agent_memory_framework.memory_runtime.context_builder import ContextBuilder
from agent_memory_framework.memory_runtime.memory_manager import MemoryManager
from agent_memory_framework.memory_runtime.memory_safety import (
    contains_synthetic_marker,
    filter_preferences,
)
from agent_memory_framework.tool_intent import should_expose_tool
from utils.logging_config import get_logger

from agent_memory_framework.trace import TraceCollector, trace_span


logger = get_logger(__name__)


_CORE_MEMORY_TOOL_NAMES = {
    "retrieve_stm_summaries",
    "retrieve_ltm_preferences",
    "search_semantic_memories",
    "search_graph_memories",
}
_WORKING_MEMORY_TOOL_NAME = "manage_working_memory"
_MEMORY_LOOKUP_HINTS = (
    "remember",
    "remembered",
    "memory",
    "memories",
    "preference",
    "preferences",
    "stored",
    "saved",
    "previous",
    "earlier",
    "history",
    "what did we",
    "what do you remember",
    "记忆",
    "记得",
    "记住",
    "偏好",
    "之前",
    "以前",
    "历史",
    "上次",
    "刚才",
    "长期记忆",
    "短期记忆",
    "知识图谱",
    "图谱",
    "关系",
    "沉淀",
)
_WORKING_MEMORY_HINTS = (
    "working memory",
    "step mode",
    "long-running task",
    "long task",
    "multi-step task",
    "工作记忆",
    "长期任务",
    "多步骤任务",
    "按步骤执行",
    "继续任务",
    "取消任务",
    "完成任务",
)
_MEMORY_KEY_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"[A-Za-z][A-Za-z0-9]*_(?:pref|memory|mem|ltm|stm|wm)_[A-Za-z0-9_]+"
    r"(?![A-Za-z0-9_])"
)
@dataclass(frozen=True)
class DemoRuntime:
    agent_id: str
    user_id: str
    memory_client: MemoryClient
    llm_call_fn: Callable[[List[Dict[str, Any]]], Any]
    conversation_id: str
    config: Dict[str, Any]
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    trace: Optional[TraceCollector] = None

    @property
    def llm_provider(self):
        return CallableLLMProvider(self.llm_call_fn)

    def trace_root(self, name: str = "runtime", **attributes: Any):
        base = {
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
        }
        base.update(attributes)
        return trace_span(self.trace, name, **base)


class DemoAgent(Agent):
    """Reusable agent shell.

        Subclasses implement:
    - `get_system_prompt()`
    - `register_domain_tools(registry)`

    Inherits the SDK :class:`Agent` so the whole codebase shares a single agent
    root (common ``enable_mcp`` / history helpers / abstract contract). This
    shell keeps its own memory-aware ``__init__``/``run_turn`` because it drives
    the raw ``llm_call_fn`` directly (supporting Responses-API tool chaining via
    ``previous_response_id``) instead of the provider abstraction.
    """

    def __init__(self, runtime: DemoRuntime):
        self.runtime = runtime

        self.logger = get_logger(f"demo_agent.{runtime.agent_id}")
        self.tool_registry = ToolRegistry()

        self.memory_manager = MemoryManager(
            memory_client=runtime.memory_client,
            user_id=runtime.user_id,
            conversation_id=runtime.conversation_id,
            config=runtime.config,
        )
        self.text_processor = TextProcessor()
        self.context_builder = ContextBuilder(
            memory_manager=self.memory_manager,
            text_processor=self.text_processor,
            config=runtime.config,
        )

        self.execution_loop = ExecutionLoop(
            agent_id=runtime.agent_id,
            llm_call_fn=runtime.llm_call_fn,
            tool_registry=self.tool_registry,
            config=runtime.config,
        )

        self._register_core_tools()
        self.register_domain_tools(self.tool_registry)

        self.conversation_history: List[Dict[str, Any]] = []

    # ---- subclass API ----
    def get_system_prompt(self) -> str:
        raise NotImplementedError

    def register_domain_tools(self, registry: ToolRegistry) -> None:
        raise NotImplementedError

    # ---- SDK Agent contract (delegate to the demo-style hooks) ----
    def system_prompt(self) -> str:
        return self.get_system_prompt()

    def register_tools(self, registry: ToolRegistry) -> None:
        self.register_domain_tools(registry)

    def tools_for_turn(self, user_query: str) -> List[Dict[str, Any]]:
        """Return the tools that should be visible to the LLM for this turn."""
        expose_working_memory = self._should_expose_working_memory_tool(user_query)
        expose_memory_lookup = expose_working_memory or self._is_explicit_memory_lookup(
            user_query
        )

        visible: List[Dict[str, Any]] = []
        for tool in self.tool_registry.list_tools(None):
            name = str(tool.get("name") or "")
            if name == _WORKING_MEMORY_TOOL_NAME and not expose_working_memory:
                continue
            if name in _CORE_MEMORY_TOOL_NAMES and not expose_memory_lookup:
                continue
            if not should_expose_tool(tool, user_query):
                continue
            visible.append(tool)
        return visible

    def _is_explicit_memory_lookup(self, user_query: str) -> bool:
        text = str(user_query or "").strip()
        if not text:
            return False
        lowered = text.lower()
        if any(hint in lowered for hint in _MEMORY_LOOKUP_HINTS):
            return True
        return _MEMORY_KEY_PATTERN.search(lowered) is not None

    def _should_expose_working_memory_tool(self, user_query: str) -> bool:
        if self._has_active_step_mode_working_memory():
            return True
        lowered = str(user_query or "").strip().lower()
        return any(hint in lowered for hint in _WORKING_MEMORY_HINTS)

    def _has_active_step_mode_working_memory(self) -> bool:
        try:
            state = self.memory_manager.retrieve_current_wm()
        except Exception:
            return False
        if not isinstance(state, dict):
            return False
        if str(state.get("mode") or "").strip().lower() != "step_mode":
            return False
        if str(state.get("status") or "").strip().lower() != "active":
            return False
        steps = state.get("steps")
        if not isinstance(steps, list):
            return False
        for step in steps:
            if not isinstance(step, dict):
                continue
            status = str(step.get("status") or "todo").strip().lower()
            text = str(step.get("text") or "").strip()
            if text and status != "done":
                return True
        return False

    # ---- shared behavior ----
    def _register_core_tools(self) -> None:
        # Keep minimal: memory operations are shared across demos.
        self.tool_registry.register(
            name="retrieve_stm_summaries",
            func=self._tool_retrieve_stm_summaries,
            category="memory",
            schema={
                "description": (
                    "Retrieve recent STM summaries only when the user explicitly "
                    "asks about previous conversation memory or history."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"last_k": {"type": "integer", "default": 15}},
                },
            },
        )

        self.tool_registry.register(
            name="retrieve_ltm_preferences",
            func=self._tool_retrieve_ltm_preferences,
            category="memory",
            schema={
                "description": (
                    "Read user long-term preferences only when the user explicitly "
                    "asks about a preference, setting, remembered key, or personal "
                    "memory. Do not call for greetings or general chat."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Optional exact preference key."},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
            },
        )

        self.tool_registry.register(
            name="search_semantic_memories",
            func=self._tool_search_semantic_memories,
            category="memory",
            schema={
                "description": (
                    "Search durable semantic facts only when the user explicitly asks "
                    "about remembered facts, decisions, requirements, or project "
                    "knowledge. Do not call for greetings or general chat."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            },
        )

        self.tool_registry.register(
            name="search_graph_memories",
            func=self._tool_search_graph_memories,
            category="memory",
            schema={
                "description": (
                    "Search knowledge graph relations only when the user explicitly "
                    "asks about remembered entity relationships or graph facts. Do not "
                    "call for greetings or general chat."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            },
        )

        if os.getenv("AGENT_EXPOSE_PREFERENCE_TOOL", "").strip().lower() in {"1", "true", "yes", "on"}:
            self.tool_registry.register(
                name="store_ltm_preference",
                func=self._tool_store_ltm_preference,
                category="memory",
                schema={
                    "description": "Store a user preference",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "value": {},
                        },
                        "required": ["key", "value"],
                    },
                },
            )

        # Working memory (WM): a single long-running task state bound to the conversation_id.
        self.tool_registry.register(
            name="manage_working_memory",
            func=self._tool_manage_working_memory,
            category="memory",
            schema={
                "description": (
                    "Manage conversation-scoped working memory only for an active "
                    "confirmed step-mode task. Do not call for greetings, normal chat, "
                    "or memory lookup."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["get", "start", "cancel", "complete", "update_step"],
                        },
                        "goal": {"type": "string"},
                        "steps": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "text": {"type": "string"},
                                },
                                "required": ["text"],
                            },
                        },
                        "notes": {"type": "string"},
                        "reason": {"type": "string"},
                        "summary": {"type": "string"},
                        "step_id": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["todo", "doing", "done"],
                        },
                    },
                    "required": ["action"],
                },
            },
        )

    def run_turn(self, user_query: str) -> str:
        direct_memory_answer = self._answer_explicit_preference_lookup(user_query)
        if direct_memory_answer:
            self.logger.info(
                "Answered explicit preference lookup without LLM",
                extra={"trace_id": self.runtime.trace_id},
            )
            self.conversation_history.append({"role": "user", "content": user_query})
            self.conversation_history.append(
                {"role": "assistant", "content": direct_memory_answer}
            )
            return direct_memory_answer

        # Step-mode WM: if an active step plan exists, bias the agent to execute the
        # next step and persist progress via `manage_working_memory`.
        wm_state = None
        next_step = None
        try:
            wm_state = self.memory_manager.retrieve_current_wm()
            if isinstance(wm_state, dict) and str(wm_state.get("mode") or "").strip() == "step_mode":
                next_step = self.memory_manager.next_wm_step()
        except Exception:
            wm_state = None
            next_step = None

        # Build enhanced context with STM summaries.
        messages = self.context_builder.build_enhanced_context(
            user_query=user_query,
            conversation_history=self.conversation_history
            + [{"role": "user", "content": user_query}],
            system_prompt=self.get_system_prompt(),
        )

        if next_step and isinstance(next_step, dict):
            goal = ""
            if isinstance(wm_state, dict):
                goal = str(wm_state.get("goal") or "").strip()
            sid = str(next_step.get("id") or "").strip() or "?"
            step_text = str(next_step.get("text") or "").strip()
            steer = [
                "You are executing a long-running task step-by-step.",
                f"Goal: {goal}" if goal else "Goal: (unspecified)",
                f"Next step ({sid}): {step_text}",
                "",
                "Rules:",
                "- Do the next step now.",
                "- When the step is completed, you MUST call:",
                f'  manage_working_memory(action=\"update_step\", step_id=\"{sid}\", status=\"done\")',
                "- After that update_step call succeeds, stop calling tools and answer the user.",
                "- If you are blocked, explain why and call update_step with status=doing once.",
                "- Do not re-plan the whole task unless the user explicitly asks.",
            ]
            messages = [{"role": "system", "content": "\n".join(steer)}] + list(messages)

        # If the gateway attached a workspace default system prompt override,
        # surface it as a system message to the model.
        override = (self.runtime.config or {}).get("system_prompt")
        if isinstance(override, str) and override.strip():
            messages = [{"role": "system", "content": override.strip()}] + list(
                messages
            )

        token_count = estimate_tokens(str(messages))
        self.logger.info(
            "Context messages=%s tokens~%s",
            len(messages),
            token_count,
            extra={"trace_id": self.runtime.trace_id},
        )

        response_text = self.execution_loop.run_single_turn(messages)

        # Update local history (thin). STM sync stays in MemoryManager for reuse.
        self.conversation_history.append({"role": "user", "content": user_query})
        self.conversation_history.append(
            {"role": "assistant", "content": response_text}
        )
        return response_text

    def _answer_explicit_preference_lookup(self, user_query: str) -> str | None:
        query = str(user_query or "").strip()
        if not query:
            return None
        if contains_synthetic_marker(query):
            return (
                "这个看起来是内部测试记忆标识，不属于可展示的真实用户偏好；"
                "我不会把它当作有效记忆。"
            )
        lowered = query.lower()
        write_intent_terms = (
            "delete", "remove", "forget", "store", "save", "set", "change", "update",
            "删除", "忘记", "保存", "记住", "设置", "修改", "改成", "更新",
        )
        if any(term in lowered for term in write_intent_terms):
            return None

        try:
            prefs = self.memory_manager.list_ltm_preferences(limit=200)
        except Exception:
            return None
        if not isinstance(prefs, dict) or not prefs:
            return None
        prefs = filter_preferences(prefs)
        if not prefs:
            return None

        matches = []
        for key, value in prefs.items():
            key_text = str(key or "").strip()
            if key_text and self._query_mentions_preference_key(lowered, key_text):
                matches.append((key_text, value))
        if not matches:
            return None
        if len(matches) == 1:
            key, value = matches[0]
            return f"{key}: {value}"
        lines = ["从长期偏好记忆中读取到："]
        lines.extend(f"- {key}: {value}" for key, value in matches[:20])
        return "\n".join(lines)

    @staticmethod
    def _query_mentions_preference_key(lowered_query: str, key_text: str) -> bool:
        key = key_text.lower()
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])"
        return re.search(pattern, lowered_query) is not None

    # ---- core tools ----
    def _tool_retrieve_stm_summaries(self, last_k: int = 15) -> Dict[str, Any]:
        data = self.memory_manager.retrieve_stm_summaries(last_k=last_k)
        return {"status": "success", "data": data}

    def _tool_retrieve_ltm_preferences(self, key: str | None = None, limit: int = 50) -> Dict[str, Any]:
        key_text = str(key or "").strip()
        if key_text:
            value = self.memory_manager.retrieve_ltm_preference(key_text)
            return {"status": "success", "data": {key_text: value} if value is not None else {}}
        try:
            limit_int = max(1, int(limit or 50))
        except Exception:
            limit_int = 50
        return {"status": "success", "data": self.memory_manager.list_ltm_preferences(limit=limit_int)}

    def _tool_search_semantic_memories(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        try:
            k = max(1, int(top_k or 5))
        except Exception:
            k = 5
        data = self.memory_manager.retrieve_semantic_memories(query=str(query or ""), top_k=k)
        return {"status": "success", "data": data}

    def _tool_search_graph_memories(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        try:
            k = max(1, int(top_k or 5))
        except Exception:
            k = 5
        result = self.runtime.memory_client.memory_search(query=str(query or ""), top_k=k, tiers=["graph"])
        if result.get("status") != "success":
            return {"status": "error", "data": [], "message": result.get("message") or "graph search failed"}
        data = result.get("data", {})
        hits = data.get("hits", []) if isinstance(data, dict) else []
        return {"status": "success", "data": hits}

    def _tool_store_ltm_preference(self, key: str, value: Any) -> Dict[str, Any]:
        return self.runtime.memory_client.store_ltm_preference(
            user_id=self.runtime.user_id,
            key=key,
            value=value,
        )

    def _tool_manage_working_memory(
        self,
        action: str,
        goal: str | None = None,
        steps: List[Dict[str, Any]] | None = None,
        notes: str | None = None,
        reason: str | None = None,
        summary: str | None = None,
        step_id: str | None = None,
        status: str | None = None,
    ) -> Dict[str, Any]:
        action = str(action or "").strip().lower()
        if action == "get":
            state = self.memory_manager.retrieve_current_wm()
            return {"status": "success", "data": state}
        if action == "start":
            return self.memory_manager.start_long_task(goal=str(goal or ""), steps=steps, notes=notes)
        if action == "cancel":
            return self.memory_manager.cancel_long_task(reason=reason)
        if action == "complete":
            return self.memory_manager.complete_long_task(summary=summary)
        if action == "update_step":
            return self.memory_manager.update_wm_step(step_id=str(step_id or ""), status=str(status or ""))
        return {"status": "error", "message": f"unsupported action: {action}"}
