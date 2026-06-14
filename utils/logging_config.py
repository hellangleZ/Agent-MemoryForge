"""
统一日志配置模块
提供结构化、可配置的日志系统，替代emoji和print调试输出
"""

import logging
import sys
from typing import Optional
from pathlib import Path


def setup_logger(
    name: str,
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    format_string: Optional[str] = None,
) -> logging.Logger:
    """
    统一配置logger

    Args:
        name: Logger名称
        level: 日志级别 (default: INFO)
        log_file: 可选的日志文件路径
        format_string: 可选的自定义格式字符串

    Returns:
        配置好的logger实例

    Example:
        >>> logger = setup_logger("my_module")
        >>> logger.info("Processing started")
        >>> logger.error("An error occurred", exc_info=True)
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重复添加handler
    if logger.handlers:
        return logger

    # 默认格式：时间戳 - 名称 - 级别 - 消息
    if format_string is None:
        format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    formatter = logging.Formatter(format_string, datefmt="%Y-%m-%d %H:%M:%S")

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    logger.addHandler(console_handler)

    # 文件输出（可选）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    获取已配置的logger（如果不存在则使用默认配置）

    Args:
        name: Logger名称

    Returns:
        Logger实例
    """
    logger = logging.getLogger(name)

    # 如果还没有handlers，使用默认配置
    if not logger.handlers:
        return setup_logger(name)

    return logger


class LoggerContext:
    """
    Logger上下文管理器，用于临时修改日志级别
    """

    def __init__(self, logger: logging.Logger, level: int):
        self.logger = logger
        self.original_level = logger.level
        self.new_level = level

    def __enter__(self):
        self.logger.setLevel(self.new_level)
        return self.logger

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logger.setLevel(self.original_level)


# 预定义的logger实例
def get_module_logger(module_name: str) -> logging.Logger:
    """
    为模块创建标准logger

    Args:
        module_name: 模块名称（通常是__name__）

    Returns:
        配置好的logger
    """
    return get_logger(module_name)
