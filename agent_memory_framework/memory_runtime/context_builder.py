"""
Context构建模块
智能构建对话上下文，包含相关性过滤和token优化
"""

import os
import re
from typing import Dict, Any, List, Optional
from utils.logging_config import get_logger
from agent_memory_lib.text_processing import TextProcessor
from .memory_manager import MemoryManager

from agent_memory_framework.memory_runtime.policies import MemoryPolicy
from agent_memory_framework.memory_runtime.context_planner import ContextPlan, LLMContextPlanner
from agent_memory_framework.memory_runtime.memory_safety import (
    filter_memory_entries,
    filter_preferences,
    is_safe_memory_payload,
)

logger = get_logger(__name__)

MEMORY_CONTEXT_RULES = """## Memory Use Rules
- Treat Working Memory, User Preferences, Relevant Conversation History, Relevant Semantic Facts, and Knowledge Graph as separate memory sources.
- If a memory section contains the answer, use it naturally without exposing internal memory keys, paths, scores, source labels, or test markers.
- Do not say no memory exists just because STM is empty; check preferences, semantic facts, graph, and working memory context too.
- Treat memory as supporting evidence, not as absolute truth. If memory conflicts with the user's current message, prefer the current user message.
"""


def _clean_memory_text(text: Any) -> str:
    value = str(text or "")
    value = re.sub(r"<!--\s*am:entry\b.*?-->", "", value, flags=re.DOTALL)
    if "-->" in value:
        value = value.rsplit("-->", 1)[-1]
    if "-[" not in value:
        value = value.replace("[", "").replace("]", "")
    value = re.sub(r"\s+", " ", value).strip()
    if re.search(
        r'"(?:created_at|memory_kind|source|tenant_id|workspace_id|tags)"\s*:',
        value,
    ):
        return ""
    return value.strip(" …")


class ContextBuilder:
    """
    Context构建器
    负责智能构建对话上下文
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        text_processor: Optional[TextProcessor] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化Context构建器

        Args:
            memory_manager: 记忆管理器
            text_processor: 可选的文本处理器
            config: 可选的配置
        """
        self.memory_manager = memory_manager
        self.text_processor = text_processor or TextProcessor()
        self.config = config or {}

        policy = MemoryPolicy.from_config(self.config)

        # 配置参数
        self.stm_max_summaries = policy.stm_max_summaries
        self.stm_relevance_threshold = policy.stm_relevance_threshold
        self.stm_top_k = policy.stm_top_k

        self.semantic_top_k = policy.semantic_top_k

        self.logger = logger

    def build_enhanced_context(
        self,
        user_query: str,
        conversation_history: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        构建增强的对话上下文

        Args:
            user_query: 用户查询
            conversation_history: 当前对话历史
            system_prompt: 可选的系统提示词

        Returns:
            增强的上下文消息列表
        """
        enhanced_context = []

        # 1. 添加系统提示
        if system_prompt:
            enhanced_context.append({"role": "system", "content": system_prompt})
        enhanced_context.append({"role": "system", "content": MEMORY_CONTEXT_RULES})

        policy = MemoryPolicy.from_config(self.config)
        default_pref_keys = self.config.get("preference_keys", []) if isinstance(self.config, dict) else []
        if isinstance(default_pref_keys, str):
            default_pref_keys = [k.strip() for k in default_pref_keys.split(",") if k.strip()]
        if not isinstance(default_pref_keys, list):
            default_pref_keys = []

        defaults = ContextPlan(
            include_wm=True,
            include_preferences=bool(self.config.get("include_preferences", True)),
            preference_keys=[str(k) for k in default_pref_keys],
            stm_last_k=int(getattr(policy, "stm_max_summaries", 15)),
            semantic_top_k=int(getattr(policy, "semantic_top_k", 5)),
        )

        plan = LLMContextPlanner().plan(user_query=user_query, defaults=defaults)

        if plan.include_wm:
            self._append_working_memory_context(enhanced_context)

        if plan.include_preferences:
            if plan.preference_keys:
                self._append_preferences_context(enhanced_context, plan.preference_keys)
            else:
                self._append_all_preferences_context(enhanced_context)

        # STM: planner decides last_k; keep filtering heuristic as fallback only.
        if plan.stm_last_k > 0:
            # Product decision: keep STM injection small and stable (rolling checkpoint summaries).
            try:
                max_stm = int(os.getenv("AGENT_STM_CONTEXT_LAST_K", "2") or "2")
            except Exception:
                max_stm = 2
            max_stm = max(0, max_stm)
            stm_last_k = min(int(plan.stm_last_k), max_stm) if max_stm else 0
            stm_context = self._get_stm_context(user_query=user_query, last_k=stm_last_k)
            if stm_context:
                enhanced_context.append({"role": "system", "content": stm_context})

        if plan.semantic_top_k > 0:
            semantic_facts = self._get_relevant_semantic_facts(user_query, top_k=plan.semantic_top_k)
            if semantic_facts:
                semantic_context = self._format_semantic_context(semantic_facts)
                enhanced_context.append({"role": "system", "content": semantic_context})
        try:
            graph_top_k = int(os.getenv("AGENT_GRAPH_CONTEXT_TOP_K", "8") or "8")
        except Exception:
            graph_top_k = 8
        if graph_top_k > 0:
            graph_facts = self._get_relevant_graph_facts(user_query, top_k=graph_top_k)
            if graph_facts:
                graph_context = self._format_graph_context(graph_facts)
                enhanced_context.append({"role": "system", "content": graph_context})

        # 4. 添加当前对话历史
        enhanced_context.extend(conversation_history)

        # 5. 估算token数量
        from agent_memory_lib.text_processing import estimate_tokens

        token_count = estimate_tokens(str(enhanced_context))

        self.logger.info(
            f"Built enhanced context: {len(enhanced_context)} messages, "
            f"~{token_count} tokens"
        )

        return enhanced_context

    def _get_stm_context(self, *, user_query: str, last_k: int) -> str:
        if last_k <= 0:
            return ""
        try:
            read_k = max(int(last_k or 0) * 3, int(last_k or 0) + 5)
            summaries = self.memory_manager.retrieve_stm_summaries(last_k=read_k)
        except Exception:
            summaries = []
        summaries = filter_memory_entries(summaries)
        if last_k > 0:
            summaries = summaries[-last_k:]
        if not summaries:
            return ""

        # If planner is enabled, we avoid additional heuristics to reduce token waste.
        try:
            if LLMContextPlanner().settings.enabled:
                return self._format_stm_context(summaries)
        except Exception:
            # Planner is optional; keep behavior best-effort, but make failures observable.
            self.logger.debug("LLMContextPlanner probe failed; falling back to heuristics", exc_info=True)

        # Best-effort relevance filter as a fallback for when planner is disabled.
        try:
            keywords = self.text_processor.extract_keywords(user_query, top_k=10)
        except Exception:
            keywords = []
        filtered = self._get_relevant_stm_summaries(keywords)
        return self._format_stm_context(filtered if filtered else summaries)

    def _get_relevant_stm_summaries(self, keywords: List[str]) -> List[Dict[str, Any]]:
        """
        获取相关的STM摘要

        Args:
            keywords: 关键词列表

        Returns:
            相关的STM摘要列表
        """
        # 获取所有STM摘要
        all_summaries = self.memory_manager.retrieve_stm_summaries(
            last_k=self.stm_max_summaries
        )

        if not all_summaries:
            return []

        # 计算相关性并过滤
        relevant_summaries = []

        for summary in all_summaries:
            summary_text = summary.get("summary", "")

            # 计算相关性得分
            relevance_score = self.text_processor.calculate_relevance(
                summary_text, keywords
            )

            # 只保留相关性超过阈值的摘要
            if relevance_score >= self.stm_relevance_threshold:
                summary["relevance_score"] = relevance_score
                relevant_summaries.append(summary)

        # 按相关性排序并取top-k
        relevant_summaries.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

        return relevant_summaries[: self.stm_top_k]

    def _format_stm_context(self, summaries: List[Dict[str, Any]]) -> str:
        """
        格式化STM摘要为上下文文本

        Args:
            summaries: STM摘要列表

        Returns:
            格式化的上下文字符串
        """
        if not summaries:
            return ""

        context_parts = ["## Relevant Conversation History"]

        for summary in summaries:
            round_id = summary.get("round_id", "?")
            summary_text = (
                summary.get("final_answer")
                or summary.get("summary")
                or summary.get("conversation_summary")
                or ""
            )
            relevance = summary.get("relevance_score", 0.0)

            context_parts.append(
                f"**Round {round_id}** [Relevance: {relevance:.2f}]\n{summary_text}"
            )

        return "\n\n".join(context_parts)

    def _get_relevant_semantic_facts(self, user_query: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve semantic facts relevant to the current query."""
        requested_k = int(self.semantic_top_k if top_k is None else top_k)
        if requested_k <= 0:
            return []
        search_k = max(requested_k * 3, requested_k + 10)
        facts: List[Dict[str, Any]] = []
        try:
            for query in self._semantic_search_queries(user_query):
                batch = self.memory_manager.retrieve_semantic_memories(
                    query=query, top_k=search_k
                )
                if batch:
                    facts.extend(batch)
                if len(facts) >= search_k:
                    break
        except Exception:
            facts = []
        if not facts:
            return []

        normalized: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in facts:
            if not isinstance(item, dict):
                continue
            text_val = item.get("text") or item.get("content") or item.get("snippet")
            if not text_val and isinstance(item.get("metadata"), dict):
                text_val = item["metadata"].get("text")
            if not text_val:
                continue
            dedupe_key = str(
                item.get("entry_id")
                or item.get("id")
                or f"{item.get('path')}:{item.get('line')}:{text_val}"
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            clean_text = _clean_memory_text(text_val)
            if not clean_text:
                continue
            normalized.append(
                {
                    "text": clean_text,
                    "score": item.get("score"),
                    "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                }
            )
        return filter_memory_entries(normalized)[: int(top_k or self.semantic_top_k)]

    def _semantic_search_queries(self, user_query: str) -> List[str]:
        """Build narrow fallback queries for file-first FTS.

        Full natural-language questions can be too restrictive for the FTS
        backend. Keep the original query first, then try high-signal identifiers.
        """
        original = str(user_query or "").strip()
        queries: List[str] = []
        seen: set[str] = set()

        def add(query: str) -> None:
            q = str(query or "").strip()
            if not q or q in seen:
                return
            seen.add(q)
            queries.append(q)

        add(original)
        generic = {
            "what",
            "which",
            "where",
            "when",
            "answer",
            "memory",
            "score",
            "path",
            "key",
            "source",
            "metadata",
            "不要",
            "什么",
            "这个",
            "那个",
        }
        raw_tokens: List[str] = []
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", original):
            if token.lower() in generic:
                continue
            if token not in raw_tokens:
                raw_tokens.append(token)
        tokens = sorted(
            raw_tokens,
            key=lambda token: (
                0 if ("_" in token or "." in token) else 1,
                raw_tokens.index(token),
            ),
        )

        for token in tokens:
            add(token)
            if len(queries) >= 6:
                return queries
        for i in range(len(tokens) - 1):
            add(f"{tokens[i]} {tokens[i + 1]}")
            if len(queries) >= 8:
                return queries
        return queries

    def _format_semantic_context(self, facts: List[Dict[str, Any]]) -> str:
        if not facts:
            return ""
        parts = ["## Relevant Semantic Facts"]
        for i, fact in enumerate(facts, start=1):
            parts.append(f"{i}. {fact.get('text','').strip()}")
        return "\n".join(parts)

    def _get_relevant_graph_facts(self, user_query: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve graph relations relevant to the current query."""
        requested_k = int(self.semantic_top_k if top_k is None else top_k)
        if requested_k <= 0:
            return []
        search_k = max(requested_k * 2, requested_k + 5)
        hits: List[Dict[str, Any]] = []
        try:
            memory_client = getattr(self.memory_manager, "memory_client", None)
            if memory_client is None or not hasattr(memory_client, "memory_search"):
                return []
            for query in self._semantic_search_queries(user_query):
                result = memory_client.memory_search(
                    query=query,
                    top_k=search_k,
                    tiers=["graph"],
                    scopes=["project"],
                )
                if not isinstance(result, dict) or result.get("status") != "success":
                    continue
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                batch = data.get("hits") if isinstance(data, dict) else []
                if batch:
                    hits.extend([item for item in batch if isinstance(item, dict)])
                if len(hits) >= search_k:
                    break
        except Exception:
            hits = []
        if not hits:
            return []

        normalized: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in hits:
            text_val = None
            if isinstance(item.get("metadata"), dict):
                meta = item["metadata"]
                subject = str(meta.get("subject") or "").strip()
                relation = str(meta.get("relation") or "").strip()
                obj = str(meta.get("obj") or "").strip()
                if subject and relation and obj:
                    text_val = f"{subject} -[{relation}]-> {obj}"
            if not text_val:
                text_val = item.get("text") or item.get("content") or item.get("snippet")
            if not text_val:
                continue
            dedupe_key = str(
                item.get("entry_id")
                or item.get("id")
                or f"{item.get('path')}:{item.get('line')}:{text_val}"
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            clean_text = _clean_memory_text(text_val)
            if not clean_text:
                continue
            normalized.append(
                {
                    "text": clean_text,
                    "score": item.get("score"),
                    "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                }
            )
        return filter_memory_entries(normalized)[:requested_k]

    def _format_graph_context(self, facts: List[Dict[str, Any]]) -> str:
        if not facts:
            return ""
        parts = ["## Knowledge Graph"]
        for i, fact in enumerate(facts, start=1):
            parts.append(f"{i}. {fact.get('text','').strip()}")
        return "\n".join(parts)

    def _append_working_memory_context(self, enhanced: List[Dict[str, Any]]) -> None:
        try:
            state = self.memory_manager.retrieve_wm_state(task_id=self.memory_manager.conversation_id)
        except Exception:
            state = None
        if not state:
            return
        if not is_safe_memory_payload(state):
            return
        if isinstance(state, dict):
            status = str(state.get("status") or "").strip().lower()
            # Only inject active WM; done/cancelled are preserved for audit but not
            # useful for day-to-day context unless explicitly requested.
            if status and status != "active":
                return

            goal = str(state.get("goal") or "").strip()
            steps = state.get("steps") if isinstance(state.get("steps"), list) else []

            lines: List[str] = ["## Working Memory"]
            if goal:
                lines.append(f"Goal: {goal}")
            if steps:
                lines.append("")
                lines.append("Steps:")
                for s in steps:
                    if not isinstance(s, dict):
                        continue
                    sid = str(s.get("id") or "").strip()
                    text = str(s.get("text") or "").strip()
                    st = str(s.get("status") or "todo").strip().lower()
                    checkbox = "[x]" if st == "done" else "[~]" if st == "doing" else "[ ]"
                    prefix = f"{sid}. " if sid else ""
                    if text:
                        lines.append(f"- {checkbox} {prefix}{text}")
            note = str(state.get("notes") or "").strip()
            if note:
                lines.append("")
                lines.append(f"Notes: {note}")

            enhanced.append({"role": "system", "content": "\n".join(lines).strip()})
            return

        enhanced.append({"role": "system", "content": "## Working Memory\n" + str(state)})

    def _append_preferences_context(self, enhanced: List[Dict[str, Any]], keys: List[str]) -> None:
        try:
            cap = int(os.getenv("AGENT_PREF_CONTEXT_MAX", "50") or "50")
        except Exception:
            cap = 50
        if cap <= 0:
            return
        normalized_keys = list(
            dict.fromkeys(str(key).strip() for key in keys if str(key).strip())
        )[:cap]
        prefs: Dict[str, Any] = {}
        for key in normalized_keys:
            try:
                value = self.memory_manager.retrieve_ltm_preference(key)
            except Exception:
                value = None
            if value is not None:
                prefs[key] = value
        prefs = filter_preferences(prefs)
        if not prefs:
            return
        try:
            max_value_length = int(os.getenv("AGENT_PREF_VALUE_MAXLEN", "200") or "200")
        except Exception:
            max_value_length = 200
        lines = ["## User Preferences"]
        for key, value in prefs.items():
            rendered_value = str(value)
            if len(rendered_value) > max_value_length:
                rendered_value = rendered_value[:max_value_length] + "…"
            lines.append(f"- {key}: {rendered_value}")
        enhanced.append({"role": "system", "content": "\n".join(lines)})

    def _append_all_preferences_context(self, enhanced: List[Dict[str, Any]]) -> None:
        """注入该用户的全部偏好（去重后的最新值，带数量与长度上限）。"""
        try:
            cap = int(os.getenv("AGENT_PREF_CONTEXT_MAX", "50") or "50")
        except Exception:
            cap = 50
        if cap <= 0:
            return
        try:
            prefs = self.memory_manager.list_ltm_preferences(limit=max(cap * 2, cap + 20))
        except Exception:
            prefs = {}
        if not prefs:
            return
        prefs = filter_preferences(prefs)
        if not prefs:
            return
        prefs = {k: prefs[k] for k in sorted(prefs)[:cap]}
        try:
            max_val = int(os.getenv("AGENT_PREF_VALUE_MAXLEN", "200") or "200")
        except Exception:
            max_val = 200

        def _trim(v: Any) -> str:
            s = str(v)
            return s if len(s) <= max_val else s[:max_val] + "\u2026"

        lines = ["## User Preferences"] + [f"- {k}: {_trim(v)}" for k, v in prefs.items()]
        enhanced.append({"role": "system", "content": "\n".join(lines)})

    def build_simple_context(
        self,
        conversation_history: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        构建简单上下文（不使用STM）

        Args:
            conversation_history: 对话历史
            system_prompt: 可选的系统提示

        Returns:
            上下文消息列表
        """
        context = []

        if system_prompt:
            context.append({"role": "system", "content": system_prompt})

        context.extend(conversation_history)

        return context

    def estimate_context_tokens(self, context: List[Dict[str, Any]]) -> int:
        """
        估算上下文的token数量

        Args:
            context: 上下文消息列表

        Returns:
            估算的token数
        """
        from agent_memory_lib.text_processing import estimate_tokens

        total_text = ""
        for msg in context:
            content = msg.get("content", "")
            if content:
                total_text += content + "\n"

        return estimate_tokens(total_text)
