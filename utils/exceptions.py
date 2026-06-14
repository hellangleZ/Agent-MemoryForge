"""
统一异常类定义
提供结构化的错误类型，便于错误处理和调试
"""

from typing import Optional, Any


class AgentMemoryError(Exception):
    """
    Agent记忆系统基础异常类

    所有自定义异常的基类，提供统一的错误信息格式
    """

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        """
        初始化异常

        Args:
            message: 错误消息
            error_code: 可选的错误代码
            details: 可选的错误详情字典
        """
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "error_code": self.error_code,
            "details": self.details,
        }


class MemoryServiceError(AgentMemoryError):
    """Memory服务错误"""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(
            message, error_code=f"MEM_{status_code or 'ERR'}", details=details
        )
        self.status_code = status_code


class EmbeddingServiceError(AgentMemoryError):
    """Embedding服务错误"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, error_code="EMBED_ERR", details=details)


class LLMClientError(AgentMemoryError):
    """LLM客户端错误"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, error_code="LLM_ERR", details=details)


class SkillExecutionError(AgentMemoryError):
    """技能执行错误"""

    def __init__(self, skill_name: str, message: str, details: Optional[dict] = None):
        super().__init__(message, error_code="SKILL_ERR", details=details)
        self.skill_name = skill_name


class ConfigError(AgentMemoryError):
    """配置错误"""

    def __init__(self, message: str, config_key: Optional[str] = None):
        details = {"config_key": config_key} if config_key else {}
        super().__init__(message, error_code="CONFIG_ERR", details=details)


class ValidationError(AgentMemoryError):
    """数据验证错误"""

    def __init__(self, message: str, field: Optional[str] = None):
        details = {"field": field} if field else {}
        super().__init__(message, error_code="VALIDATION_ERR", details=details)


class StorageError(AgentMemoryError):
    """存储后端错误"""

    def __init__(
        self,
        message: str,
        storage_type: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        all_details = {"storage_type": storage_type} if storage_type else {}
        all_details.update(details or {})
        super().__init__(message, error_code="STORAGE_ERR", details=all_details)


class RetryExhaustedError(AgentMemoryError):
    """重试次数耗尽错误"""

    def __init__(
        self, message: str, attempts: int, last_error: Optional[Exception] = None
    ):
        details = {
            "attempts": attempts,
            "last_error": str(last_error) if last_error else None,
        }
        super().__init__(message, error_code="RETRY_ERR", details=details)
        self.attempts = attempts
        self.last_error = last_error


# 错误处理工具函数
def format_error(error: Exception) -> str:
    """
    格式化错误信息为可读字符串

    Args:
        error: 异常实例

    Returns:
        格式化的错误字符串
    """
    if isinstance(error, AgentMemoryError):
        parts = [f"[{error.error_code}] {error.message}"]
        if error.details:
            details_str = ", ".join(f"{k}={v}" for k, v in error.details.items())
            parts.append(f"({details_str})")
        return " ".join(parts)
    else:
        return f"{error.__class__.__name__}: {str(error)}"


def handle_error(
    error: Exception, logger, reraise: bool = False, default_return: Any = None
) -> Any:
    """
    统一错误处理函数

    Args:
        error: 捕获的异常
        logger: Logger实例
        reraise: 是否重新抛出异常
        default_return: 默认返回值（当reraise=False时）

    Returns:
        default_return或None
    """
    error_message = format_error(error)

    if isinstance(error, AgentMemoryError):
        logger.error(f"Structured error: {error_message}", exc_info=True)
    else:
        logger.error(f"Unexpected error: {error_message}", exc_info=True)

    if reraise:
        raise error

    return default_return
