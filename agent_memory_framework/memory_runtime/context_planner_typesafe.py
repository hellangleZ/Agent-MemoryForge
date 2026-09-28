"""Jev (TypeSafe) powered context planner.

The context planner decides which memory tiers to retrieve and how much. That is
a structured decision, not text generation, so it is a natural fit for a System
One model. We evaluate, in a single call:

- include/exclude each tier           (Choice: include|exclude)
- how much STM / semantic to retrieve (Score: bucketed amount)

The choice answers carry a confidence. When confidence is below a threshold the
caller falls back to the LLM-based planner, then to static defaults. All of this
is best-effort: if the TypeSafe key is missing or the call fails, nothing is used.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from agent_memory_lib.typesafe_client import TypeSafeClient
from utils.logging_config import get_logger

from agent_memory_framework.memory_runtime.context_planner import ContextPlan


logger = get_logger(__name__)


_CONFIDENCE_ENV = "CONTEXT_PLANNER_TYPESAFE_MIN_CONFIDENCE"


def _min_confidence() -> float:
    try:
        return float(os.getenv(_CONFIDENCE_ENV) or "0.6")
    except Exception:
        return 0.6


# Amount buckets for STM last_k and semantic top_k. The planner only ever picks
# from a small, bounded set; the LLM planner could emit arbitrary ints, which was
# part of why parsing was fragile.
_STM_BUCKETS = [0, 2, 5, 15]
_SEMANTIC_BUCKETS = [0, 2, 5, 10]


def _nearest_bucket(value: int, buckets: List[int]) -> int:
    return min(buckets, key=lambda b: abs(b - int(value)))


def _amount_criteria(buckets: List[int], what: str) -> List[str]:
    return [
        f"Do not include any {what}",
        f"A little {what} ({buckets[1]})",
        f"A moderate amount of {what} ({buckets[2]})",
        f"A generous amount of {what} ({buckets[3]})",
    ][: len(buckets)]


def _build_questions(defaults: ContextPlan) -> Dict[str, Any]:
    questions: Dict[str, Any] = {}
    tier_desc = {
        "wm": "short-lived working state for the current task",
        "preferences": "durable user preferences and settings",
        "stm": "recent conversation checkpoint summaries",
        "semantic": "durable facts and knowledge",
    }
    for tier, desc in tier_desc.items():
        questions[f"include_{tier}"] = TypeSafeClient.choice(
            instructions=f"Should the agent retrieve {desc} to answer this user query?",
            criteria={
                "include": f"The query likely needs {desc}",
                "exclude": f"The query clearly does not need {desc}",
            },
        )
    questions["stm_last_k"] = TypeSafeClient.score(
        instructions="How much recent conversation context (STM summaries) does this query need?",
        criteria=_amount_criteria(_STM_BUCKETS, "recent conversation context"),
    )
    questions["semantic_top_k"] = TypeSafeClient.score(
        instructions="How many durable semantic facts does this query need?",
        criteria=_amount_criteria(_SEMANTIC_BUCKETS, "semantic facts"),
    )
    return questions


def _score_to_bucket(answer: Dict[str, Any], buckets: List[int]) -> Optional[int]:
    if not isinstance(answer, dict):
        return None
    probs = answer.get("probabilities")
    if isinstance(probs, dict) and probs:
        # Pick the level with the highest probability, then map to the bucket.
        try:
            best_level = max(probs.items(), key=lambda kv: float(kv[1]))[0]
            idx = int(best_level)
            if 0 <= idx < len(buckets):
                return buckets[idx]
        except Exception:
            return None
    score = answer.get("score")
    try:
        idx = int(round(float(score)))
    except Exception:
        return None
    return buckets[idx] if 0 <= idx < len(buckets) else None


class TypeSafeContextPlanner:
    """Plan memory retrieval with a System One model.

    Returns a ContextPlan on success, or None when unavailable / low confidence so
    the caller can fall back to the LLM planner and then to defaults.
    """

    def __init__(self, *, client: Optional[TypeSafeClient] = None) -> None:
        self.client = client or TypeSafeClient()

    def plan(self, *, user_query: str, defaults: ContextPlan) -> Optional[ContextPlan]:
        if not self.client.available():
            return None

        questions = _build_questions(defaults)
        try:
            answers = self.client.decide(state=user_query, questions=questions)
        except Exception as exc:
            logger.debug("typesafe context planner call failed: %s", exc)
            return None

        min_conf = _min_confidence()

        def _include(tier: str, default: bool) -> Optional[bool]:
            ans = answers.get(f"include_{tier}") or {}
            conf = ans.get("confidence")
            choice = ans.get("choice")
            if choice not in ("include", "exclude"):
                return None
            if conf is None or float(conf) < min_conf:
                return None
            return choice == "include"

        include_wm = _include("wm", defaults.include_wm)
        include_preferences = _include("preferences", defaults.include_preferences)
        include_stm = _include("stm", defaults.stm_last_k > 0)
        include_semantic = _include("semantic", defaults.semantic_top_k > 0)

        # Amount questions: score -> nearest bucket, gated by the include decision
        # and by confidence.
        stm_last_k = defaults.stm_last_k
        if include_stm is False:
            stm_last_k = 0
        elif include_stm is True:
            ans = answers.get("stm_last_k") or {}
            if ans.get("confidence") is not None and float(ans["confidence"]) >= min_conf:
                bucket = _score_to_bucket(ans, _STM_BUCKETS)
                if bucket is not None:
                    stm_last_k = bucket

        semantic_top_k = defaults.semantic_top_k
        if include_semantic is False:
            semantic_top_k = 0
        elif include_semantic is True:
            ans = answers.get("semantic_top_k") or {}
            if ans.get("confidence") is not None and float(ans["confidence"]) >= min_conf:
                bucket = _score_to_bucket(ans, _SEMANTIC_BUCKETS)
                if bucket is not None:
                    semantic_top_k = bucket

        # If every tier decision was low confidence, treat the whole plan as
        # unusable so the caller falls back to the LLM planner.
        if include_wm is None and include_preferences is None and include_stm is None and include_semantic is None:
            return None

        return ContextPlan(
            include_wm=defaults.include_wm if include_wm is None else include_wm,
            preference_keys=defaults.preference_keys,
            stm_last_k=int(stm_last_k),
            semantic_top_k=int(semantic_top_k),
            notes="typesafe",
            include_preferences=(
                defaults.include_preferences if include_preferences is None else include_preferences
            ),
        )
