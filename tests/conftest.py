# -*- coding: utf-8 -*-
"""
pytest配置和共享fixtures
"""

import sys
import os
import pytest
import tempfile
from pathlib import Path


def pytest_configure(config):
    # Speed up/avoid flaky jieba initialization during tests.
    os.environ.setdefault("AGENT_MEMORY_DISABLE_JIEBA", "1")

    # Prevent pytest-asyncio from interfering with sync tests that internally
    # use Starlette's TestClient/anyio.
    os.environ.setdefault("PYTEST_ASYNCIO_MODE", "auto")

    # Configure MCP stdio server for framework tool discovery.
    os.environ.setdefault(
        "AGENT_MEMORY_MCP_STDIO",
        '{"command":"python","args":["-m","agent_memory_mcp_server"]}',
    )

    os.environ.setdefault(
        "AGENT_MEMORY_MCP_SERVERS",
        '[{"name":"local","transport":"stdio","namespace":"local","command":"python","args":["-m","agent_memory_mcp_server"]}]',
    )


# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def test_data_dir():
    """测试数据目录"""
    data_dir = Path(__file__).parent / "fixtures"
    data_dir.mkdir(exist_ok=True)
    return data_dir


@pytest.fixture(scope="session")
def sample_embeddings():
    """示例向量数据"""
    import numpy as np

    return {
        "query_embedding": np.random.rand(1024).astype(np.float32),
        "doc_embedding": np.random.rand(1024).astype(np.float32),
    }


@pytest.fixture(scope="function")
def temp_db_file():
    """临时数据库文件"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    # 清理
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(scope="function")
def temp_vector_files():
    """临时向量索引文件"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".faiss", delete=False) as f:
        faiss_path = f.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json_path = f.name

    yield faiss_path, json_path

    # 清理
    try:
        os.unlink(faiss_path)
        os.unlink(json_path)
    except OSError:
        pass


@pytest.fixture(scope="function")
def mock_redis():
    """模拟Redis连接"""
    import fakeredis

    return fakeredis.FakeStrictRedis(decode_responses=False)


@pytest.fixture(scope="function")
def mock_neo4j_driver():
    """模拟Neo4j驱动"""
    from unittest.mock import Mock, MagicMock

    mock_driver = Mock()
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.data.return_value = []
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = Mock(return_value=mock_session)
    mock_session.__exit__ = Mock(return_value=False)
    mock_driver.session.return_value = mock_session
    return mock_driver


# 新增fixtures用于重构后的模块测试


@pytest.fixture(scope="function")
def sample_text():
    """示例文本"""
    return "项目管理需要协调团队和资源，确保项目按时完成。"


@pytest.fixture(scope="function")
def sample_keywords():
    """示例关键词"""
    return ["项目", "管理", "团队", "协调"]


@pytest.fixture(scope="function")
def sample_conversation_history():
    """示例对话历史"""
    return [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！有什么可以帮你的？"},
        {"role": "user", "content": "帮我管理项目"},
    ]


@pytest.fixture(scope="function")
def sample_stm_summaries():
    """示例STM摘要"""
    return [
        {
            "round_id": 1,
            "summary": "讨论了项目启动的相关事项",
            "timestamp": "2024-01-13 10:00:00",
        },
        {
            "round_id": 2,
            "summary": "确定了项目团队组成",
            "timestamp": "2024-01-13 11:00:00",
        },
    ]


@pytest.fixture(scope="function")
def mock_logger():
    """模拟Logger"""
    from unittest.mock import MagicMock

    logger = MagicMock()
    logger.info = MagicMock()
    logger.debug = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    return logger
