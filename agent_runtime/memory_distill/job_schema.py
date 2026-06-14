from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class DistillJob:
    job_id: str
    attempt: int

    tenant_id: str
    workspace_id: str

    user_id: str
    conversation_id: str
    round_id: int

    # Full merged messages (chat format)
    messages: List[Dict[str, Any]]

    # Fast access
    last_user: str
    assistant_answer: str

    created_at_s: float

    # Optional: last few STM summaries to support incremental checkpointing.
    prior_stm_summaries: List[Dict[str, Any]] = field(default_factory=list)
    # Optional: how many rounds are included in `messages` (for debugging/analytics).
    chunk_rounds: Optional[int] = None
    trace_id: Optional[str] = None
    content_hash: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | bytes) -> "DistillJob":
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        return cls(**data)


def content_fingerprint(
    *,
    messages: List[Dict[str, Any]],
    last_user: str,
    assistant_answer: str,
    chunk_rounds: Optional[int] = None,
) -> str:
    payload: Dict[str, Any] = {
        "messages": messages or [],
        "last_user": last_user or "",
        "assistant_answer": assistant_answer or "",
    }
    if chunk_rounds is not None:
        payload["chunk_rounds"] = int(chunk_rounds)
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def stable_job_id(
    *,
    tenant_id: str,
    workspace_id: str,
    conversation_id: str,
    round_id: int,
    content_hash: Optional[str] = None,
) -> str:
    parts = [tenant_id, workspace_id, conversation_id, str(round_id)]
    if content_hash:
        parts.append(content_hash)
    base = "|".join(parts).encode("utf-8")
    return hashlib.sha256(base).hexdigest()[:32]


def new_job(
    *,
    tenant_id: str,
    workspace_id: str,
    user_id: str,
    conversation_id: str,
    round_id: int,
    messages: List[Dict[str, Any]],
    last_user: str,
    assistant_answer: str,
    prior_stm_summaries: Optional[List[Dict[str, Any]]] = None,
    chunk_rounds: Optional[int] = None,
    trace_id: Optional[str] = None,
    use_stable_id: bool = True,
) -> DistillJob:
    content_hash = content_fingerprint(
        messages=messages,
        last_user=last_user,
        assistant_answer=assistant_answer,
        chunk_rounds=chunk_rounds,
    )
    job_id = (
        stable_job_id(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            round_id=round_id,
            content_hash=content_hash,
        )
        if use_stable_id
        else uuid.uuid4().hex
    )
    return DistillJob(
        job_id=job_id,
        attempt=0,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        user_id=user_id,
        conversation_id=conversation_id,
        round_id=round_id,
        messages=messages,
        prior_stm_summaries=list(prior_stm_summaries or []),
        chunk_rounds=chunk_rounds,
        last_user=last_user,
        assistant_answer=assistant_answer,
        created_at_s=time.time(),
        trace_id=trace_id,
        content_hash=content_hash,
    )
