from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Dict, List, Optional, Tuple

from agent_memory_lib.text_processing import TextProcessor
from utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ContextBudget:
    max_tokens: int
    reserved_response_tokens: int = 0

    @property
    def available_tokens(self) -> int:
        return max(0, self.max_tokens - self.reserved_response_tokens)


@dataclass(frozen=True)
class ContextPolicy:
    """Controls how context is compacted under budget."""

    # If True, always keep the very last user message even under budget pressure.
    keep_last_user_message: bool = True


@dataclass(frozen=True)
class ContextItem:
    role: str
    content: str
    source: str
    tokens: int
    included: bool
    reason: str


@dataclass(frozen=True)
class ContextTrace:
    context_hash: str
    included: List[Dict[str, Any]]
    excluded: List[Dict[str, Any]]
    total_tokens: int
    budget: ContextBudget


@dataclass
class ContextAssembler:
    memory_manager: Any
    text_processor: TextProcessor
    config: Dict[str, Any]

    def build(
        self,
        *,
        user_query: str,
        conversation_history: List[Dict[str, Any]],
        system_prompt: str,
    ) -> List[Dict[str, Any]]:
        # Prefer an explicitly configured builder (env or config spec). This lets
        # callers plug in a richer, memory-aware builder (e.g. the memory_runtime
        # ContextBuilder) without the framework taking a hard dependency on it.
        builder = self._configured_builder()
        if builder is not None:
            return builder.build_enhanced_context(
                user_query=user_query,
                conversation_history=conversation_history,
                system_prompt=system_prompt,
            )

        # Default: system prompt + history only.
        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(conversation_history)
        return messages

    def _configured_builder(self):
        spec = os.getenv("AGENT_MEMORY_CONTEXT_BUILDER", "").strip()
        if not spec and isinstance(self.config, dict):
            spec = str(self.config.get("context_builder") or "").strip()
        if not spec or ":" not in spec:
            return None

        module_name, _, class_name = spec.partition(":")
        module_name = module_name.strip()
        class_name = class_name.strip()
        if not module_name or not class_name:
            return None
        try:
            mod = importlib.import_module(module_name)
            cls = getattr(mod, class_name)
            return cls(
                memory_manager=self.memory_manager,
                text_processor=self.text_processor,
                config=self.config,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load context builder %r: %s", spec, exc)
            return None

    @classmethod
    def minimal(cls) -> "ContextAssembler":
        """Create a ContextAssembler suitable for tests without MemoryManager dependencies."""

        return cls(memory_manager=None, text_processor=TextProcessor(), config={})  # type: ignore[arg-type]

    def build_with_trace(
        self,
        *,
        user_query: str,
        conversation_history: List[Dict[str, Any]],
        system_prompt: str,
        budget: ContextBudget,
        policy: Optional[ContextPolicy] = None,
    ) -> Tuple[List[Dict[str, Any]], ContextTrace]:
        base = self.build(
            user_query=user_query,
            conversation_history=conversation_history,
            system_prompt=system_prompt,
        )
        compacted, trace = _dedup_and_compact_under_budget(
            base, budget=budget, policy=policy or ContextPolicy()
        )
        return compacted, trace

    def build_with_mcp_resources(
        self,
        *,
        user_query: str,
        conversation_history: List[Dict[str, Any]],
        system_prompt: str,
        mcp_resources: List[Dict[str, Any]],
        max_resources: int = 20,
    ) -> List[Dict[str, Any]]:
        """Build context and include a concise MCP resource index.

        The resource content itself is not inlined; agents should use MCP read tools.
        """

        from agent_memory_framework.mcp import (
            normalize_mcp_resources,
            format_mcp_resources_for_context,
        )

        try:
            messages = self.build(
                user_query=user_query,
                conversation_history=conversation_history,
                system_prompt=system_prompt,
            )
        except Exception:
            # In minimal/test mode, build() may be unavailable due to missing MemoryManager.
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.extend(conversation_history)

        resources = normalize_mcp_resources(mcp_resources)
        listing = format_mcp_resources_for_context(resources, max_items=max_resources)
        if listing:
            messages.insert(
                1 if messages and messages[0].get("role") == "system" else 0,
                {"role": "system", "content": listing},
            )
        return messages


def _message_tokens(text_processor: TextProcessor, message: Dict[str, Any]) -> int:
    from agent_memory_lib.text_processing import estimate_tokens

    content = (message.get("content") or "").strip()
    if not content:
        return 0
    return estimate_tokens(content)


def _dedup_key(message: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    role = message.get("role")
    content = message.get("content")
    if not role or not content:
        return None
    return (str(role), str(content))


def _context_hash(messages: List[Dict[str, Any]]) -> str:
    payload = "\n".join(f"{m.get('role')}:{m.get('content')}" for m in messages)
    return sha256(payload.encode("utf-8")).hexdigest()


def _estimate_messages_tokens(
    text_processor: TextProcessor, messages: List[Dict[str, Any]]
) -> int:
    return sum(_message_tokens(text_processor, m) for m in messages)


def _dedup_and_compact_under_budget(
    messages: List[Dict[str, Any]],
    *,
    budget: ContextBudget,
    text_processor: Optional[TextProcessor] = None,
    policy: Optional[ContextPolicy] = None,
) -> Tuple[List[Dict[str, Any]], ContextTrace]:
    """Deduplicate exact role/content pairs and drop older messages until under budget.

    Strategy:
    - Keep first occurrences; exclude exact duplicates (role+content).
    - Enforce token budget by preferentially dropping oldest non-system messages.
    """

    text_processor = text_processor or TextProcessor()
    policy = policy or ContextPolicy()

    included_messages: List[Dict[str, Any]] = []
    included_entries: List[Dict[str, Any]] = []
    msg_indexes: List[int] = []
    excluded_entries: List[Dict[str, Any]] = []

    seen = set()
    for idx, msg in enumerate(messages):
        key = _dedup_key(msg)
        if key is not None and key in seen:
            excluded_entries.append(
                {
                    "index": idx,
                    "role": msg.get("role"),
                    "source": "conversation",
                    "reason": "dedup",
                }
            )
            continue
        if key is not None:
            seen.add(key)

        tokens = _message_tokens(text_processor, msg)
        included_messages.append(msg)
        msg_indexes.append(idx)
        included_entries.append(
            {
                "index": idx,
                "role": msg.get("role"),
                "source": "conversation",
                "reason": "included",
                "tokens": tokens,
            }
        )

    available = budget.available_tokens
    tokens_total = _estimate_messages_tokens(text_processor, included_messages)

    if tokens_total > available:
        # Drop older messages first, always keep system prompt if present.
        # Optionally keep the last user message.
        last_user_idx = None
        if policy.keep_last_user_message:
            for i in range(len(included_messages) - 1, -1, -1):
                if included_messages[i].get("role") == "user":
                    last_user_idx = i
                    break

        drop_order = [
            i
            for i, m in enumerate(included_messages)
            if m.get("role") != "system" and i != last_user_idx
        ]
        for drop_idx in drop_order:
            if tokens_total <= available:
                break
            msg = included_messages[drop_idx]
            drop_tokens = _message_tokens(text_processor, msg)
            included_messages[drop_idx] = None  # type: ignore[assignment]
            tokens_total = max(0, tokens_total - drop_tokens)

            for entry in included_entries:
                if entry.get("index") == msg_indexes[drop_idx]:
                    excluded_entries.append(
                        {
                            "index": entry.get("index"),
                            "role": entry.get("role"),
                            "source": entry.get("source"),
                            "reason": "budget",
                            "tokens": drop_tokens,
                        }
                    )
                    entry["reason"] = "budget"
                    break

        included_messages = [m for m in included_messages if m is not None]

    trace = ContextTrace(
        context_hash=_context_hash(included_messages),
        included=[e for e in included_entries if e.get("reason") == "included"],
        excluded=excluded_entries,
        total_tokens=tokens_total,
        budget=budget,
    )
    return included_messages, trace


__all__ = [
    "ContextAssembler",
    "ContextBudget",
    "ContextPolicy",
    "ContextItem",
    "ContextTrace",
]
