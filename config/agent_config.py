"""
Agent配置管理
集中管理所有Agent相关的配置，支持从环境变量读取
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentConfig:
    """Agent配置类

    集中管理所有Agent的配置项，支持从环境变量读取，
    避免硬编码，提高灵活性和可维护性。
    """

    # ========== 服务端点配置 ==========
    memory_service_url: str
    user_id: str
    agent_id: str
    mcp_tools_enabled: bool = True

    # ========== Azure OpenAI配置 ==========
    azure_api_key: Optional[str] = None
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None

    # ========== 记忆系统配置 ==========
    # STM配置
    stm_max_rounds: int = 15
    stm_cache_ttl: int = 60  # 缓存60秒

    # WM配置
    wm_capacity: int = 20  # 工作记忆最大容量

    # Embedding服务配置
    embedding_service_url: str = "http://127.0.0.1:7999/v1/embeddings"
    embedding_model_name: str = "qwen3-embedding-0___6b"

    # Embedding provider selection
    # - local: call EMBEDDING_SERVICE_URL (FastAPI ONNX embedding service)
    # - azure: call Azure OpenAI-compatible embeddings endpoint (/openai/v1)
    embedding_provider: str = "local"
    azure_embedding_base_url: Optional[str] = None
    azure_embedding_api_key: Optional[str] = None
    azure_embedding_deployment: Optional[str] = None

    # ========== Neo4j配置 ==========
    neo4j_uri: Optional[str] = None
    neo4j_user: Optional[str] = None
    neo4j_password: Optional[str] = None

    # ========== Redis配置 ==========
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # ========== 对话配置 ==========
    max_working_memory: int = 20  # 最大工作记忆容量
    max_conversation_history: int = 20  # 最大对话历史长度

    # ========== 性能配置 ==========
    stm_sync_max_retries: int = 3  # STM同步最大重试次数
    stm_sync_retry_delay: float = 0.5  # STM同步重试延迟（秒）

    @classmethod
    def from_env(cls) -> "AgentConfig":
        """从环境变量加载配置

        如果环境变量未设置，使用默认值。
        这样可以在不同环境（开发、测试、生产）中使用不同的配置。
        """
        return cls(
            # 服务端点配置（必需）
            memory_service_url=os.getenv(
                "MEMORY_SERVICE_URL",
                "http://127.0.0.1:8001"
            ),
            user_id=os.getenv(
                "USER_ID",
                "project_manager_alice"
            ),
            agent_id=os.getenv(
                "AGENT_ID",
                "agent_project_management_assistant"
            ),
            mcp_tools_enabled=os.getenv("MCP_TOOLS_ENABLED", "1").strip().lower() in {
                "1",
                "true",
                "yes",
                "y",
                "on",
            },

            # Azure OpenAI配置（可选）
            azure_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),

            embedding_service_url=os.getenv(
                "EMBEDDING_SERVICE_URL",
                "http://127.0.0.1:7999/v1/embeddings"
            ),
            embedding_model_name=os.getenv(
                "EMBEDDING_MODEL_NAME",
                "qwen3-embedding-0___6b"
            ),

            embedding_provider=os.getenv("EMBEDDING_PROVIDER", "local").strip().lower() or "local",
            azure_embedding_base_url=os.getenv("AZURE_EMBEDDING_BASE_URL"),
            azure_embedding_api_key=os.getenv("AZURE_EMBEDDING_API_KEY"),
            azure_embedding_deployment=os.getenv("AZURE_EMBEDDING_DEPLOYMENT"),

            # Neo4j配置（可选）
            neo4j_uri=os.getenv("NEO4J_URI"),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),

            # Redis配置
            redis_host=os.getenv("REDIS_HOST", "localhost"),
            redis_port=int(os.getenv("REDIS_PORT", "6379")),
            redis_db=int(os.getenv("REDIS_DB", "0")),
        )

    def validate(self) -> bool:
        """验证配置是否完整

        Returns:
            bool: 配置是否有效
        """
        errors = []

        # 检查必需的配置项
        if not self.memory_service_url:
            errors.append("memory_service_url不能为空")

        if not self.user_id:
            errors.append("user_id不能为空")

        if not self.agent_id:
            errors.append("agent_id不能为空")

        if errors:
            print("❌ 配置验证失败:")
            for error in errors:
                print(f"   - {error}")
            return False

        return True

    def get_azure_config(self) -> dict:
        """获取Azure OpenAI配置

        Returns:
            dict: Azure配置字典，用于初始化Azure客户端

        Raises:
            ValueError: 如果Azure配置不完整
        """
        if not all([self.azure_api_key, self.azure_endpoint, self.azure_deployment]):
            raise ValueError(
                "❌ Azure OpenAI配置不完整。请设置以下环境变量:\n"
                "   - AZURE_OPENAI_API_KEY\n"
                "   - AZURE_OPENAI_ENDPOINT\n"
                "   - AZURE_OPENAI_DEPLOYMENT"
            )

        return {
            "api_key": self.azure_api_key,
            "base_url": self.azure_endpoint,
            "model": self.azure_deployment,
        }

    def __str__(self) -> str:
        """打印配置摘要"""
        return f"""Agent配置:
  服务端点:
    - Memory Service: {self.memory_service_url}
    - User ID: {self.user_id}
    - Agent ID: {self.agent_id}
    - MCP Tools Enabled: {self.mcp_tools_enabled}

  记忆系统:
    - STM Max Rounds: {self.stm_max_rounds}
    - WM Capacity: {self.wm_capacity}
    - Embedding Model: {self.embedding_model_name}
    - Embedding Provider: {self.embedding_provider}

  性能:
    - STM Cache TTL: {self.stm_cache_ttl}s
"""


# 创建全局配置实例
_global_config: Optional[AgentConfig] = None


def get_config() -> AgentConfig:
    """获取全局配置实例（单例模式）

    Returns:
        AgentConfig: 全局配置实例
    """
    global _global_config
    if _global_config is None:
        _global_config = AgentConfig.from_env()
        _global_config.validate()
    return _global_config


def reload_config() -> AgentConfig:
    """重新加载配置（从环境变量）

    用于在运行时重新加载配置，例如配置文件更新后。

    Returns:
        AgentConfig: 新的配置实例
    """
    global _global_config
    _global_config = AgentConfig.from_env()
    _global_config.validate()
    return _global_config
