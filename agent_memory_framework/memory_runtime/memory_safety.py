from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


SYNTHETIC_MEMORY_RE = re.compile(
    r"(?i)("
    r"FAKE_MEMORY|"
    r"manual_(?:bulk_)?fake_seed|"
    r"fake\s+memory\s+test|"
    r"test\s+memory\s+marker|"
    r"synthetic\s+memory|"
    r"synthetic\s+seed|"
    r"测试记忆|"
    r"假记忆|"
    r"伪造记忆|"
    r"bulk_pref_\d+|"
    r"semantic_bulk_\d+|"
    r"stm_bulk_\d+|"
    r"graph_bulk_\d+|"
    r"memory_test_marker"
    r")"
)

UNCERTAIN_MEMORY_RE = re.compile(
    r"(?i)("
    r"\bi guess\b|"
    r"\bprobably\b|"
    r"\blikely\b|"
    r"\bseems\b|"
    r"\bappears\b|"
    r"\bmaybe\b|"
    r"我猜|猜测|推测|可能|看起来|似乎|大概|更像|应该是"
    r")"
)

MEMORY_WRITE_DIRECTIVE_RE = re.compile(
    r"(?i)("
    r"\bremember\b|"
    r"\bmemorize\b|"
    r"\bsave\b|"
    r"\bstore\b|"
    r"\brecord\b|"
    r"\bnote\b|"
    r"\bkeep this\b|"
    r"\badd (?:this )?to memory\b|"
    r"\bupdate memory\b|"
    r"记住|记一下|记录|保存|存一下|写入记忆|加入记忆|加到记忆|更新记忆"
    r")"
)

QUESTION_LIKE_RE = re.compile(
    r"(?i)("
    r"\bwhat\b|"
    r"\bwhich\b|"
    r"\bwho\b|"
    r"\bwhen\b|"
    r"\bwhere\b|"
    r"\bwhy\b|"
    r"\bhow\b|"
    r"\bcan you\b|"
    r"\bcould you\b|"
    r"\bdo you\b|"
    r"\bdoes\b|"
    r"\bis\b|"
    r"\bare\b|"
    r"什么|哪些|哪个|怎么|咋|为什么|是否|是不是|能否|可不可以|有没有|"
    r"如何|吗|么|呢|对吗|正常吗"
    r")"
)

UNSAFE_TAGS = {"fake", "synthetic", "memory_test"}
GENERIC_TOKENS = {
    "user",
    "users",
    "project",
    "system",
    "product",
    "current",
    "now",
    "task",
    "memory",
    "agent",
    "用户",
    "项目",
    "系统",
    "产品",
    "当前",
    "现在",
    "任务",
    "记忆",
    "回答",
    "相关",
    "这个",
    "那个",
    "正在",
    "需要",
    "可以",
}


def contains_synthetic_marker(value: Any) -> bool:
    """Return True when a memory payload contains internal test/synthetic markers."""
    if value is None:
        return False
    if isinstance(value, str):
        return SYNTHETIC_MEMORY_RE.search(value) is not None
    if isinstance(value, Mapping):
        source = str(value.get("source") or "").lower()
        marker = value.get("marker") or value.get("memory_test_marker")
        if "fake_seed" in source or contains_synthetic_marker(marker):
            return True
        tags = value.get("tags")
        if isinstance(tags, Iterable) and not isinstance(tags, (str, bytes)):
            for tag in tags:
                if str(tag).strip().lower() in UNSAFE_TAGS:
                    return True
        return any(contains_synthetic_marker(v) for v in value.values())
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        return any(contains_synthetic_marker(v) for v in value)
    return False


def is_safe_preference(key: Any, value: Any) -> bool:
    return not contains_synthetic_marker({"key": key, "value": value})


def filter_preferences(prefs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in prefs.items()
        if is_safe_preference(key, value)
    }


def is_safe_memory_payload(payload: Any) -> bool:
    return not contains_synthetic_marker(payload)


def filter_memory_entries(entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        if not is_safe_memory_payload(item):
            continue
        safe.append(dict(item))
    return safe


def _ascii_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_+.-]{2,}", text)
        if token.lower() not in GENERIC_TOKENS
    }


def _cjk_tokens(text: str) -> set[str]:
    out: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if len(run) <= 8 and run not in GENERIC_TOKENS:
            out.add(run)
        for size in (2, 3, 4):
            if len(run) < size:
                continue
            for i in range(0, len(run) - size + 1):
                token = run[i : i + size]
                if token not in GENERIC_TOKENS:
                    out.add(token)
    return out


def evidence_tokens(text: str) -> set[str]:
    text = str(text or "")
    return _ascii_tokens(text) | _cjk_tokens(text)


def _specific_ascii_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[#@]?[A-Za-z0-9][A-Za-z0-9_./:-]{2,}", str(text or "")):
        token = raw.strip(".,;:!?()[]{}<>`'\"").lower()
        if not token or token in GENERIC_TOKENS:
            continue
        if (
            any(ch in token for ch in ("_", ".", "/", ":", "#", "@", "-"))
            or any(ch.isdigit() for ch in token)
        ):
            tokens.add(token)
    return tokens


def _specific_token_is_grounded(token: str, user_text: str, user_specific: set[str]) -> bool:
    if token in user_specific:
        return True
    if token in user_text:
        return True
    pieces = [
        piece
        for piece in re.split(r"[#@_./:-]+", token)
        if len(piece) >= 3 and piece not in GENERIC_TOKENS
    ]
    return any(piece in user_text for piece in pieces)


def missing_specific_evidence_tokens(
    candidate_text: str, user_messages: Iterable[str]
) -> set[str]:
    """Specific IDs/times/handles in durable memories must be user supplied."""
    candidate_specific = _specific_ascii_tokens(candidate_text)
    if not candidate_specific:
        return set()
    user_text = "\n".join(str(m or "") for m in user_messages).lower()
    user_specific = _specific_ascii_tokens(user_text)
    return {
        token
        for token in candidate_specific
        if not _specific_token_is_grounded(token, user_text, user_specific)
    }


def is_user_grounded(candidate_text: str, user_messages: Iterable[str]) -> bool:
    if missing_specific_evidence_tokens(candidate_text, user_messages):
        return False
    candidate_tokens = evidence_tokens(candidate_text)
    if not candidate_tokens:
        return False
    user_text = "\n".join(str(m or "") for m in user_messages)
    user_tokens = evidence_tokens(user_text)
    overlap = candidate_tokens & user_tokens
    if len(overlap) >= 2:
        return True
    for token in overlap:
        if len(token) >= 4 or re.search(r"[\u4e00-\u9fff]{3,}", token):
            return True
    return False


def has_memory_write_directive(text: str) -> bool:
    return MEMORY_WRITE_DIRECTIVE_RE.search(str(text or "")) is not None


def is_question_like_user_message(text: str) -> bool:
    text = str(text or "").strip()
    if not text:
        return False
    if "?" in text or "？" in text:
        return True
    return QUESTION_LIKE_RE.search(text) is not None


def allows_durable_distill_from_user_messages(user_messages: Iterable[str]) -> bool:
    texts = [str(m or "").strip() for m in user_messages if str(m or "").strip()]
    if not texts:
        return False
    if any(has_memory_write_directive(text) for text in texts):
        return True
    return any(evidence_tokens(text) and not is_question_like_user_message(text) for text in texts)


def is_uncertain_memory(candidate_text: str) -> bool:
    return UNCERTAIN_MEMORY_RE.search(str(candidate_text or "")) is not None


def should_persist_distilled_memory(
    *,
    candidate_text: str,
    metadata: Mapping[str, Any] | None = None,
    user_messages: Iterable[str] = (),
    require_user_grounding: bool = True,
) -> bool:
    payload = {"text": candidate_text, "metadata": dict(metadata or {})}
    if not is_safe_memory_payload(payload):
        return False
    if is_uncertain_memory(candidate_text):
        return False
    if require_user_grounding and not is_user_grounded(candidate_text, user_messages):
        return False
    return True
