import json

from agent_runtime.product.conversation_store import RedisConversationStore


class _FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def setex(self, key, ttl, payload):
        # Store bytes-like to mirror redis-py behavior.
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        self.data[key] = payload


class _FakeIncrementalRedis(_FakeRedis):
    def __init__(self):
        super().__init__()
        self.lists = {}
        self.hashes = {}
        self.expiries = {}

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        if start < 0:
            start = max(0, len(items) + start)
        if end < 0:
            end = len(items) + end
        return items[start : end + 1]

    def rpush(self, key, *values):
        self.lists.setdefault(key, []).extend(values)

    def llen(self, key):
        return len(self.lists.get(key, []))

    def delete(self, key):
        self.lists.pop(key, None)

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def expire(self, key, ttl):
        self.expiries[key] = ttl


def test_conversation_store_roundtrips_metadata():
    r = _FakeRedis()
    store = RedisConversationStore(redis_client=r, ttl_seconds=10)
    store.put(
        conversation_id="c1",
        user_id="u1",
        messages=[{"role": "user", "content": "hi"}],
        metadata={"step_mode": {"status": "awaiting_confirmation", "steps": ["a"]}},
    )
    rec = store.get("c1")
    assert rec is not None
    assert rec.user_id == "u1"
    assert rec.messages and rec.messages[0]["content"] == "hi"
    assert rec.metadata["step_mode"]["status"] == "awaiting_confirmation"


def test_conversation_store_is_backward_compatible_with_missing_metadata():
    r = _FakeRedis()
    store = RedisConversationStore(redis_client=r, ttl_seconds=10)
    # Simulate old payload shape.
    r.setex("conv:c2", 10, json.dumps({"user_id": "u2", "messages": []}))
    rec = store.get("c2")
    assert rec is not None
    assert rec.metadata == {}


def test_conversation_store_uses_incremental_lists_and_reads_recent_only():
    r = _FakeIncrementalRedis()
    store = RedisConversationStore(redis_client=r, ttl_seconds=10)

    store.put(
        conversation_id="c3",
        user_id="u3",
        messages=[
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
        ],
        metadata={"m": 1},
    )
    store.put(
        conversation_id="c3",
        user_id="u3",
        messages=[
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
            {"role": "user", "content": "three"},
        ],
        metadata={"m": 2},
    )

    assert len(r.lists["conv:c3:messages"]) == 3
    recent = store.get_recent("c3", max_messages=1)
    assert recent is not None
    assert [m["content"] for m in recent.messages] == ["three"]
    assert recent.metadata == {"m": 2}
