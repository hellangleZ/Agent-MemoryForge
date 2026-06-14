"""
异常类测试
"""

import pytest
from unittest.mock import MagicMock
from utils.exceptions import (
    AgentMemoryError,
    MemoryServiceError,
    EmbeddingServiceError,
    LLMClientError,
    SkillExecutionError,
    ConfigError,
    ValidationError,
    StorageError,
    RetryExhaustedError,
    format_error,
    handle_error,
)


class TestAgentMemoryError:
    """测试基础异常"""

    def test_basic_error(self):
        """测试基本异常"""
        error = AgentMemoryError("Test error")

        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.error_code is None
        assert error.details == {}

    def test_error_with_code(self):
        """测试带错误代码的异常"""
        error = AgentMemoryError("Test error", error_code="TEST_001")

        assert error.error_code == "TEST_001"

    def test_error_with_details(self):
        """测试带详情的异常"""
        details = {"field": "test", "value": 123}
        error = AgentMemoryError("Test error", details=details)

        assert error.details == details

    def test_to_dict(self):
        """测试转换为字典"""
        error = AgentMemoryError(
            "Test error", error_code="TEST_001", details={"key": "value"}
        )

        error_dict = error.to_dict()

        assert error_dict["error_type"] == "AgentMemoryError"
        assert error_dict["message"] == "Test error"
        assert error_dict["error_code"] == "TEST_001"
        assert error_dict["details"] == {"key": "value"}


class TestSpecificErrors:
    """测试特定异常类型"""

    def test_memory_service_error(self):
        """测试Memory服务错误"""
        error = MemoryServiceError("Connection failed", status_code=503)

        assert error.message == "Connection failed"
        assert error.status_code == 503
        assert error.error_code == "MEM_503"

    def test_embedding_service_error(self):
        """测试Embedding服务错误"""
        error = EmbeddingServiceError("Model not found")

        assert error.error_code == "EMBED_ERR"

    def test_llm_client_error(self):
        """测试LLM客户端错误"""
        error = LLMClientError("API timeout")

        assert error.error_code == "LLM_ERR"

    def test_skill_execution_error(self):
        """测试技能执行错误"""
        error = SkillExecutionError("test_skill", "Execution failed")

        assert error.skill_name == "test_skill"
        assert error.error_code == "SKILL_ERR"

    def test_config_error(self):
        """测试配置错误"""
        error = ConfigError("Invalid config", config_key="test.key")

        assert error.details["config_key"] == "test.key"
        assert error.error_code == "CONFIG_ERR"

    def test_validation_error(self):
        """测试验证错误"""
        error = ValidationError("Invalid field", field="email")

        assert error.details["field"] == "email"
        assert error.error_code == "VALIDATION_ERR"

    def test_storage_error(self):
        """测试存储错误"""
        error = StorageError("Disk full", storage_type="SQLite")

        assert error.details["storage_type"] == "SQLite"
        assert error.error_code == "STORAGE_ERR"

    def test_retry_exhausted_error(self):
        """测试重试耗尽错误"""
        original_error = Exception("Connection timeout")
        error = RetryExhaustedError(
            "Retries exhausted", attempts=5, last_error=original_error
        )

        assert error.attempts == 5
        assert error.last_error == original_error
        assert error.details["attempts"] == 5


class TestErrorFunctions:
    """测试错误处理函数"""

    def test_format_agent_memory_error(self):
        """测试格式化AgentMemoryError"""
        error = AgentMemoryError(
            "Test error", error_code="TEST_001", details={"key": "value"}
        )

        formatted = format_error(error)

        assert "[TEST_001]" in formatted
        assert "Test error" in formatted
        assert "key=value" in formatted

    def test_format_standard_error(self):
        """测试格式化标准异常"""
        error = ValueError("Invalid value")

        formatted = format_error(error)

        assert "ValueError" in formatted
        assert "Invalid value" in formatted

    def test_handle_error_no_reraise(self):
        """测试不重新抛出"""
        error = Exception("Test error")
        logger = MagicMock()

        result = handle_error(error, logger, reraise=False, default_return="default")

        assert result == "default"

    def test_handle_error_reraise(self):
        """测试重新抛出"""
        error = ValueError("Test error")
        logger = MagicMock()

        with pytest.raises(ValueError):
            handle_error(error, logger, reraise=True)
