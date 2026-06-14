from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


_YES_RE = re.compile(r"^\s*yes\s*$", re.IGNORECASE)
_CANCEL_RE = re.compile(r"^\s*(cancel|取消|终止|停止)\s*$", re.IGNORECASE)
_STEP_LINE_RE = re.compile(r"^\s*(\d+)\s*-\s*(.+?)\s*$")


def is_yes(text: str) -> bool:
    return bool(_YES_RE.match(text or ""))


def is_cancel(text: str) -> bool:
    return bool(_CANCEL_RE.match(text or ""))


def parse_numbered_steps(text: str, *, max_steps: int = 10) -> Optional[List[str]]:
    """Parse user-provided steps from `1- ...` lines.

    Returns a list of step text (max `max_steps`) or None if the text is not a
    valid steps list.
    """
    if not text or not text.strip():
        return None
    steps: List[Tuple[int, str]] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        m = _STEP_LINE_RE.match(raw)
        if not m:
            return None
        idx = int(m.group(1))
        body = m.group(2).strip()
        if not body:
            return None
        steps.append((idx, body))

    if not steps:
        return None
    steps.sort(key=lambda x: x[0])

    # Enforce contiguous numbering starting from 1 for stability.
    expected = 1
    out: List[str] = []
    for idx, body in steps:
        if idx != expected:
            return None
        out.append(body)
        expected += 1
        if len(out) >= max_steps:
            break
    return out


@dataclass(frozen=True)
class StepModeDraft:
    goal: str
    steps: List[str]
    source_user_query: str


STEP_MODE_DECIDER_SYSTEM_PROMPT = """You are a product assistant that decides whether a user request should be handled step-by-step.

If the request is a multi-step task (implementation, debugging, refactor, long workflow, or anything that benefits from a checklist), propose a short step plan.

Return STRICT JSON only (no markdown, no code fences):
{
  "offer": true,
  "goal": "short goal",
  "steps": ["step 1", "step 2", "..."]
}

Rules:
- If NOT needed, return: {"offer": false}
- Keep steps concise and actionable.
- Maximum 10 steps.
"""


def parse_step_mode_decider_json(raw: str) -> Dict[str, Any]:
    try:
        return json.loads((raw or "").strip())
    except Exception:
        return {}


def normalize_steps(steps: Sequence[Any] | None, *, max_steps: int = 10) -> List[str]:
    out: List[str] = []
    for s in list(steps or []):
        t = str(s or "").strip()
        if not t:
            continue
        out.append(t)
        if len(out) >= max_steps:
            break
    return out


def build_confirmation_message(*, goal: str, steps: Sequence[str], max_steps: int = 10) -> str:
    goal = str(goal or "").strip()
    lines: List[str] = []
    if goal:
        lines.append(f"我建议按步骤推进，目标是：{goal}")
    else:
        lines.append("我建议按步骤推进。")
    lines.append("")
    lines.append("草案步骤（最多10条）：")
    for i, s in enumerate(list(steps)[:max_steps], start=1):
        lines.append(f"{i}- {str(s).strip()}")
    lines.append("")
    lines.append("请用以下两种方式之一回复：")
    lines.append("- 回复 `yes`：接受草案，直接开始执行第1步")
    lines.append("- 或用 `1- ...` `2- ...` 的格式发你认可的步骤（最多10条），我将按你的步骤开始")
    return "\n".join(lines).strip()


def build_wm_state_for_steps(
    *,
    conversation_id: str,
    user_id: str,
    goal: str,
    steps: Sequence[str],
    mode: str = "step_mode",
) -> Dict[str, Any]:
    norm_steps = []
    for i, s in enumerate(list(steps), start=1):
        t = str(s).strip()
        if not t:
            continue
        norm_steps.append({"id": str(i), "text": t, "status": "todo"})
    return {
        "wm_id": str(conversation_id),
        "conversation_id": str(conversation_id),
        "user_id": str(user_id),
        "mode": str(mode),
        "status": "active",
        "goal": str(goal or "").strip(),
        "steps": norm_steps,
    }

