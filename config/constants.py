# -*- coding: utf-8 -*-
"""
系统配置常量
统一管理所有硬编码的配置常量
"""


class MemoryConfig:
    """记忆系统配置"""

    STM_TTL_SECONDS = 1800  # 短期记忆30分钟过期
    STM_MAX_SUMMARIES = 15  # 最多保留15条历史摘要
    WM_MAX_SIZE = 20  # 工作记忆最大容量
    MAX_CONVERSATION_HISTORY = 100  # 对话历史最大条数


class LLMConfig:
    """LLM配置"""

    MAX_TOOL_TURNS = 15  # 单轮对话最多工具调用次数
    MAX_RETRIES = 3  # API调用最大重试次数
    RETRY_DELAY_BASE = 1  # 重试基础延迟(秒)
    TIMEOUT = 60  # API超时时间(秒)


class ServiceConfig:
    """服务URL配置"""

    MEMORY_SERVICE_URL = "http://127.0.0.1:8000"
    EMBEDDING_SERVICE_URL = "http://127.0.0.1:7999/v1/embeddings"
    REDIS_HOST = "localhost"
    REDIS_PORT = 6379
    NEO4J_URI = "bolt://localhost:7687"
    NEO4J_USER = "neo4j"


class UserConfig:
    """用户配置"""

    DEFAULT_USER_ID = "project_manager_alice"
    DEFAULT_AGENT_ID = "agent_project_management_assistant"


class LogConfig:
    """日志配置"""

    LOG_FILE = "project_management_demo.log"
    DEBUG_LOG_FILE = "project_management_demo_debug.log"
    LOG_LEVEL = "INFO"
    LOG_FORMAT = "%(asctime)s - %(levelname)s - [%(module)s:%(funcName)s:%(lineno)d] - %(message)s"


class MultiAgentConfig:
    """多Agent配置"""

    MAX_PARALLEL_WORKERS = 8  # 并行执行最大工作线程数
    SCOPE_IDS_CACHE_MAX = 32  # 作用域ID缓存最大数量


class RetryConfig:
    """重试配置"""

    DB_LOCK_MAX_RETRIES = 5  # 数据库锁定最大重试次数
    DB_LOCK_BASE_DELAY = 0.1  # 数据库锁定基础延迟(秒)
