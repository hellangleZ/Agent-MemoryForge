import dataclasses

import redis as redis_pkg

from agent_runtime.memory_distill.distill_settings import MemoryDistillSettings
from agent_runtime.memory_distill.job_schema import new_job
from agent_runtime.memory_distill import queue as distill_queue


class _FakePipeline:
    def __init__(self, client):
        self.client = client
        self.ops = []

    def sadd(self, key, value):
        self.ops.append(("sadd", key, value))
        return self

    def expire(self, key, ttl):
        self.ops.append(("expire", key, ttl))
        return self

    def rpush(self, key, value):
        self.ops.append(("rpush", key, value))
        return self

    def execute(self):
        for op in self.ops:
            name, *args = op
            getattr(self.client, name)(*args)
        return True


class _FakeRedis:
    def __init__(self):
        self.sets = {}
        self.lists = {}
        self.values = {}

    def sismember(self, key, value):
        return value in self.sets.get(key, set())

    def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    def expire(self, key, ttl):
        return None

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def brpoplpush(self, source, destination, timeout=0):
        items = self.lists.get(source, [])
        if not items:
            return None
        value = items.pop()
        self.lists.setdefault(destination, []).insert(0, value)
        return value

    def lrange(self, key, start, end):
        items = list(self.lists.get(key, []))
        if end == -1:
            return items[start:]
        return items[start : end + 1]

    def lrem(self, key, count, value):
        items = self.lists.get(key, [])
        removed = 0
        next_items = []
        for item in items:
            if item == value and (count == 0 or removed < abs(count)):
                removed += 1
                continue
            next_items.append(item)
        self.lists[key] = next_items
        return removed

    def blpop(self, key, timeout=0):
        items = self.lists.get(key, [])
        if not items:
            return None
        return key, items.pop(0)

    def set(self, key, value, ex=None):
        self.values[key] = value

    def pipeline(self, transaction=True):
        return _FakePipeline(self)

    def eval(self, script, numkeys, *keys_and_args):
        keys = list(keys_and_args[:numkeys])
        args = list(keys_and_args[numkeys:])
        if "SADD" in script and "EXPIRE" in script:
            queue_key, dedupe_key = keys
            job_key, payload, ttl = args
            if self.sismember(dedupe_key, job_key):
                self.expire(dedupe_key, ttl)
                return 0
            self.sadd(dedupe_key, job_key)
            self.expire(dedupe_key, ttl)
            self.rpush(queue_key, payload)
            return 1
        if "LREM" in script and "RPUSH" in script:
            processing_key, dest_key = keys
            raw, payload = args
            removed = self.lrem(processing_key, 1, raw)
            if removed:
                self.rpush(dest_key, payload)
            return removed
        raise AssertionError("unsupported fake Redis script")


class _FakeRedisModule:
    exceptions = redis_pkg.exceptions

    def __init__(self, client):
        self._client = client
        self.pool_creations = 0

    def ConnectionPool(self, **kwargs):
        self.pool_creations += 1
        return object()

    def Redis(self, connection_pool=None):
        return self._client


def _settings(enabled=True):
    return MemoryDistillSettings(
        enabled=enabled,
        provider="openai",
        model="gpt",
        temperature=0.1,
        max_output_tokens=100,
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        redis_max_connections=2,
        queue_key="distill:q",
        dedupe_set_key="distill:dedupe",
        dedupe_ttl_s=5,
        job_result_prefix="distill:result:",
        job_result_ttl_s=60,
        max_attempts=2,
        llm_max_attempts=2,
        llm_retry_base_sleep_s=0.1,
    )


def _install_fake_redis(monkeypatch, client):
    distill_queue._CLIENTS.clear()
    fake_module = _FakeRedisModule(client)
    monkeypatch.setattr(distill_queue, "redis", fake_module)
    return fake_module


def test_enqueue_and_pop_distill_job(monkeypatch):
    client = _FakeRedis()
    _install_fake_redis(monkeypatch, client)

    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="u",
        conversation_id="c",
        round_id=1,
        messages=[],
        prior_stm_summaries=[],
        chunk_rounds=10,
        last_user="hi",
        assistant_answer="ok",
    )
    settings = _settings()
    result = distill_queue.enqueue_distill_job(settings=settings, job=job)
    assert result["status"] == "queued"

    popped = distill_queue.pop_distill_job(settings=settings, timeout_s=0)
    assert popped.job_id == job.job_id
    assert client.lists[f"{settings.queue_key}:processing"]


def test_pop_distill_job_returns_none_on_idle_timeout(monkeypatch):
    class _TimeoutRedis(_FakeRedis):
        def brpoplpush(self, source, destination, timeout=0):
            raise redis_pkg.exceptions.TimeoutError("Timeout reading from socket")

    _install_fake_redis(monkeypatch, _TimeoutRedis())

    assert distill_queue.pop_distill_job(settings=_settings(), timeout_s=5) is None


def test_enqueue_skips_duplicates(monkeypatch):
    client = _FakeRedis()
    _install_fake_redis(monkeypatch, client)
    settings = _settings()
    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="u",
        conversation_id="c",
        round_id=1,
        messages=[],
        prior_stm_summaries=[],
        chunk_rounds=10,
        last_user="hi",
        assistant_answer="ok",
    )
    distill_queue.enqueue_distill_job(settings=settings, job=job)
    result = distill_queue.enqueue_distill_job(settings=settings, job=job)
    assert result["status"] == "skipped"


def test_record_job_result(monkeypatch):
    client = _FakeRedis()
    _install_fake_redis(monkeypatch, client)
    settings = _settings()
    distill_queue.record_job_result(settings=settings, job_id="j1", result={"ok": True}, ok=True)
    key = f"{settings.job_result_prefix}j1".encode("utf-8")
    assert key in client.values


def test_recover_processing_jobs_requeues_unacked_job(monkeypatch):
    client = _FakeRedis()
    _install_fake_redis(monkeypatch, client)
    settings = _settings()
    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="u",
        conversation_id="c",
        round_id=1,
        messages=[],
        prior_stm_summaries=[],
        chunk_rounds=10,
        last_user="hi",
        assistant_answer="ok",
    )

    distill_queue.enqueue_distill_job(settings=settings, job=job)
    popped = distill_queue.pop_distill_job(settings=settings, timeout_s=0)
    assert popped.job_id == job.job_id

    recovered = distill_queue.recover_processing_jobs(settings=settings)
    assert recovered == 1
    popped_again = distill_queue.pop_distill_job(settings=settings, timeout_s=0)
    assert popped_again.job_id == job.job_id


def test_ack_distill_job_removes_processing_payload(monkeypatch):
    client = _FakeRedis()
    _install_fake_redis(monkeypatch, client)
    settings = _settings()
    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="u",
        conversation_id="c",
        round_id=1,
        messages=[],
        prior_stm_summaries=[],
        chunk_rounds=10,
        last_user="hi",
        assistant_answer="ok",
    )

    distill_queue.enqueue_distill_job(settings=settings, job=job)
    popped = distill_queue.pop_distill_job(settings=settings, timeout_s=0)
    assert distill_queue.ack_distill_job(settings=settings, job=popped) == 1
    assert client.lists.get(f"{settings.queue_key}:processing") == []


def test_requeue_with_backoff_dlq(monkeypatch):
    client = _FakeRedis()
    _install_fake_redis(monkeypatch, client)
    settings = _settings()
    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="u",
        conversation_id="c",
        round_id=1,
        messages=[],
        prior_stm_summaries=[],
        chunk_rounds=10,
        last_user="hi",
        assistant_answer="ok",
    )
    job = dataclasses.replace(job, attempt=settings.max_attempts)
    distill_queue.requeue_with_backoff(settings=settings, job=job, error="boom")
    dlq_key = f"{settings.queue_key}:dlq".encode("utf-8")
    assert dlq_key in client.lists


def test_enqueue_disabled(monkeypatch):
    client = _FakeRedis()
    _install_fake_redis(monkeypatch, client)
    settings = _settings(enabled=False)
    job = new_job(
        tenant_id="t",
        workspace_id="w",
        user_id="u",
        conversation_id="c",
        round_id=1,
        messages=[],
        prior_stm_summaries=[],
        chunk_rounds=10,
        last_user="hi",
        assistant_answer="ok",
    )
    result = distill_queue.enqueue_distill_job(settings=settings, job=job)
    assert result["status"] == "skipped"


def test_distill_queue_reuses_redis_client_for_same_settings(monkeypatch):
    client = _FakeRedis()
    fake_module = _install_fake_redis(monkeypatch, client)
    settings = _settings()

    first = distill_queue._redis_client(settings)
    second = distill_queue._redis_client(settings)

    assert first is second
    assert fake_module.pool_creations == 1


def test_distill_settings_default_model_follows_openai_model(monkeypatch):
    # Avoid accidental 404s by ensuring the distill worker defaults to the main model/deployment.
    from agent_runtime.memory_distill.distill_settings import MemoryDistillSettings

    monkeypatch.delenv("MEMORY_DISTILL_MODEL", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "my_deployment")

    settings = MemoryDistillSettings.from_env()
    assert settings.model == "my_deployment"
