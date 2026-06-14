from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from utils.logging_config import get_logger


logger = get_logger(__name__)


DISTILL_SYSTEM_PROMPT = """You distill a conversation checkpoint into structured memories for a long-running AI agent.

Return STRICT JSON only (no markdown, no code fences). The output schema:
{
  "stm_summary": {
    "user_request": "...",
    "final_answer": "...",
    "memories_used": ["..."],
    "timestamp": 1710000000,
    "conversation_length": 0
  },
  "semantic_facts": [
    {"text": "...", "importance": 0.0, "tags": ["..."]}
  ],
  "preferences": [
    {"key": "...", "value": "...", "confidence": 0.0}
  ],
  "kg_relations": [
    {"subject": "...", "relation": "...", "obj": "...", "confidence": 0.0}
  ]
}

Rules:
- Extract only durable information.
- Treat LLM output as candidate memory only; deterministic service code will reject unsafe or ungrounded candidates.
- Semantic facts MUST be one of:
  - hard constraints (budgets, deadlines, non-negotiables)
  - decisions (chosen approach/stack, accepted tradeoffs)
  - interfaces/contracts (APIs, schemas, invariants)
  - processes/SOPs (how we do X, checklist-worthy workflows)
  - enterprise/project knowledge that should remain true across sessions
- Do NOT put ephemeral chat/events/progress logs into semantic facts (meeting recap, "we talked about", transient status).
- Do NOT extract facts from assistant guesses, suggestions, or assumptions unless the user explicitly confirmed them.
- Do NOT extract test/synthetic markers, internal memory keys, benchmark data, or fake seed content.
- Candidate semantic facts and relations should be grounded in the user's own messages, not only in prior memory context or the assistant answer.
- Prefer fewer, higher-quality items.
- If nothing to extract for a section, output an empty list.
- STM is a rolling checkpoint summary. You may be given `prior_stm_summaries` plus a non-overlapping `chunk_messages`.
- Write `stm_summary.final_answer` as a concise checkpoint summary (target 150-300 tokens).
- Do not repeat raw chat; capture stable facts, decisions, constraints, and active threads.
"""

STM_CHECKPOINT_TEXT_PROMPT = """You write a rolling STM checkpoint summary for a long-running AI agent.

You will be given:
- `prior_stm_summaries`: up to 2 previous checkpoint summaries
- `chunk_messages`: a non-overlapping chunk (e.g. the last 10 rounds)

Task:
- Produce a single updated checkpoint summary that incorporates the prior summaries plus the new chunk.
- Target length: 150-300 tokens.
- Do not repeat raw chat. Capture stable facts, decisions, constraints, open threads, and notable tool outcomes.

Return plain text only.
"""


@dataclass(frozen=True)
class DistillResult:
    stm_summary: Dict[str, Any]
    semantic_facts: List[Dict[str, Any]]
    preferences: List[Dict[str, Any]]
    kg_relations: List[Dict[str, Any]]


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    return text.strip()


def parse_distill_output(raw_text: str) -> DistillResult:
    """Parse distillation LLM output. Robust to minor formatting mistakes."""
    cleaned = _strip_code_fences(raw_text)

    # If the model accidentally included surrounding text, try to extract JSON object.
    if not cleaned.startswith("{"):
        m = re.search(r"\{.*\}", cleaned, flags=re.S)
        if m:
            cleaned = m.group(0)

    try:
        data = json.loads(cleaned)
    except Exception as exc:
        logger.warning("distill output parse failed: %s", exc)
        # Fallback: keep the raw text as an STM summary so distillation still yields
        # a durable "what happened" artifact even when providers don't reliably
        # follow strict JSON instructions.
        data = {"stm_summary": {"final_answer": _strip_code_fences(raw_text)}}

    stm_summary = data.get("stm_summary") or {}
    semantic_facts = data.get("semantic_facts") or []
    preferences = data.get("preferences") or []
    kg_relations = data.get("kg_relations") or []

    if not isinstance(stm_summary, dict):
        stm_summary = {}
    if not isinstance(semantic_facts, list):
        semantic_facts = []
    if not isinstance(preferences, list):
        preferences = []
    if not isinstance(kg_relations, list):
        kg_relations = []

    return DistillResult(
        stm_summary=stm_summary,
        semantic_facts=[x for x in semantic_facts if isinstance(x, dict)],
        preferences=[x for x in preferences if isinstance(x, dict)],
        kg_relations=[x for x in kg_relations if isinstance(x, dict)],
    )


def build_distill_messages(
    *,
    user_id: str,
    conversation_id: str,
    round_id: int,
    last_user: str,
    assistant_answer: str,
    history: Optional[List[Dict[str, Any]]] = None,
    prior_stm_summaries: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    history = history or []
    prior_stm_summaries = prior_stm_summaries or []

    content = {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "round_id": round_id,
        "last_user": last_user,
        "assistant_answer": assistant_answer,
        # `history` is expected to be a non-overlapping chunk (e.g., last 10 rounds).
        "chunk_messages": history,
        # Provide prior STM so the model can produce an updated checkpoint summary.
        "prior_stm_summaries": prior_stm_summaries,
    }

    return [
        {"role": "system", "content": DISTILL_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(content, ensure_ascii=False),
        },
    ]


def build_stm_checkpoint_messages(
    *,
    user_id: str,
    conversation_id: str,
    round_id: int,
    last_user: str,
    assistant_answer: str,
    chunk_messages: List[Dict[str, Any]],
    prior_stm_summaries: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    prior_stm_summaries = prior_stm_summaries or []
    content = {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "round_id": round_id,
        "last_user": last_user,
        "assistant_answer": assistant_answer,
        "chunk_messages": chunk_messages,
        "prior_stm_summaries": prior_stm_summaries,
    }
    return [
        {"role": "system", "content": STM_CHECKPOINT_TEXT_PROMPT},
        {"role": "user", "content": json.dumps(content, ensure_ascii=False)},
    ]
