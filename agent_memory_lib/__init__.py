"""
Agent-MemoryForge SDK library

提供可复用的记忆系统组件，包括：
- 文本处理工具
- Memory服务客户端SDK
- 配置管理

这个库可以独立于Demo代码使用
"""

from .text_processing import (
    TextProcessor,
    estimate_tokens,
    extract_keywords,
    calculate_relevance,
)
from .client import MemoryClient, MemoryClientBuilder

__version__ = "2.0.0"

__all__ = [
    # Text processing
    "TextProcessor",
    "estimate_tokens",
    "extract_keywords",
    "calculate_relevance",
    # Client SDK
    "MemoryClient",
    "MemoryClientBuilder",
]
