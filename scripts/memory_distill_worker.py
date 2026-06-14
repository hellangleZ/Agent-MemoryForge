from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

from agent_memory_framework.memory_distill.distiller import (
    build_distill_messages,
    build_stm_checkpoint_messages,
    parse_distill_output,
)
from agent_memory_framework.memory_distill.llm_provider import (
    DistillLLMConfig,
    call_distill_llm,
)
from agent_memory_framework.memory_runtime.memory_safety import (
    allows_durable_distill_from_user_messages,
    is_safe_preference,
    should_persist_distilled_memory,
)
from agent_memory_lib import MemoryClient
from agent_runtime.memory_distill.distill_settings import MemoryDistillSettings
from agent_runtime.memory_distill.queue import (
    ack_distill_job,
    dead_letter_job,
    pop_distill_job,
    recover_processing_jobs,
    record_job_result,
    requeue_with_backoff,
)
from agent_runtime.product.observability import log_structured_event
from utils.logging_config import get_logger


logger = get_logger(__name__)

_RESPONSE_PREFERENCE_KEY_RE = re.compile(
    r"(?i)(answer|reply|response|language|locale|style|tone|format|verbosity|concise|brief|lang|回答|回复|语言|风格|格式|语气|长短)"
)
_RESPONSE_PREFERENCE_TEXT_RE = re.compile(
    r"(?i)("
    r"(以后|后续|之后|接下来|always|future|from now on).{0,24}(回答|回复|respond|reply|answer)|"
    r"(回答|回复|respond|reply|answer).{0,32}(中文|英文|短句|简短|简洁|精简|风格|格式|语气|language|style|tone|format|concise|brief|short)|"
    r"(中文|英文|短句|简短|简洁|精简|language|style|tone|format|concise|brief|short).{0,32}(回答|回复|respond|reply|answer)"
    r")"
)
_USER_SUBJECTS = {
    "user",
    "users",
    "用户",
    "客户",
    "tenant_user",
    "end_user",
}


def _bool_env(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _float_env(name: str, default: float) -> float:
    val = os.getenv(name)
    if val is None or not val.strip():
        return default
    try:
        return float(val)
    except Exception:
        return default


def _load_dotenv_best_effort() -> None:
    """
    The gateway loads `.env`, but this standalone worker is often launched manually.
    Make env loading best-effort so `.env` configuration is honored without requiring
    users to `source .env` in every shell.
    """
    dotenv_path = os.getenv("DOTENV_PATH")
    if dotenv_path:
        load_dotenv(dotenv_path=dotenv_path, override=False)
        return

    repo_root = Path(__file__).resolve().parents[1]
    candidate = repo_root / ".env"
    if candidate.exists():
        load_dotenv(dotenv_path=candidate, override=False)


def _sleep_backoff_s(attempt: int) -> float:
    # 0.. -> 0.5,1,2,4,8
    return min(8.0, 0.5 * (2 ** max(0, attempt - 1)))


def _job_user_messages(job) -> list[str]:
    messages: list[str] = []
    last_user = str(getattr(job, "last_user", "") or "").strip()
    if last_user:
        messages.append(last_user)
    for item in getattr(job, "messages", None) or []:
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        text = str(item.get("content") or "").strip()
        if text:
            messages.append(text)
    return messages


def _preference_has_user_evidence(
    *,
    key: str,
    value: Any,
    user_messages: list[str],
    require_user_grounding: bool,
) -> bool:
    if not require_user_grounding:
        return should_persist_distilled_memory(
            candidate_text=f"{key}: {value}",
            metadata={"key": key, "value": value, "source": "distill"},
            user_messages=user_messages,
            require_user_grounding=False,
        )

    if should_persist_distilled_memory(
        candidate_text=f"{key}: {value}",
        metadata={"key": key, "value": value, "source": "distill"},
        user_messages=user_messages,
        require_user_grounding=True,
    ):
        return True

    value_text = str(value if value is not None else "").strip()
    if not value_text:
        return False

    # Distillers normalize preference keys (for example answer_style/language).
    # The user's evidence must support the visible preference value, not the
    # internal normalized key name.
    return should_persist_distilled_memory(
        candidate_text=value_text,
        metadata={"key": key, "value": value, "source": "distill"},
        user_messages=user_messages,
        require_user_grounding=True,
    )


def _preference_candidates(result) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for pref in getattr(result, "preferences", None) or []:
        if not isinstance(pref, dict):
            continue
        key = str(pref.get("key") or "").strip()
        value = str(pref.get("value") or "").strip()
        if key or value:
            candidates.append((key, value))
    return candidates


def _is_response_preference_key(key: str) -> bool:
    return _RESPONSE_PREFERENCE_KEY_RE.search(str(key or "")) is not None


def _is_response_preference_text(text: str, preferences: list[tuple[str, str]]) -> bool:
    text = str(text or "").strip()
    if not text:
        return False
    if _RESPONSE_PREFERENCE_TEXT_RE.search(text):
        return True

    lower = text.lower()
    for key, value in preferences:
        value = str(value or "").strip()
        if not value:
            continue
        if value.lower() not in lower:
            continue
        if _is_response_preference_key(key) or _RESPONSE_PREFERENCE_TEXT_RE.search(
            f"回答 {value}"
        ):
            return True
    return False


def _is_user_response_preference_relation(
    *, subject: str, relation: str, obj: str, preferences: list[tuple[str, str]]
) -> bool:
    normalized_subject = str(subject or "").strip().lower()
    if normalized_subject not in _USER_SUBJECTS:
        return False
    relation_text = str(relation or "").strip()
    if _is_response_preference_key(relation_text):
        return True
    return _is_response_preference_text(
        f"{relation_text} {obj}",
        preferences,
    )


def _store_distilled_memories(*, base_url: str, job, result) -> Dict[str, Any]:
    client = MemoryClient(base_url).with_scope(
        tenant_id=job.tenant_id, workspace_id=job.workspace_id
    )

    semantic_min_importance = _float_env("MEMORY_DISTILL_SEMANTIC_MIN_IMPORTANCE", 0.6)
    require_user_grounding = _bool_env("MEMORY_DISTILL_REQUIRE_USER_GROUNDING", True)
    graph_min_confidence = _float_env("MEMORY_DISTILL_GRAPH_MIN_CONFIDENCE", 0.6)
    user_messages = _job_user_messages(job)
    allow_durable_distill = allows_durable_distill_from_user_messages(user_messages)
    preference_candidates = _preference_candidates(result)

    store_prefs = _bool_env("MEMORY_DISTILL_STORE_PREFERENCES", True)
    pref_require_confirm = _bool_env(
        "MEMORY_DISTILL_PREFERENCE_REQUIRE_CONFIRMATION", False
    )
    pref_min_conf = _float_env("MEMORY_DISTILL_PREFERENCE_MIN_CONFIDENCE", 0.8)
    summary: Dict[str, Any] = {
        "job_id": job.job_id,
        "round_id": int(job.round_id),
        "tenant_id": job.tenant_id,
        "workspace_id": job.workspace_id,
        "conversation_id": job.conversation_id,
        "allow_durable_distill": bool(allow_durable_distill),
        "candidate_counts": {
            "stm": 1 if result.stm_summary else 0,
            "semantic": len(getattr(result, "semantic_facts", []) or []),
            "preferences": len(getattr(result, "preferences", []) or []),
            "graph": len(getattr(result, "kg_relations", []) or []),
        },
        "written": {"stm": 0, "semantic": 0, "preferences": 0, "graph": 0},
        "skipped": {},
    }

    def _written(tier: str) -> None:
        written = summary["written"]
        written[tier] = int(written.get(tier, 0)) + 1

    def _skipped(reason: str, count: int = 1) -> None:
        skipped = summary["skipped"]
        skipped[reason] = int(skipped.get(reason, 0)) + int(count)

    # STM summary
    if result.stm_summary:
        stm_summary = result.stm_summary if isinstance(result.stm_summary, dict) else {}
        # `content` must be a string (validated by the memory service). Keep the full
        # structured summary in metadata for later retrieval.
        content = (
            stm_summary.get("final_answer") or stm_summary.get("user_request") or ""
        )
        content = str(content).strip() if content is not None else ""
        if not content:
            content = "(empty summary)"

        stm_metadata = {
            "user_id": job.user_id,
            "conversation_id": job.conversation_id,
            "round_id": int(job.round_id),
            "source": "distill",
            "stm_summary": {
                "conversation_id": job.conversation_id,
                "round_id": int(job.round_id),
                **stm_summary,
            },
        }
        if should_persist_distilled_memory(
            candidate_text=content,
            metadata=stm_metadata,
            user_messages=user_messages,
            require_user_grounding=False,
        ):
            client.memory_write(
                tier="stm",
                scope="conversation",
                target="stm",
                conversation_id=job.conversation_id,
                content=content,
                metadata=stm_metadata,
            )
            _written("stm")
        else:
            _skipped("stm.safety_filter")
    else:
        _skipped("stm.empty_candidate")

    # Semantic facts
    if allow_durable_distill:
        for fact in result.semantic_facts:
            text = (fact.get("text") or "").strip()
            if not text:
                _skipped("semantic.empty_text")
                continue
            try:
                importance = float(fact.get("importance") or 0.0)
            except Exception:
                importance = 0.0
            if importance < float(semantic_min_importance):
                _skipped("semantic.low_importance")
                continue
            if _is_response_preference_text(text, preference_candidates):
                _skipped("semantic.response_preference")
                continue
            metadata = {
                "user_id": job.user_id,
                "conversation_id": job.conversation_id,
                "round_id": int(job.round_id),
                "source": "distill",
                "importance": importance,
                "tags": fact.get("tags") or [],
            }
            if not should_persist_distilled_memory(
                candidate_text=text,
                metadata=metadata,
                user_messages=user_messages,
                require_user_grounding=require_user_grounding,
            ):
                _skipped("semantic.safety_filter")
                continue
            client.memory_write(
                tier="semantic",
                scope="project",
                target="daily",
                content=text,
                metadata=metadata,
            )
            _written("semantic")
    elif result.semantic_facts:
        _skipped("semantic.durable_not_allowed", len(result.semantic_facts))

    # Episodic is deprecated/removed from the product surface. Event history
    # should come from durable evidence (audit/trace/commits), not distillation.

    # Preferences persist automatically when grounded in the user's message.
    # Deployments can disable storage or opt into a separate confirmation path.
    if allow_durable_distill and store_prefs and (pref_require_confirm is False):
        for pref in result.preferences:
            key = (pref.get("key") or "").strip()
            if not key:
                _skipped("preferences.empty_key")
                continue
            value = pref.get("value")
            try:
                conf = float(pref.get("confidence") or 0.0)
            except Exception:
                conf = 0.0
            if conf < float(pref_min_conf):
                _skipped("preferences.low_confidence")
                continue
            if not is_safe_preference(key, value):
                _skipped("preferences.unsafe")
                continue
            if not _preference_has_user_evidence(
                key=key,
                value=value,
                user_messages=user_messages,
                require_user_grounding=require_user_grounding,
            ):
                _skipped("preferences.no_user_evidence")
                continue
            client.memory_write(
                tier="preferences",
                scope="user",
                target="preferences",
                content=f"{key}: {value}",
                metadata={
                    "user_id": job.user_id,
                    "key": key,
                    "value": value,
                    "confidence": conf,
                    "source": "distill",
                    "conversation_id": job.conversation_id,
                    "round_id": int(job.round_id),
                },
            )
            _written("preferences")
    elif result.preferences:
        if not allow_durable_distill:
            _skipped("preferences.durable_not_allowed", len(result.preferences))
        elif not store_prefs:
            _skipped("preferences.disabled", len(result.preferences))
        elif pref_require_confirm:
            _skipped("preferences.confirmation_required", len(result.preferences))

    # KG relations (optional; can be disabled operationally by not running Neo4j)
    if allow_durable_distill:
        for rel in result.kg_relations:
            subject = (rel.get("subject") or "").strip()
            relation = (rel.get("relation") or "").strip()
            obj = (rel.get("obj") or "").strip()
            if not (subject and relation and obj):
                _skipped("graph.incomplete_relation")
                continue
            try:
                conf = float(rel.get("confidence") or 0.0)
            except Exception:
                conf = 0.0
            if conf < float(graph_min_confidence):
                _skipped("graph.low_confidence")
                continue
            if _is_user_response_preference_relation(
                subject=subject,
                relation=relation,
                obj=obj,
                preferences=preference_candidates,
            ):
                _skipped("graph.response_preference")
                continue
            rel_text = f"{subject} -[{relation}]-> {obj}"
            rel_metadata = {
                "subject": subject,
                "relation": relation,
                "obj": obj,
                "source": "distill",
                "conversation_id": job.conversation_id,
                "round_id": int(job.round_id),
            }
            if not should_persist_distilled_memory(
                candidate_text=f"{subject} {obj}",
                metadata=rel_metadata,
                user_messages=user_messages,
                require_user_grounding=require_user_grounding,
            ):
                _skipped("graph.safety_filter")
                continue
            client.memory_write(
                tier="graph",
                scope="project",
                target="graph",
                content=rel_text,
                metadata=rel_metadata,
            )
            _written("graph")
    elif result.kg_relations:
        _skipped("graph.durable_not_allowed", len(result.kg_relations))

    return summary


def _ensure_non_empty_stm_summary(*, job, parsed, llm_cfg) -> Any:
    """Providers sometimes return `{}` or other non-useful output. Ensure STM is not empty."""
    try:
        stm = getattr(parsed, "stm_summary", None) or {}
        final = ""
        if isinstance(stm, dict):
            final = str(stm.get("final_answer") or "").strip()
        if final:
            return parsed
    except Exception:
        pass

    try:
        fallback_messages = build_stm_checkpoint_messages(
            user_id=job.user_id,
            conversation_id=job.conversation_id,
            round_id=int(job.round_id),
            last_user=job.last_user,
            assistant_answer=job.assistant_answer,
            chunk_messages=job.messages or [],
            prior_stm_summaries=getattr(job, "prior_stm_summaries", None),
        )
        raw = call_distill_llm(cfg=llm_cfg, messages=fallback_messages)
        text = str(raw or "").strip()
        if not text:
            # Last-resort deterministic summary for extreme provider failures.
            prior = getattr(job, "prior_stm_summaries", None) or []
            text = (
                f"Checkpoint (round {int(job.round_id)}): "
                f"last_user={str(job.last_user)[:240]!r}; "
                f"assistant={str(job.assistant_answer)[:240]!r}; "
                f"chunk_messages={len(job.messages or [])}; "
                f"prior_stm={len(prior)}"
            )

        # Re-wrap into a DistillResult-like object.
        from agent_memory_framework.memory_distill.distiller import DistillResult

        return DistillResult(
            stm_summary={"final_answer": text},
            semantic_facts=getattr(parsed, "semantic_facts", []) or [],
            preferences=getattr(parsed, "preferences", []) or [],
            kg_relations=getattr(parsed, "kg_relations", []) or [],
        )
    except Exception as exc:  # noqa: BLE001
        # Fallback summary generation failed; we still return the original
        # parsed result (possibly empty) so the worker does not crash, but log
        # it so an empty STM summary landing in memory is traceable.
        logger.warning("STM fallback summary failed, using original parsed: %s", exc)
        return parsed


def _is_non_retryable(err: str) -> bool:
    """Auth / model-not-found style errors won't succeed on retry; dead-letter fast."""
    e = (err or "").lower()
    needles = (
        "401",
        "403",
        "unauthorized",
        "invalid api key",
        "invalid_api_key",
        "permission",
        "access denied",
        "404",
        "not found",
        "does not exist",
        "model_not_found",
        "deploymentnotfound",
        "no such model",
    )
    return any(n in e for n in needles)


def main() -> int:
    _load_dotenv_best_effort()

    parser = argparse.ArgumentParser(description="Async memory distillation worker")
    parser.add_argument(
        "--memory-service-url",
        default=os.getenv("MEMORY_SERVICE_URL", "http://127.0.0.1:8001"),
    )
    parser.add_argument("--once", action="store_true", help="Process one job and exit")
    args = parser.parse_args()

    settings = MemoryDistillSettings.from_env()
    if not settings.enabled:
        logger.warning("MEMORY_DISTILL_ENABLED is false; worker exiting")
        return 2

    llm_cfg = DistillLLMConfig(
        provider=settings.provider,
        model=settings.model,
        temperature=settings.temperature,
        max_output_tokens=settings.max_output_tokens,
        max_attempts=settings.llm_max_attempts,
        retry_base_sleep_s=settings.llm_retry_base_sleep_s,
        timeout_s=getattr(settings, "timeout_s", 45.0),
        openai_api_key=settings.openai_api_key,
        openai_base_url=settings.openai_base_url,
        api_style=getattr(settings, "api_style", "auto"),
        azure_api_key=settings.azure_api_key,
        azure_endpoint=settings.azure_endpoint,
        azure_deployment=settings.azure_deployment,
        azure_api_version=settings.azure_api_version,
    )

    logger.info(
        "distill worker started queue=%s provider=%s model=%s",
        settings.queue_key,
        llm_cfg.provider,
        llm_cfg.model,
    )
    try:
        recovered = recover_processing_jobs(settings=settings)
        if recovered:
            logger.warning("recovered %s unacked distill jobs", recovered)
    except Exception:
        logger.exception("distill processing queue recovery failed")

    while True:
        job = pop_distill_job(settings=settings, timeout_s=5)
        if job is None:
            if args.once:
                return 0
            continue

        logger.info(
            "distill job started job_id=%s round_id=%s attempt=%s",
            job.job_id,
            job.round_id,
            job.attempt,
        )
        job_started_s = time.monotonic()
        log_structured_event(
            logger,
            "distill.job.start",
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            workspace_id=job.workspace_id,
            user_id=job.user_id,
            conversation_id=job.conversation_id,
            round_id=int(job.round_id),
            attempt=int(job.attempt),
        )

        try:
            messages = build_distill_messages(
                user_id=job.user_id,
                conversation_id=job.conversation_id,
                round_id=int(job.round_id),
                last_user=job.last_user,
                assistant_answer=job.assistant_answer,
                history=job.messages,
                prior_stm_summaries=getattr(job, "prior_stm_summaries", None),
            )
            raw = call_distill_llm(cfg=llm_cfg, messages=messages)
            parsed = parse_distill_output(raw)
            parsed = _ensure_non_empty_stm_summary(
                job=job, parsed=parsed, llm_cfg=llm_cfg
            )

            store_summary = _store_distilled_memories(
                base_url=args.memory_service_url,
                job=job,
                result=parsed,
            )
            log_structured_event(
                logger,
                "distill.store",
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                workspace_id=job.workspace_id,
                user_id=job.user_id,
                conversation_id=job.conversation_id,
                round_id=int(job.round_id),
                summary=store_summary,
            )

            record_job_result(
                settings=settings,
                job_id=job.job_id,
                result={
                    "status": "success",
                    "attempt": int(job.attempt),
                    "store_summary": store_summary,
                },
                ok=True,
            )
            ack_distill_job(settings=settings, job=job)
            logger.info(
                "distilled job ok job_id=%s round_id=%s", job.job_id, job.round_id
            )
            log_structured_event(
                logger,
                "distill.job.success",
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                workspace_id=job.workspace_id,
                user_id=job.user_id,
                conversation_id=job.conversation_id,
                round_id=int(job.round_id),
                attempt=int(job.attempt),
                duration_ms=round((time.monotonic() - job_started_s) * 1000, 3),
            )
        except Exception as exc:
            err = str(exc)
            logger.exception("distill job failed job_id=%s", job.job_id)
            log_structured_event(
                logger,
                "distill.job.error",
                level="error",
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                workspace_id=job.workspace_id,
                user_id=job.user_id,
                conversation_id=job.conversation_id,
                round_id=int(job.round_id),
                attempt=int(job.attempt),
                duration_ms=round((time.monotonic() - job_started_s) * 1000, 3),
                error_type=type(exc).__name__,
                error=err,
            )
            record_job_result(
                settings=settings,
                job_id=job.job_id,
                result={"status": "error", "error": err, "attempt": int(job.attempt)},
                ok=False,
            )

            if _is_non_retryable(err):
                logger.error(
                    "distill job non-retryable (auth/not-found); dead-lettering job_id=%s",
                    job.job_id,
                )
                dead_letter_job(settings=settings, job=job, error=err)
            else:
                time.sleep(_sleep_backoff_s(int(job.attempt)))
                requeue_with_backoff(settings=settings, job=job, error=err)

        if args.once:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
