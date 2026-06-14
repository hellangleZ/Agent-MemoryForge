"""
记忆管理器集成测试
"""

from unittest.mock import MagicMock
from agent_memory_framework.memory_runtime.memory_manager import MemoryManager
from agent_memory_lib import MemoryClient


class TestMemoryManager:
    """测试MemoryManager"""

    def test_init(self):
        """测试初始化"""
        mock_client = MagicMock(spec=MemoryClient)
        manager = MemoryManager(memory_client=mock_client, user_id="test_user")

        assert manager.user_id == "test_user"
        assert manager.memory_client == mock_client

    def test_sync_conversation_to_stm(self):
        """同步到 STM 时应把 conversation_id/round_id/summary 正确转发给 client"""
        mock_client = MagicMock(spec=MemoryClient)
        mock_client.store_stm.return_value = {
            "status": "success",
            "data": {"round_id": 1},
        }

        manager = MemoryManager(
            memory_client=mock_client, user_id="test_user", conversation_id="conv_x"
        )

        result = manager.sync_conversation_to_stm(
            round_id=7, messages=[], summary="Test summary"
        )

        assert result["status"] == "success"
        # 验证转发的实参，而非仅"被调用过"
        mock_client.store_stm.assert_called_once_with(
            conversation_id="conv_x", round_id=7, summary="Test summary"
        )

    def test_sync_stm_error_handling(self):
        """测试STM同步错误处理"""
        mock_client = MagicMock(spec=MemoryClient)
        mock_client.store_stm.side_effect = Exception("Connection error")

        manager = MemoryManager(memory_client=mock_client, user_id="test_user")

        result = manager.sync_conversation_to_stm(
            round_id=1, messages=[], summary="Test summary"
        )

        assert result["status"] == "error"

    def test_retrieve_stm_summaries(self):
        """测试检索STM摘要"""
        mock_client = MagicMock(spec=MemoryClient)
        mock_client.retrieve_stm.return_value = {
            "status": "success",
            "data": [
                {"round_id": 1, "summary": "Summary 1"},
                {"round_id": 2, "summary": "Summary 2"},
            ],
        }

        manager = MemoryManager(memory_client=mock_client, user_id="test_user")

        summaries = manager.retrieve_stm_summaries()

        assert len(summaries) == 2
        assert summaries[0]["summary"] == "Summary 1"

    def test_store_wm_state(self):
        """存储工作记忆时应把 user_id/task_id/state/ttl 正确转发给 client"""
        mock_client = MagicMock(spec=MemoryClient)
        mock_client.store_wm.return_value = {"status": "success"}

        manager = MemoryManager(memory_client=mock_client, user_id="test_user")

        result = manager.store_wm_state(
            task_id="task_1", state={"status": "in_progress"}
        )

        assert result["status"] == "success"
        _, kwargs = mock_client.store_wm.call_args
        assert kwargs["user_id"] == "test_user"
        assert kwargs["task_id"] == "task_1"
        assert kwargs["state"] == {"status": "in_progress"}

    def test_wm_long_task_cancelled_terminal(self):
        """cancelled 是终态：后续 complete 不应把 cancelled 改回 done"""
        mock_client = MagicMock(spec=MemoryClient)
        mock_client.store_wm.return_value = {"status": "success"}
        # Existing active WM
        mock_client.retrieve_wm.return_value = {
            "status": "success",
            "data": {"status": "active", "goal": "g", "steps": []},
        }

        manager = MemoryManager(
            memory_client=mock_client, user_id="test_user", conversation_id="conv1"
        )
        cancelled = manager.cancel_long_task(reason="user")
        assert cancelled["status"] == "success"
        assert cancelled["data"]["status"] == "cancelled"

        # Completing after cancelled should keep cancelled.
        mock_client.retrieve_wm.return_value = {"status": "success", "data": cancelled["data"]}
        completed = manager.complete_long_task(summary="x")
        assert completed["status"] == "success"
        assert completed["data"]["status"] == "cancelled"

    def test_retrieve_wm_state(self):
        """测试检索工作记忆"""
        mock_client = MagicMock(spec=MemoryClient)
        mock_client.retrieve_wm.return_value = {
            "status": "success",
            "data": {"status": "completed"},
        }

        manager = MemoryManager(memory_client=mock_client, user_id="test_user")

        state = manager.retrieve_wm_state("task_1")

        assert state is not None
        assert state["status"] == "completed"

    def test_store_ltm_preference(self):
        """测试存储长期偏好"""
        mock_client = MagicMock(spec=MemoryClient)
        mock_client.store_ltm_preference.return_value = {"status": "success"}

        manager = MemoryManager(memory_client=mock_client, user_id="test_user")

        result = manager.store_ltm_preference(key="management_style", value="agile")

        assert result["status"] == "success"

    def test_retrieve_ltm_preference(self):
        """测试检索长期偏好"""
        mock_client = MagicMock(spec=MemoryClient)
        mock_client.retrieve_ltm_preference.return_value = {
            "status": "success",
            "data": "agile",
        }

        manager = MemoryManager(memory_client=mock_client, user_id="test_user")

        value = manager.retrieve_ltm_preference("management_style")

        assert value == "agile"

    def test_retrieve_semantic_memories(self):
        """测试检索语义记忆"""
        mock_client = MagicMock(spec=MemoryClient)
        mock_client.memory_search.return_value = {
            "status": "success",
            "data": {
                "hits": [
                    {"content": "Best practice 1"},
                    {"content": "Best practice 2"},
                ]
            },
        }

        manager = MemoryManager(memory_client=mock_client, user_id="test_user")

        memories = manager.retrieve_semantic_memories("agile methodology", top_k=5)

        assert len(memories) == 2
        mock_client.memory_search.assert_called_once_with(
            query="agile methodology",
            top_k=5,
            tiers=["semantic"],
            scopes=["project"],
        )
