from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agent_memory_framework.memory_runtime.openai_like_llm import OpenAILikeLLMConfig, call_openai_like_llm
from utils.logging_config import get_logger

from agent_memory_framework.memory_runtime.context_planner_settings import ContextPlannerSettings


logger = get_logger(__name__)


PLANNER_SYSTEM_PROMPT = """You are a context planning module for a long-running agent.

Goal: decide what memories to retrieve and how to assemble a compact context.

Return STRICT JSON only (no markdown, no code fences) with schema:
{
  "include": {
    "wm": true,
    "preferences": {"enabled": true, "keys": ["..."]},
    "stm": {"enabled": true, "last_k": 15},
    "semantic": {"enabled": true, "top_k": 5}
  },
  "notes": "short rationale"
}

Rules:
- Prefer fewer items; avoid token bloat.
- Use the provided defaults unless there is a clear need to change.
"""


@dataclass(frozen=True)
class ContextPlan:
    include_wm: bool
    preference_keys: List[str]
    stm_last_k: int
    semantic_top_k: int
    notes: str = ""
    include_preferences: bool = True


def _safe_int(value: Any, default: int) -> int:
    try:
        n = int(value)
        return n if n > 0 else default
    except Exception:
        return default


def _parse_plan(raw_text: str, defaults: ContextPlan) -> ContextPlan:
    try:
        data = json.loads(raw_text.strip())
    except Exception:
        return defaults

    include = data.get("include") if isinstance(data, dict) else None
    if not isinstance(include, dict):
        return defaults

    wm = bool(include.get("wm", defaults.include_wm))

    pref = include.get("preferences")
    include_preferences = defaults.include_preferences
    preference_keys = defaults.preference_keys
    if isinstance(pref, dict) and pref.get("enabled", True) is not False:
        keys = pref.get("keys")
        if include_preferences and isinstance(keys, list):
            preference_keys = [str(k).strip() for k in keys if str(k).strip()]
    elif isinstance(pref, dict) and pref.get("enabled") is False:
        include_preferences = False
        preference_keys = []

    stm = include.get("stm")
    stm_last_k = defaults.stm_last_k
    if (
        defaults.stm_last_k > 0
        and isinstance(stm, dict)
        and stm.get("enabled", True) is not False
    ):
        stm_last_k = _safe_int(stm.get("last_k"), defaults.stm_last_k)
    elif isinstance(stm, dict) and stm.get("enabled") is False:
        stm_last_k = 0

    semantic = include.get("semantic")
    semantic_top_k = defaults.semantic_top_k
    if (
        defaults.semantic_top_k > 0
        and isinstance(semantic, dict)
        and semantic.get("enabled", True) is not False
    ):
        semantic_top_k = _safe_int(semantic.get("top_k"), defaults.semantic_top_k)
    elif isinstance(semantic, dict) and semantic.get("enabled") is False:
        semantic_top_k = 0

    notes = str(data.get("notes") or "") if isinstance(data, dict) else ""

    return ContextPlan(
        include_wm=wm,
        preference_keys=preference_keys,
        stm_last_k=stm_last_k,
        semantic_top_k=semantic_top_k,
        notes=notes,
        include_preferences=include_preferences,
    )


class LLMContextPlanner:
    def __init__(self, *, settings: Optional[ContextPlannerSettings] = None):
        self.settings = settings or ContextPlannerSettings.from_env()

    def plan(
        self,
        *,
        user_query: str,
        defaults: ContextPlan,
    ) -> ContextPlan:
        if not self.settings.enabled:
            return defaults

        cfg = OpenAILikeLLMConfig(
            provider=self.settings.provider,
            model=self.settings.model,
            temperature=self.settings.temperature,
            max_output_tokens=self.settings.max_output_tokens,
            max_attempts=self.settings.max_attempts,
            retry_base_sleep_s=self.settings.retry_base_sleep_s,
            openai_api_key=self.settings.openai_api_key,
            openai_base_url=self.settings.openai_base_url,
            api_style=self.settings.api_style,
            azure_api_key=self.settings.azure_api_key,
            azure_endpoint=self.settings.azure_endpoint,
            azure_deployment=self.settings.azure_deployment,
            azure_api_version=self.settings.azure_api_version,
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_query": user_query,
                        "defaults": {
                            "wm": defaults.include_wm,
                            "include_preferences": defaults.include_preferences,
                            "preference_keys": defaults.preference_keys,
                            "stm_last_k": defaults.stm_last_k,
                            "semantic_top_k": defaults.semantic_top_k,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        try:
            raw = call_openai_like_llm(cfg=cfg, messages=messages)
        except Exception as exc:
            logger.warning("context planner failed; using defaults: %s", exc)
            return defaults

        planned = _parse_plan(raw, defaults)
        logger.debug("context planner notes=%s", planned.notes)
        return planned
