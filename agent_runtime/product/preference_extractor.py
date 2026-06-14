from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, List


@dataclass(frozen=True)
class PreferenceCandidate:
    key: str
    value: Any
    source: str  # rule|llm
    confidence: float


_WS_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", s.strip())


def extract_preferences_rule_based(text: str) -> List[PreferenceCandidate]:
    """Deterministic preference extraction.

    Keep this narrow/high-precision; LLM validation will still run before write.
    """

    t = _norm(text)
    candidates: List[PreferenceCandidate] = []

    # English: "my favorite language is Python"
    m = re.search(
        r"\bmy\s+favorite\s+language\s+is\s+(?P<val>[^.\n]+)",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        candidates.append(
            PreferenceCandidate(
                key="favorite_language",
                value=_norm(m.group("val")),
                source="rule",
                confidence=0.85,
            )
        )

    # Chinese: "我最喜欢的语言是 Python"
    m = re.search(r"我\s*最\s*喜\s*欢\s*的\s*语\s*言\s*是\s*(?P<val>[^。\n]+)", t)
    if m:
        candidates.append(
            PreferenceCandidate(
                key="favorite_language",
                value=_norm(m.group("val")),
                source="rule",
                confidence=0.85,
            )
        )

    # "Call me <name>" / "You can call me <name>"
    m = re.search(
        r"\b(?:call\s+me|you\s+can\s+call\s+me)\s+(?P<val>[A-Za-z0-9_\- ]{2,40})\b",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        candidates.append(
            PreferenceCandidate(
                key="preferred_name",
                value=_norm(m.group("val")),
                source="rule",
                confidence=0.8,
            )
        )

    return candidates


def extract_preferences_llm(
    *,
    llm_call_fn,
    text: str,
    allowed_keys: Iterable[str],
) -> List[PreferenceCandidate]:
    """LLM extraction producing candidates.

    Must be validated again before persist.
    """

    allow = sorted(set(allowed_keys))
    prompt = (
        "Extract user preferences from the given message. "
        "Return ONLY valid JSON with this exact schema: "
        "{\"items\":[{\"key\":...,\"value\":...,\"confidence\":0.0-1.0}]} "
        f"Allowed keys: {allow}. If none, return {{\"items\":[]}}.\n\n"
        f"Message: {text}"
    )
    raw = llm_call_fn([{"role": "user", "content": prompt}])
    output_text = getattr(raw, "output_text", None) or str(raw)
    output_text = output_text.strip()

    # Best-effort JSON parse.
    data = None
    try:
        data = json.loads(output_text)
    except Exception:
        # Try to locate JSON object inside text.
        start = output_text.find("{")
        end = output_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            data = json.loads(output_text[start : end + 1])
        else:
            return []

    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []

    candidates: List[PreferenceCandidate] = []
    allow_set = set(allow)
    for it in items:
        if not isinstance(it, dict):
            continue
        k = it.get("key")
        if not isinstance(k, str) or k not in allow_set:
            continue
        conf = it.get("confidence")
        try:
            conf_f = float(conf)
        except Exception:
            conf_f = 0.0
        candidates.append(
            PreferenceCandidate(
                key=k,
                value=it.get("value"),
                source="llm",
                confidence=max(0.0, min(1.0, conf_f)),
            )
        )
    return candidates


def validate_preference_llm(
    *,
    llm_call_fn,
    key: str,
    value: Any,
    text: str,
    min_confidence: float = 0.7,
) -> bool:
    """Mandatory LLM gate before writing LTM.

    Returns True only if the model confirms the preference is explicitly stated.
    """

    prompt = (
        "Decide whether the message explicitly states the given user preference. "
        "Return ONLY valid JSON: {\"accept\": true/false, \"confidence\": 0.0-1.0}.\n\n"
        f"Preference key: {key}\n"
        f"Preference value: {value}\n\n"
        f"Message: {text}"
    )
    raw = llm_call_fn([{"role": "user", "content": prompt}])
    output_text = getattr(raw, "output_text", None) or str(raw)
    output_text = output_text.strip()
    try:
        data = json.loads(output_text)
    except Exception:
        start = output_text.find("{")
        end = output_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(output_text[start : end + 1])
            except Exception:
                return False
        else:
            return False

    if not isinstance(data, dict):
        return False
    accept = data.get("accept")
    if accept is not True:
        return False
    conf = data.get("confidence")
    try:
        conf_f = float(conf)
    except Exception:
        return False
    return conf_f >= float(min_confidence)


def two_stage_preferences(
    *,
    user_text: str,
    llm_call_fn,
    allowed_keys: Iterable[str],
    extract_llm_when_no_rule: bool = True,
    min_validation_confidence: float = 0.7,
) -> List[PreferenceCandidate]:
    """Default pipeline:

    1) Rule-based extract.
    2) If no rule hit and enabled: LLM extract.
    3) For any candidate: mandatory LLM validation gate.
    """

    candidates = extract_preferences_rule_based(user_text)
    if not candidates and extract_llm_when_no_rule:
        candidates = extract_preferences_llm(
            llm_call_fn=llm_call_fn, text=user_text, allowed_keys=allowed_keys
        )

    accepted: List[PreferenceCandidate] = []
    for c in candidates:
        if validate_preference_llm(
            llm_call_fn=llm_call_fn,
            key=c.key,
            value=c.value,
            text=user_text,
            min_confidence=min_validation_confidence,
        ):
            accepted.append(c)
    return accepted

