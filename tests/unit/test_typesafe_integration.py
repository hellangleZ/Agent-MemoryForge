# -*- coding: utf-8 -*-
"""Unit tests for the TypeSafe (Jev) integration. HTTP is mocked."""
import pytest

from agent_memory_lib.typesafe_client import TypeSafeClient
from agent_memory_framework.memory_runtime.context_planner import ContextPlan
from agent_memory_framework.memory_runtime.context_planner_typesafe import (
    TypeSafeContextPlanner,
)


def _client(answers):
    c = TypeSafeClient(api_key="test-key")
    c.decide = lambda *, state, questions: answers  # type: ignore
    return c


def _defaults():
    return ContextPlan(
        include_wm=True, preference_keys=[], stm_last_k=15, semantic_top_k=5,
        include_preferences=True,
    )


def test_client_disabled_without_key():
    assert TypeSafeClient(api_key="").available() is False
    assert TypeSafeClient(api_key="k").available() is True


def test_planner_uses_typesafe_answers():
    answers = {
        "include_wm": {"choice": "exclude", "confidence": 0.95},
        "include_preferences": {"choice": "include", "confidence": 0.95},
        "include_stm": {"choice": "include", "confidence": 0.95},
        "include_semantic": {"choice": "exclude", "confidence": 0.95},
        "stm_last_k": {"score": 1.0, "confidence": 0.9,
                       "probabilities": {"0": 0.0, "1": 1.0, "2": 0.0, "3": 0.0}},
        "semantic_top_k": {"score": 0.0, "confidence": 0.9,
                           "probabilities": {"0": 1.0, "1": 0.0, "2": 0.0, "3": 0.0}},
    }
    planner = TypeSafeContextPlanner(client=_client(answers))
    plan = planner.plan(user_query="q", defaults=_defaults())
    assert plan is not None
    assert plan.include_wm is False
    assert plan.include_preferences is True
    assert plan.stm_last_k == 2        # score bucket 1 -> 2
    assert plan.semantic_top_k == 0    # include_semantic exclude -> 0


def test_planner_returns_none_when_all_low_confidence(monkeypatch):
    monkeypatch.setenv("CONTEXT_PLANNER_TYPESAFE_MIN_CONFIDENCE", "0.9")
    answers = {
        "include_wm": {"choice": "include", "confidence": 0.2},
        "include_preferences": {"choice": "include", "confidence": 0.2},
        "include_stm": {"choice": "include", "confidence": 0.2},
        "include_semantic": {"choice": "include", "confidence": 0.2},
    }
    planner = TypeSafeContextPlanner(client=_client(answers))
    assert planner.plan(user_query="q", defaults=_defaults()) is None


def test_planner_falls_back_when_client_raises():
    class _Boom:
        def available(self):
            return True
        def decide(self, *, state, questions):
            raise RuntimeError("boom")
    planner = TypeSafeContextPlanner(client=_Boom())
    assert planner.plan(user_query="q", defaults=_defaults()) is None


def test_safety_guard_uses_typesafe_verdict(monkeypatch):
    from agent_memory_framework.memory_runtime import memory_safety_typesafe as mst

    monkeypatch.setenv("MEMORY_SAFETY_TYPESAFE_ENABLED", "1")

    class _C:
        def available(self):
            return True
        def decide(self, *, state, questions):
            return {
                "is_persistent": {"noul": 0.95},
                "is_uncertain": {"noul": 0.01},
                "is_grounded": {"noul": 0.9},
            }
    verdict = mst.evaluate_persistence(
        candidate_text="user likes tables",
        user_messages=["please use tables"],
        require_user_grounding=True,
        client=_C(),
    )
    assert verdict is True


def test_safety_guard_rejects_uncertain(monkeypatch):
    from agent_memory_framework.memory_runtime import memory_safety_typesafe as mst

    monkeypatch.setenv("MEMORY_SAFETY_TYPESAFE_ENABLED", "1")

    class _C:
        def available(self):
            return True
        def decide(self, *, state, questions):
            return {
                "is_persistent": {"noul": 0.9},
                "is_uncertain": {"noul": 0.95},
            }
    verdict = mst.evaluate_persistence(
        candidate_text="probably likes coffee",
        user_messages=["probably likes coffee"],
        require_user_grounding=False,
        client=_C(),
    )
    assert verdict is False


def test_safety_guard_disabled_returns_none(monkeypatch):
    from agent_memory_framework.memory_runtime import memory_safety_typesafe as mst
    monkeypatch.delenv("MEMORY_SAFETY_TYPESAFE_ENABLED", raising=False)

    class _C:
        def available(self):
            return True
        def decide(self, *, state, questions):
            raise AssertionError("should not be called when disabled")
    assert mst.evaluate_persistence(candidate_text="x", client=_C()) is None
