"""
Key映射测试
"""

from agent_memory_framework.memory_runtime.key_mapping import (
    resolve_key,
    add_mapping,
    get_all_mappings,
)


class TestKeyMapping:
    """测试Key映射"""

    def test_resolve_chinese_key(self):
        """测试解析中文key"""
        assert resolve_key("管理风格") == "work_decision_making_style"
        assert resolve_key("沟通风格") == "communication_style"
        assert resolve_key("会议风格") == "meeting_time_preference"
        assert resolve_key("风险管理") == "risk_management"

    def test_resolve_english_key(self):
        """测试解析英文key"""
        assert resolve_key("management_style") == "work_decision_making_style"
        assert resolve_key("communication_style") == "communication_style"
        assert resolve_key("meeting_style") == "meeting_time_preference"
        assert resolve_key("risk_management") == "risk_management"

    def test_resolve_unknown_key(self):
        """测试未知key"""
        # 未知key应该原样返回
        assert resolve_key("unknown_key") == "unknown_key"
        assert resolve_key("random") == "random"

    def test_add_mapping(self):
        """测试添加映射"""
        # 添加新映射
        add_mapping("test_key", "db_test_key")

        assert resolve_key("test_key") == "db_test_key"

    def test_get_all_mappings(self):
        """测试获取所有映射"""
        mappings = get_all_mappings()

        assert isinstance(mappings, dict)
        assert len(mappings) > 0
        assert "管理风格" in mappings
        assert "management_style" in mappings

    def test_mapping_immutability(self):
        """测试返回的是副本"""
        mappings1 = get_all_mappings()
        mappings2 = get_all_mappings()

        # 修改mappings1不应该影响mappings2
        mappings1["new_key"] = "new_value"

        assert "new_key" not in mappings2
