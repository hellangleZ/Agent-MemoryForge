"""
ToolRegistry 测试（ToolRegistry 现位于 SDK：agent_memory_framework.tools）。
"""

import pytest
from agent_memory_framework.tools import ToolRegistry


class TestToolRegistry:
    """测试工具注册表"""

    def test_init(self):
        """测试初始化"""
        registry = ToolRegistry()

        assert len(registry.tools) == 0

    def test_register_tool(self):
        """测试注册工具"""
        registry = ToolRegistry()

        def dummy_func():
            return "test"

        schema = {"name": "dummy", "description": "Dummy function", "parameters": {}}

        registry.register("dummy", dummy_func, schema)

        assert "dummy" in registry.tools

    def test_register_with_category(self):
        """测试带分类的注册"""
        registry = ToolRegistry()

        def dummy_func():
            return "test"

        registry.register("dummy", dummy_func, {}, category="test")

        assert registry.tools["dummy"]["category"] == "test"

    def test_get_tool(self):
        """测试获取工具"""
        registry = ToolRegistry()

        def dummy_func():
            return "test"

        registry.register("dummy", dummy_func, {})

        func = registry.get("dummy")

        assert func is not None
        assert func() == "test"

    def test_get_nonexistent_tool(self):
        """测试获取不存在的工具"""
        registry = ToolRegistry()

        func = registry.get("nonexistent")

        assert func is None

    def test_get_schema(self):
        """测试获取schema"""
        registry = ToolRegistry()

        schema = {"name": "dummy", "description": "Test"}

        registry.register("dummy", lambda: None, schema)

        retrieved_schema = registry.get_schema("dummy")

        assert retrieved_schema == schema

    def test_list_tools(self):
        """测试列出所有工具"""
        registry = ToolRegistry()

        registry.register("tool1", lambda: None, {"name": "tool1"}, category="cat1")
        registry.register("tool2", lambda: None, {"name": "tool2"}, category="cat2")
        registry.register("tool3", lambda: None, {"name": "tool3"}, category="cat1")

        # 获取所有工具
        all_tools = registry.list_tools()
        assert len(all_tools) == 3

        # 按分类过滤
        cat1_tools = registry.list_tools(category="cat1")
        assert len(cat1_tools) == 2

        cat2_tools = registry.list_tools(category="cat2")
        assert len(cat2_tools) == 1

    def test_execute_tool(self):
        """测试执行工具"""
        registry = ToolRegistry()

        def dummy_func(x, y):
            return x + y

        registry.register("add", dummy_func, {})

        result = registry.execute("add", x=1, y=2)

        assert result == 3

    def test_execute_nonexistent_tool(self):
        """测试执行不存在的工具"""
        from utils.exceptions import LLMClientError

        registry = ToolRegistry()

        with pytest.raises(LLMClientError):
            registry.execute("nonexistent")

    def test_execute_tool_with_error(self):
        """测试执行出错"""
        from utils.exceptions import LLMClientError

        registry = ToolRegistry()

        def error_func():
            raise ValueError("Test error")

        registry.register("error", error_func, {})

        with pytest.raises(LLMClientError):
            registry.execute("error")
