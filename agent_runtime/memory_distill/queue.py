from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict
from typing import Any, Dict, Optional, Tuple

import redis

from agent_runtime.memory_distill.distill_settings import MemoryDistillSettings
from agent_runtime.memory_distill.job_schema import DistillJob

_CLIENTS_LOCK = threading.Lock()
_CLIENTS: Dict[Tuple[str, int, int, int], redis.Redis] = {}

_ENQUEUE_ONCE_SCRIPT = """
local added = redis.call('SADD', KEYS[2], ARGV[1])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[3]))
if added == 1 then
  redis.call('RPUSH', KEYS[1], ARGV[2])
end
return added
"""

_MOVE_PROCESSING_SCRIPT = """
local removed = redis.call('LREM', KEYS[1], 1, ARGV[1])
if removed > 0 then
  redis.call('RPUSH', KEYS[2], ARGV[2])
end
return removed
"""


def _redis_client(settings: MemoryDistillSettings) -> redis.Redis:
    key = (
        settings.redis_host,
        int(settings.redis_port),
        int(settings.redis_db),
        int(settings.redis_max_connections),
    )
    with _CLIENTS_LOCK:
        client = _CLIENTS.get(key)
        if client is not None:
            return client
        pool = redis.ConnectionPool(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            max_connections=settings.redis_max_connections,
            decode_responses=False,
        )
        client = redis.Redis(connection_pool=pool)
        _CLIENTS[key] = client
        return client


def enqueue_distill_job(
    *,
    settings: MemoryDistillSettings,
    job: DistillJob,
) -> Dict[str, Any]:
    """Enqueue distillation job; uses a dedupe set to prevent duplicates."""
    if not settings.enabled:
        return {"status": "skipped", "reason": "disabled"}

    client = _redis_client(settings)
    job_key = f"{job.job_id}".encode("utf-8")
    job_payload = job.to_json().encode("utf-8")

    added = int(
        client.eval(
            _ENQUEUE_ONCE_SCRIPT,
            2,
            settings.queue_key,
            settings.dedupe_set_key,
            job_key,
            job_payload,
            int(settings.dedupe_ttl_s),
        )
        or 0
    )
    if added <= 0:
        return {"status": "skipped", "reason": "duplicate", "job_id": job.job_id}

    return {"status": "queued", "job_id": job.job_id}


def _processing_key(settings: MemoryDistillSettings) -> str:
    return f"{settings.queue_key}:processing"


def pop_distill_job(
    *,
    settings: MemoryDistillSettings,
    timeout_s: int = 5,
) -> Optional[DistillJob]:
    client = _redis_client(settings)
    try:
        raw: Optional[bytes] = client.brpoplpush(
            settings.queue_key,
            _processing_key(settings),
            timeout=timeout_s,
        )
    except redis.exceptions.TimeoutError:
        return None
    if not raw:
        return None
    return DistillJob.from_json(raw)


def ack_distill_job(
    *,
    settings: MemoryDistillSettings,
    job: DistillJob,
) -> int:
    """Acknowledge a processing job after success, DLQ, or explicit requeue."""

    client = _redis_client(settings)
    processing_key = _processing_key(settings)
    raw = job.to_json().encode("utf-8")
    removed = int(client.lrem(processing_key, 1, raw) or 0)
    if removed:
        return removed

    # Be tolerant of schema migrations or attempt mutations by matching job_id.
    for item in client.lrange(processing_key, 0, -1):
        try:
            candidate = DistillJob.from_json(item)
        except Exception:
            continue
        if candidate.job_id != job.job_id:
            continue
        removed += int(client.lrem(processing_key, 1, item) or 0)
        break
    return removed


def recover_processing_jobs(
    *,
    settings: MemoryDistillSettings,
    max_jobs: int = 1000,
) -> int:
    """Move unacked processing jobs back to the main queue.

    The worker uses BRPOPLPUSH so a crash cannot lose a job. On worker start,
    reclaim pending jobs before polling the main queue.
    """

    client = _redis_client(settings)
    processing_key = _processing_key(settings)
    recovered = 0
    for item in list(client.lrange(processing_key, 0, max(0, int(max_jobs)) - 1)):
        if not item:
            continue
        recovered += int(
            client.eval(
                _MOVE_PROCESSING_SCRIPT,
                2,
                processing_key,
                settings.queue_key,
                item,
                item,
            )
            or 0
        )
    return recovered


def record_job_result(
    *,
    settings: MemoryDistillSettings,
    job_id: str,
    result: Dict[str, Any],
    ok: bool,
) -> None:
    client = _redis_client(settings)
    key = f"{settings.job_result_prefix}{job_id}".encode("utf-8")
    payload = {
        "ok": ok,
        "result": result,
        "ts_s": time.time(),
    }
    client.set(key, json.dumps(payload, ensure_ascii=False).encode("utf-8"), ex=settings.job_result_ttl_s)


def dead_letter_job(
    *,
    settings: MemoryDistillSettings,
    job: DistillJob,
    error: str,
) -> None:
    """Send a job straight to the DLQ without further retries (non-retryable error)."""
    client = _redis_client(settings)
    dlq_key = f"{settings.queue_key}:dlq".encode("utf-8")
    raw = job.to_json().encode("utf-8")
    moved = int(
        client.eval(
            _MOVE_PROCESSING_SCRIPT,
            2,
            _processing_key(settings),
            dlq_key,
            raw,
            raw,
        )
        or 0
    )
    if moved <= 0:
        client.rpush(dlq_key, raw)
    record_job_result(
        settings=settings,
        job_id=job.job_id,
        result={"status": "failed", "error": error, "attempt": int(job.attempt), "non_retryable": True},
        ok=False,
    )


def requeue_with_backoff(
    *,
    settings: MemoryDistillSettings,
    job: DistillJob,
    error: str,
) -> None:
    client = _redis_client(settings)

    attempt = int(job.attempt) + 1
    updated = DistillJob(
        **{**asdict(job), "attempt": attempt},
    )

    # crude backoff: sleep is done by worker; here we only requeue
    if attempt >= settings.max_attempts:
        # dead-letter
        dlq_key = f"{settings.queue_key}:dlq".encode("utf-8")
        moved = int(
            client.eval(
                _MOVE_PROCESSING_SCRIPT,
                2,
                _processing_key(settings),
                dlq_key,
                job.to_json().encode("utf-8"),
                updated.to_json().encode("utf-8"),
            )
            or 0
        )
        if moved <= 0:
            ack_distill_job(settings=settings, job=job)
            client.rpush(dlq_key, updated.to_json().encode("utf-8"))
        record_job_result(
            settings=settings,
            job_id=job.job_id,
            result={"status": "failed", "error": error, "attempt": attempt},
            ok=False,
        )
        return

    moved = int(
        client.eval(
            _MOVE_PROCESSING_SCRIPT,
            2,
            _processing_key(settings),
            settings.queue_key,
            job.to_json().encode("utf-8"),
            updated.to_json().encode("utf-8"),
        )
        or 0
    )
    if moved <= 0:
        ack_distill_job(settings=settings, job=job)
        client.rpush(settings.queue_key, updated.to_json().encode("utf-8"))
