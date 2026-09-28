"""Jev (TypeSafe) semantic checks for memory persistence.

The regex-based memory_safety checks are fast but brittle: they only understand a
fixed set of English/Chinese cue words and a token-overlap grounding heuristic.
A System One model can answer the same guardrail questions semantically, in any
language, without parsing free text.

This module is strictly opt-in: when TYPESAFE_API_KEY is unset, or the call
fails, or the answer is ambiguous, callers fall back to the existing regex path.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Optional

from agent_memory_lib.typesafe_client import TypeSafeClient
from utils.logging_config import get_logger


logger = get_logger(__name__)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except Exception:
        return default


def _enabled() -> bool:
    return (os.getenv("MEMORY_SAFETY_TYPESAFE_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# noul thresholds: persist requires a clear yes; uncertainty rejects on a clear yes.
_PERSIST_YES = lambda: _env_float("MEMORY_SAFETY_TYPESAFE_PERSIST_MIN", 0.8)
_UNCERTAIN_YES = lambda: _env_float("MEMORY_SAFETY_TYPESAFE_UNCERTAIN_MIN", 0.7)
_GROUNDED_YES = lambda: _env_float("MEMORY_SAFETY_TYPESAFE_GROUNDED_MIN", 0.6)


def _user_evidence_block(user_messages: Iterable[str]) -> str:
    lines = [str(m or "").strip() for m in user_messages if str(m or "").strip()]
    return "\n".join(lines[:20])


def evaluate_persistence(
    *,
    candidate_text: str,
    user_messages: Iterable[str] = (),
    require_user_grounding: bool = True,
    client: Optional[TypeSafeClient] = None,
) -> Optional[bool]:
    """Return True/False when Jev gives a confident verdict, else None.

    None means "no confident semantic answer" -> caller should use the regex path.
    """
    if not _enabled():
        return None
    client = client or TypeSafeClient()
    if not client.available():
        return None

    state = f"Candidate memory:\n{candidate_text}\n\nUser messages (evidence):\n{_user_evidence_block(user_messages)}"
    questions: Dict[str, Any] = {
        "is_persistent": TypeSafeClient.noul(
            instructions=(
                "Is this candidate a durable, factual memory worth persisting for an AI agent "
                "(a real user preference, fact, decision, or event) rather than small talk, a "
                "transient filler, or an internal test/synthetic marker?"
            )
        ),
        "is_uncertain": TypeSafeClient.noul(
            instructions=(
                "Does this candidate memory express uncertainty, guessing, or speculation "
                "(words like maybe, probably, I guess, seems) rather than a stated fact?"
            )
        ),
    }
    if require_user_grounding:
        questions["is_grounded"] = TypeSafeClient.noul(
            instructions=(
                "Is the candidate memory directly supported by the user messages shown as "
                "evidence (its specific entities, values, and claims appear in or follow from "
                "what the user actually said), rather than invented?"
            )
        )

    try:
        answers = client.decide(state=state, questions=questions)
    except Exception as exc:
        logger.debug("typesafe memory-safety call failed: %s", exc)
        return None

    persistent = (answers.get("is_persistent") or {}).get("noul")
    uncertain = (answers.get("is_uncertain") or {}).get("noul")
    if persistent is None or uncertain is None:
        return None
    persistent = float(persistent)
    uncertain = float(uncertain)

    # Uncertainty is a hard reject when Jev is confident it is present.
    if uncertain >= _UNCERTAIN_YES():
        return False
    # Persistence must be a clear yes; a clear no also rejects.
    if persistent <= 1.0 - _PERSIST_YES():
        return False
    if persistent < _PERSIST_YES():
        return None

    if require_user_grounding:
        grounded = (answers.get("is_grounded") or {}).get("noul")
        if grounded is None:
            return None
        if float(grounded) < _GROUNDED_YES():
            return False

    return True
