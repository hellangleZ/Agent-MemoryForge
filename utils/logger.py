# -*- coding: utf-8 -*-
"""
统一日志配置
"""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    name: str,
    level: str = "INFO",
    log_file: Optional[str] = None,
    log_format: Optional[str] = None,
) -> logging.Logger:
    """
    配置标准日志记录器

    Args:
        name: 日志记录器名称
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径（可选）
        log_format: 日志格式（可选）

    Returns:
        logging.Logger: 配置好的日志记录器
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # 清除已有的处理器
    logger.handlers.clear()

    # 默认格式
    if log_format is None:
        log_format = "%(asctime)s - %(levelname)s - [%(name)s:%(funcName)s:%(lineno)d] - %(message)s"

    formatter = logging.Formatter(log_format)

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件处理器（如果指定）
    if log_file:
        # 确保目录存在
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_handler.setLevel(getattr(logging, level.upper()))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    获取日志记录器（如果不存在则创建）

    Args:
        name: 日志记录器名称

    Returns:
        logging.Logger: 日志记录器
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        # 如果没有处理器，使用默认配置
        logger = setup_logging(name)
    return logger


# 日志级别使用指南
"""
日志级别使用指南：

DEBUG: 详细调试信息
- 用于开发和故障排查
- 记录函数调用参数、中间变量等
- 示例：logger.debug(f"处理参数: {params}")

INFO: 一般信息
- 正常运行时的信息
- 记录关键操作步骤
- 示例：logger.info(f"成功加载 {count} 条数据")

WARNING: 警告信息
- 潜在问题，但不影响运行
- 需要注意但不立即处理
- 示例：logger.warning(f"配置文件不存在，使用默认值")

ERROR: 错误信息
- 影响功能但可恢复的错误
- 需要关注的异常
- 示例：logger.error(f"API调用失败: {e}")

CRITICAL: 严重错误
- 导致服务不可用的错误
- 需要立即处理
- 示例：logger.critical(f"数据库连接失败，服务终止")
"""
