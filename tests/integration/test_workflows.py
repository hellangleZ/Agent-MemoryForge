# -*- coding: utf-8 -*-
"""集成测试 - 跨组件工作流（验证真实行为，而非常量字面量）。"""


class TestMemoryWorkflow:
    """记忆相关辅助组件的端到端行为。"""

    def test_redis_helper_roundtrips_nested_data(self):
        """序列化->反序列化必须无损还原嵌套结构。"""
        from utils.redis_helper import RedisHelper

        data = {
            "string": "test",
            "number": 42,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
        }
        assert RedisHelper.deserialize(RedisHelper.serialize(data)) == data

    def test_memory_policy_applies_overrides_and_defaults(self):
        """MemoryPolicy.from_config 应消费传入配置，缺失项回落到默认。
        这验证"配置真的被组件使用"，而非只断言常量字面量。
        """
        from agent_memory_framework.memory_runtime.policies import MemoryPolicy

        policy = MemoryPolicy.from_config({"stm_max_summaries": 7, "wm_max_size": 99})
        # 传入的被采用
        assert policy.stm_max_summaries == 7
        assert policy.wm_max_size == 99
        # 未传入的回落默认
        assert policy.stm_ttl_s == MemoryPolicy.stm_ttl_s
        assert policy.semantic_top_k == MemoryPolicy.semantic_top_k

    def test_memory_policy_reads_stm_ttl_alias(self):
        """from_config 用的是 `stm_ttl` 键（而非 `stm_ttl_s`）——回归保护这个易错别名。"""
        from agent_memory_framework.memory_runtime.policies import MemoryPolicy

        assert MemoryPolicy.from_config({"stm_ttl": 60}).stm_ttl_s == 60
        # 错误的键名不应生效（仍取默认）
        assert MemoryPolicy.from_config({"stm_ttl_s": 60}).stm_ttl_s != 60


class TestMCPToolInterfaceWorkflow:
    """MCP 工具的真实计算逻辑（直接调用，避免脆弱的子进程依赖）。"""

    def test_calculate_budget_math_and_breakdown(self):
        from agent_memory_mcp_server import calculate_budget

        out = calculate_budget("5天", hotel_level="4star")
        assert out["success"] is True
        b = out["breakdown"]
        assert b["days"] == 5
        # 酒店: 500/晚 * 5 = 2500; 餐: 300*5=1500; 机票1200; 交通200
        assert b["hotel_cost"] == 2500
        assert b["meal_cost"] == 1500
        assert b["total"] == 1200 + 2500 + 1500 + 200

    def test_calculate_budget_rejects_empty(self):
        from agent_memory_mcp_server import calculate_budget

        out = calculate_budget("")
        assert out["success"] is False

    def test_calculate_budget_unknown_hotel_falls_back(self):
        from agent_memory_mcp_server import calculate_budget

        # 未知档位回落到 5star 的 800/晚
        out = calculate_budget("2 days", hotel_level="7star")
        assert out["breakdown"]["hotel_cost"] == 800 * 2


class TestLoggerWorkflow:
    """日志系统配置。"""

    def test_logger_writes_to_file(self, tmp_path):
        from utils.logger import setup_logging

        log_file = tmp_path / "test.log"
        logger = setup_logging(name="test_logger", level="INFO", log_file=str(log_file))
        logger.info("hello")
        logger.warning("warn")

        for handler in logger.handlers:
            handler.flush()

        assert log_file.exists()
        assert "hello" in log_file.read_text(encoding="utf-8")

    def test_get_logger_same_name_same_instance(self):
        from utils.logger import get_logger

        assert get_logger("test_module") is get_logger("test_module")
