"""
记忆管理模块
管理STM、WM、LTM等记忆的同步和维护
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from utils.logging_config import get_logger
from agent_memory_lib import MemoryClient

from agent_memory_framework.memory_runtime.policies import MemoryPolicy

logger = get_logger(__name__)


class MemoryManager:
    """
    记忆管理器
    负责管理Agent的所有记忆操作
    """

    def __init__(
        self,
        memory_client: MemoryClient,
        user_id: str,
        conversation_id: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化记忆管理器

        Args:
            memory_client: Memory服务客户端
            user_id: 用户ID
            conversation_id: 可选的对话ID
            config: 可选的配置
        """
        self.memory_client = memory_client
        self.user_id = user_id
        self.conversation_id = conversation_id or f"conv_{user_id}"
        self.config = config or {}

        policy = MemoryPolicy.from_config(self.config)

        # STM配置
        self.stm_max_summaries = policy.stm_max_summaries
        self.stm_ttl = policy.stm_ttl_s

        # WM配置
        self.wm_max_size = policy.wm_max_size
        self.wm_ttl_s = policy.wm_ttl_s

        self.semantic_top_k = policy.semantic_top_k

        self.logger = logger

    def sync_conversation_to_stm(
        self, round_id: int, messages: List[Dict[str, Any]], summary: str
    ) -> Dict[str, Any]:
        """
        同步对话到STM

        Args:
            round_id: 对话轮次ID
            messages: 对话消息列表
            summary: 对话摘要

        Returns:
            同步结果
        """
        try:
            result = self.memory_client.store_stm(
                conversation_id=self.conversation_id, round_id=round_id, summary=summary
            )

            self.logger.info(f"Synced round {round_id} to STM: {summary[:50]}...")

            return result

        except Exception as e:
            self.logger.error(f"Failed to sync to STM: {e}")
            return {"status": "error", "message": str(e)}

    def retrieve_stm_summaries(
        self, last_k: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        检索STM摘要

        Args:
            last_k: 获取最近k条摘要

        Returns:
            STM摘要列表
        """
        try:
            k = last_k or self.stm_max_summaries

            result = self.memory_client.retrieve_stm(
                conversation_id=self.conversation_id, last_k=k
            )

            if result.get("status") == "success":
                summaries = result.get("data", [])
                self.logger.debug(f"Retrieved {len(summaries)} STM summaries")
                return summaries

            return []

        except Exception as e:
            self.logger.error(f"Failed to retrieve STM summaries: {e}")
            return []

    def store_wm_state(self, task_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        存储工作记忆状态

        Args:
            task_id: 任务ID
            state: 任务状态

        Returns:
            存储结果
        """
        try:
            result = self.memory_client.store_wm(
                user_id=self.user_id, task_id=task_id, state=state, ttl_s=self.wm_ttl_s
            )

            self.logger.debug(f"Stored WM state for task: {task_id}")

            return result

        except Exception as e:
            self.logger.error(f"Failed to store WM state: {e}")
            return {"status": "error", "message": str(e)}

    def retrieve_wm_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        检索工作记忆状态

        Args:
            task_id: 任务ID

        Returns:
            任务状态或None
        """
        try:
            result = self.memory_client.retrieve_wm(
                user_id=self.user_id, task_id=task_id
            )

            if result.get("status") == "success":
                state = result.get("data")
                self.logger.debug(f"Retrieved WM state for task: {task_id}")
                return state

            return None

        except Exception as e:
            self.logger.error(f"Failed to retrieve WM state: {e}")
            return None

    # ---- Working Memory (WM) long-task helpers (conversation-scoped) ----
    #
    # Policy: WM is a single long-running task per conversation.
    # - wm_id == conversation_id
    # - statuses: active | done | cancelled
    #
    # This enables "disconnect and resume": the conversation can reload WM state
    # from `wm/<conversation_id>.md` and continue progressing until done.

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def wm_id(self) -> str:
        return str(self.conversation_id)

    def retrieve_current_wm(self) -> Optional[Dict[str, Any]]:
        return self.retrieve_wm_state(self.wm_id())

    def next_wm_step(self) -> Optional[Dict[str, Any]]:
        """Return the next non-done step dict for the current WM (if any)."""
        state = self.retrieve_current_wm()
        if not isinstance(state, dict):
            return None
        if str(state.get("status") or "").strip().lower() != "active":
            return None
        steps = state.get("steps")
        if not isinstance(steps, list):
            return None
        for s in steps:
            if not isinstance(s, dict):
                continue
            st = str(s.get("status") or "todo").strip().lower()
            if st != "done":
                sid = str(s.get("id") or "").strip()
                text = str(s.get("text") or "").strip()
                if text:
                    return {"id": sid, "text": text, "status": st}
        return None

    def _normalize_steps(
        self, steps: Sequence[Dict[str, Any]] | None
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not steps:
            return out
        for i, raw in enumerate(list(steps), start=1):
            if not isinstance(raw, dict):
                continue
            sid = str(raw.get("id") or raw.get("step_id") or i).strip()
            text = str(raw.get("text") or raw.get("title") or "").strip()
            status = str(raw.get("status") or "todo").strip().lower()
            if not text:
                continue
            if status not in {"todo", "doing", "done"}:
                status = "todo"
            out.append({"id": sid, "text": text, "status": status})
        return out

    def _wm_base_state(self) -> Dict[str, Any]:
        now = self._now_iso()
        return {
            "wm_id": self.wm_id(),
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "goal": "",
            "steps": [],
            "notes": "",
        }

    def start_long_task(
        self,
        *,
        goal: str,
        steps: Sequence[Dict[str, Any]] | None = None,
        notes: str | None = None,
    ) -> Dict[str, Any]:
        goal = str(goal or "").strip()
        if not goal:
            return {"status": "error", "message": "goal is required"}

        existing = self.retrieve_current_wm()
        if isinstance(existing, dict) and str(existing.get("status") or "").strip().lower() == "active":
            return {
                "status": "error",
                "message": "wm already active for this conversation; cancel or complete it first",
                "data": existing,
            }

        state = self._wm_base_state()
        state["goal"] = goal
        state["steps"] = self._normalize_steps(steps)
        if notes:
            state["notes"] = str(notes)

        res = self.store_wm_state(self.wm_id(), state)
        if res.get("status") != "success":
            return res
        return {"status": "success", "data": state}

    def cancel_long_task(self, *, reason: str | None = None) -> Dict[str, Any]:
        existing = self.retrieve_current_wm()
        if not isinstance(existing, dict):
            return {"status": "error", "message": "no wm state found to cancel"}
        status = str(existing.get("status") or "").strip().lower()
        if status in {"done", "cancelled"}:
            return {"status": "success", "data": existing}

        existing["status"] = "cancelled"
        if reason:
            existing["cancel_reason"] = str(reason)
        now = self._now_iso()
        existing["completed_at"] = now
        existing["updated_at"] = now
        res = self.store_wm_state(self.wm_id(), existing)
        if res.get("status") != "success":
            return res
        return {"status": "success", "data": existing}

    def complete_long_task(self, *, summary: str | None = None) -> Dict[str, Any]:
        existing = self.retrieve_current_wm()
        if not isinstance(existing, dict):
            return {"status": "error", "message": "no wm state found to complete"}
        status = str(existing.get("status") or "").strip().lower()
        if status in {"done", "cancelled"}:
            return {"status": "success", "data": existing}

        existing["status"] = "done"
        if summary:
            existing["completion_summary"] = str(summary)
        now = self._now_iso()
        existing["completed_at"] = now
        existing["updated_at"] = now
        res = self.store_wm_state(self.wm_id(), existing)
        if res.get("status") != "success":
            return res
        return {"status": "success", "data": existing}

    def update_wm_step(self, *, step_id: str, status: str) -> Dict[str, Any]:
        existing = self.retrieve_current_wm()
        if not isinstance(existing, dict):
            return {"status": "error", "message": "no wm state found"}
        if str(existing.get("status") or "").strip().lower() != "active":
            return {"status": "error", "message": "wm is not active"}

        step_id = str(step_id or "").strip()
        if not step_id:
            return {"status": "error", "message": "step_id is required"}
        status = str(status or "").strip().lower()
        if status not in {"todo", "doing", "done"}:
            return {
                "status": "error",
                "message": "status must be one of: todo, doing, done",
            }

        steps = existing.get("steps")
        if not isinstance(steps, list):
            steps = []
            existing["steps"] = steps

        updated = False
        for s in steps:
            if not isinstance(s, dict):
                continue
            if str(s.get("id") or "").strip() == step_id:
                s["status"] = status
                updated = True
                break

        if not updated:
            return {"status": "error", "message": f"step_id not found: {step_id}"}

        existing["updated_at"] = self._now_iso()
        res = self.store_wm_state(self.wm_id(), existing)
        if res.get("status") != "success":
            return res
        return {"status": "success", "data": existing}

    def store_ltm_preference(self, key: str, value: Any) -> Dict[str, Any]:
        """
        存储长期偏好

        Args:
            key: 偏好键
            value: 偏好值

        Returns:
            存储结果
        """
        try:
            result = self.memory_client.store_ltm_preference(
                user_id=self.user_id, key=key, value=value
            )

            self.logger.debug(f"Stored LTM preference: {key}")

            return result

        except Exception as e:
            self.logger.error(f"Failed to store LTM preference: {e}")
            return {"status": "error", "message": str(e)}

    def retrieve_ltm_preference(self, key: str) -> Optional[Any]:
        """
        检索长期偏好

        Args:
            key: 偏好键

        Returns:
            偏好值或None
        """
        try:
            result = self.memory_client.retrieve_ltm_preference(
                user_id=self.user_id, key=key
            )

            if result.get("status") == "success":
                value = result.get("data")
                self.logger.debug(f"Retrieved LTM preference: {key}")
                return value

            return None

        except Exception as e:
            self.logger.error(f"Failed to retrieve LTM preference: {e}")
            return None

    def list_ltm_preferences(self, limit: int = 50) -> Dict[str, Any]:
        """列出当前用户的全部长期偏好（按 key 去重，取最新值）。"""
        try:
            result = self.memory_client.list_ltm_preferences(
                user_id=self.user_id, limit=limit
            )
            if result.get("status") == "success":
                data = result.get("data")
                return data if isinstance(data, dict) else {}
            return {}
        except Exception as e:
            self.logger.error(f"Failed to list LTM preferences: {e}")
            return {}

    def retrieve_semantic_memories(
        self, query: str, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        检索语义记忆

        Args:
            query: 查询文本
            top_k: 返回前k条

        Returns:
            语义记忆列表
        """
        try:
            k = top_k or self.semantic_top_k
            result = self.memory_client.memory_search(
                query=query,
                top_k=k,
                tiers=["semantic"],
                scopes=["project"],
            )

            if result.get("status") == "success":
                data = result.get("data", {})
                memories = data.get("hits", []) if isinstance(data, dict) else []
                self.logger.debug(f"Retrieved {len(memories)} semantic memories")
                return memories

            return []

        except Exception as e:
            self.logger.error(f"Failed to retrieve semantic memories: {e}")
            return []
