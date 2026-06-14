from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ConversationRecord:
    conversation_id: str
    user_id: str
    messages: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class RedisConversationStore:
    def __init__(self, *, redis_client, ttl_seconds: int = 86400) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds

    def _key(self, conversation_id: str) -> str:
        return f"conv:{conversation_id}"

    def _messages_key(self, conversation_id: str) -> str:
        return f"{self._key(conversation_id)}:messages"

    def _meta_key(self, conversation_id: str) -> str:
        return f"{self._key(conversation_id)}:meta"

    def _supports_incremental(self) -> bool:
        return all(
            hasattr(self._redis, name)
            for name in ("lrange", "rpush", "llen", "delete", "hset", "hgetall", "expire")
        )

    @staticmethod
    def _decode(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    def _read_metadata(self, conversation_id: str) -> tuple[str, Dict[str, Any]]:
        meta_raw = self._redis.hgetall(self._meta_key(conversation_id))
        meta: Dict[str, Any] = {}
        for k, v in (meta_raw or {}).items():
            key = self._decode(k)
            value = self._decode(v)
            if key == "metadata":
                try:
                    loaded = json.loads(value)
                    meta["metadata"] = loaded if isinstance(loaded, dict) else {}
                except Exception:
                    meta["metadata"] = {}
            else:
                meta[key] = value
        return str(meta.get("user_id") or ""), dict(meta.get("metadata") or {})

    def _read_messages(
        self, conversation_id: str, *, max_messages: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        key = self._messages_key(conversation_id)
        if max_messages is not None and max_messages > 0:
            raw_items = self._redis.lrange(key, -int(max_messages), -1)
        else:
            raw_items = self._redis.lrange(key, 0, -1)
        messages: List[Dict[str, Any]] = []
        for raw in raw_items or []:
            try:
                item = json.loads(self._decode(raw))
            except Exception:
                continue
            if isinstance(item, dict):
                messages.append(item)
        return messages

    def get(self, conversation_id: str) -> Optional[ConversationRecord]:
        if self._supports_incremental() and int(self._redis.llen(self._messages_key(conversation_id)) or 0) > 0:
            user_id, metadata = self._read_metadata(conversation_id)
            return ConversationRecord(
                conversation_id=conversation_id,
                user_id=user_id,
                messages=self._read_messages(conversation_id),
                metadata=metadata,
            )

        raw = self._redis.get(self._key(conversation_id))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
        return ConversationRecord(
            conversation_id=conversation_id,
            user_id=str(payload.get("user_id") or ""),
            messages=list(payload.get("messages") or []),
            metadata=dict(payload.get("metadata") or {}),
        )

    def get_recent(
        self, conversation_id: str, *, max_messages: int
    ) -> Optional[ConversationRecord]:
        if self._supports_incremental() and int(self._redis.llen(self._messages_key(conversation_id)) or 0) > 0:
            user_id, metadata = self._read_metadata(conversation_id)
            return ConversationRecord(
                conversation_id=conversation_id,
                user_id=user_id,
                messages=self._read_messages(
                    conversation_id, max_messages=max(1, int(max_messages))
                ),
                metadata=metadata,
            )
        rec = self.get(conversation_id)
        if rec is None:
            return None
        return ConversationRecord(
            conversation_id=rec.conversation_id,
            user_id=rec.user_id,
            messages=rec.messages[-max(1, int(max_messages)) :],
            metadata=rec.metadata,
        )

    def put(
        self,
        *,
        conversation_id: str,
        user_id: str,
        messages: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._supports_incremental():
            msg_key = self._messages_key(conversation_id)
            meta_key = self._meta_key(conversation_id)
            existing_len = int(self._redis.llen(msg_key) or 0)
            if existing_len > len(messages):
                self._redis.delete(msg_key)
                existing_len = 0
            if existing_len == 0:
                to_append = list(messages)
            else:
                to_append = list(messages[existing_len:])
            if to_append:
                self._redis.rpush(
                    msg_key,
                    *[
                        json.dumps(m, ensure_ascii=False)
                        for m in to_append
                        if isinstance(m, dict)
                    ],
                )
            self._redis.hset(
                meta_key,
                mapping={
                    "user_id": str(user_id or ""),
                    "metadata": json.dumps(dict(metadata or {}), ensure_ascii=False),
                },
            )
            self._redis.expire(msg_key, self._ttl)
            self._redis.expire(meta_key, self._ttl)
            return

        payload = json.dumps(
            {"user_id": user_id, "messages": messages, "metadata": dict(metadata or {})}
        )
        self._redis.setex(self._key(conversation_id), self._ttl, payload)
