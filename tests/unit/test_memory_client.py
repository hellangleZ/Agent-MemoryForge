"""
Memory客户端测试
"""

import pytest
from unittest.mock import patch, MagicMock
import requests
import json
from agent_memory_lib.client import MemoryClient, MemoryClientBuilder
from utils.exceptions import MemoryServiceError


class TestMemoryClient:
    """测试Memory客户端"""

    @pytest.fixture
    def mock_session(self):
        """Mock session"""
        with patch("agent_memory_lib.client.requests.Session") as mock:
            session = MagicMock()
            mock.return_value = session
            yield session

    def test_init(self):
        """测试初始化"""
        client = MemoryClient("http://localhost:8001")

        assert client.base_url == "http://localhost:8001"
        assert client.timeout == 15
        assert client.max_retries == 3
        assert client.tenant_id is None
        assert client.workspace_id is None

    def test_init_custom(self):
        """测试自定义初始化"""
        client = MemoryClient(
            base_url="http://example.com:9000",
            timeout=30,
            max_retries=5,
            tenant_id="t1",
            workspace_id="ws1",
        )

        assert client.base_url == "http://example.com:9000"
        assert client.timeout == 30
        assert client.max_retries == 5
        assert client.tenant_id == "t1"
        assert client.workspace_id == "ws1"

    def test_scoping_injected(self, mock_session):
        """Default tenant/workspace scope is injected into canonical payloads."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success", "data": {}}
        mock_session.post.return_value = mock_response

        client = MemoryClient(
            "http://localhost:8001", tenant_id="t1", workspace_id="ws1"
        )
        client.memory_write(tier="semantic", scope="project", content="x")

        called_payload = mock_session.post.call_args.kwargs.get("json")
        assert called_payload["tenant_id"] == "t1"
        assert called_payload["workspace_id"] == "ws1"

    def test_actor_identity_injected(self, mock_session):
        """Actor identity is sent so the service can enforce private memory RBAC."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success", "data": {"hits": []}}
        mock_session.post.return_value = mock_response

        client = MemoryClient(
            "http://localhost:8001",
            tenant_id="t1",
            workspace_id="ws1",
            actor_user_id="alice",
            actor_role="user",
        )
        client.memory_search(query="timezone", tiers=["preferences"])

        called_payload = mock_session.post.call_args.kwargs.get("json")
        assert called_payload["actor_user_id"] == "alice"
        assert called_payload["actor_role"] == "user"

    def test_gateway_auth_headers_are_sent(self, mock_session):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success", "data": {"hits": []}}
        mock_session.post.return_value = mock_response

        client = MemoryClient(
            "https://gateway.example.com",
            tenant_id="tenant_acme",
            workspace_id="dw_ops",
            access_token="access-token",
        )
        client.memory_search(query="finance_mrr", tiers=["semantic"])

        headers = mock_session.post.call_args.kwargs.get("headers")
        assert headers["authorization"] == "Bearer access-token"
        assert headers["x-workspace-id"] == "dw_ops"

    def test_memory_write_success(self, mock_session):
        """Canonical memory_write stores memory."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success", "data": {"entry_id": "123"}}
        mock_session.post.return_value = mock_response

        client = MemoryClient("http://localhost:8001")
        result = client.memory_write(tier="semantic", scope="project", content="test")

        assert result["status"] == "success"
        assert result["data"]["entry_id"] == "123"
        assert mock_session.post.call_args.args[0] == "http://localhost:8001/v1/memory/write"

    def test_memory_write_error(self, mock_session):
        """Canonical write errors are wrapped."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {
            "status": "error",
            "message": "Internal error",
        }
        mock_session.post.return_value = mock_response
        mock_session.post.return_value.raise_for_status.side_effect = Exception("500")

        client = MemoryClient("http://localhost:8001")

        with pytest.raises(MemoryServiceError):
            client.memory_write(tier="semantic", scope="project", content="test")

    def test_memory_search_success(self, mock_session):
        """Canonical memory_search retrieves hits."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {"hits": [{"snippet": "test"}]},
        }
        mock_session.post.return_value = mock_response

        client = MemoryClient("http://localhost:8001")
        result = client.memory_search(query="test", tiers=["semantic"])

        assert result["status"] == "success"
        assert len(result["data"]["hits"]) == 1
        assert mock_session.post.call_args.args[0] == "http://localhost:8001/v1/memory/search"

    def test_zero_max_retries_still_performs_initial_request(self, mock_session):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {"hits": []},
        }
        mock_session.post.return_value = mock_response

        client = MemoryClient("http://localhost:8001", max_retries=0)
        result = client.memory_search(query="test", tiers=["semantic"])

        assert result["status"] == "success"
        mock_session.post.assert_called_once()

    def test_build_context_returns_agent_ready_messages(self, mocker):
        """SDK users can build memory context without adopting the demo agent."""
        client = MemoryClient(
            "http://localhost:8001",
            tenant_id="t1",
            workspace_id="ws1",
        )
        mocker.patch.object(
            client,
            "memory_read",
            side_effect=[
                {
                    "status": "success",
                    "data": {"timezone": "Asia/Shanghai"},
                },
                {
                    "status": "success",
                    "data": [
                        {"summary": "finance_mrr SLA is 08:30 Asia/Shanghai."}
                    ],
                },
            ],
        )
        mocker.patch.object(
            client,
            "memory_search",
            side_effect=[
                {
                    "status": "success",
                    "data": {
                        "hits": [
                            {
                                "snippet": "finance_mrr refreshes daily by 08:30 Asia/Shanghai.",
                                "path": "memory/dw.md",
                                "line": 12,
                            }
                        ]
                    },
                },
                {
                    "status": "success",
                    "data": {
                        "hits": [
                            {
                                "snippet": "finance_mrr depends on fact_orders.",
                                "path": "graph/dw.md",
                                "line": 4,
                            }
                        ]
                    },
                },
            ],
        )

        messages = client.build_context(
            query="finance_mrr freshness SLA 和上游依赖是什么？",
            user_id="u1",
            conversation_id="conv1",
            system_prompt="You are a data warehouse assistant.",
        )

        assert messages[0]["role"] == "system"
        assert "You are a data warehouse assistant." in messages[0]["content"]
        joined = "\n".join(message["content"] for message in messages)
        assert "finance_mrr refreshes daily by 08:30" in joined
        assert "finance_mrr depends on fact_orders" in joined
        assert "Asia/Shanghai" in joined

    def test_build_context_fails_open_when_memory_is_unavailable(self, mocker):
        client = MemoryClient("http://localhost:8001")
        mocker.patch.object(
            client,
            "memory_search",
            side_effect=MemoryServiceError("memory service unavailable"),
        )

        messages = client.build_context(query="hello", include_preferences=False)

        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert "Memory Use Rules" in messages[0]["content"]

    def test_build_context_zero_search_limits_skip_search(self, mocker):
        client = MemoryClient("http://localhost:8001")
        search = mocker.patch.object(client, "memory_search")

        client.build_context(
            query="hello",
            semantic_top_k=0,
            graph_top_k=0,
        )

        search.assert_not_called()

    def test_build_context_zero_preference_limit_skips_read(self, mocker):
        client = MemoryClient("http://localhost:8001")
        read = mocker.patch.object(client, "memory_read")

        client.build_context(
            query="hello",
            user_id="u1",
            preference_limit=0,
            include_semantic=False,
            include_graph=False,
        )

        read.assert_not_called()

    def test_build_context_falls_back_to_identifier_queries(self, mocker):
        client = MemoryClient("http://localhost:8001")
        mocker.patch.object(client, "memory_read", return_value={"status": "success", "data": {}})

        def search_side_effect(**kwargs):
            query = kwargs["query"]
            tier = kwargs["tiers"][0]
            if query == "finance_mrr" and tier == "semantic":
                return {
                    "status": "success",
                    "data": {
                        "hits": [
                            {
                                "snippet": "marts.finance_mrr 的刷新 SLA 是每天 08:30 Asia/Shanghai。"
                            }
                        ]
                    },
                }
            if query == "finance_mrr" and tier == "graph":
                return {
                    "status": "success",
                    "data": {
                        "hits": [
                            {
                                "snippet": "marts.finance_mrr -[depends_on]-> fact_orders"
                            }
                        ]
                    },
                }
            return {"status": "success", "data": {"hits": []}}

        search = mocker.patch.object(
            client,
            "memory_search",
            side_effect=search_side_effect,
        )

        query = (
            "我现在这个 Northstar DW Ops 里，"
            "finance_mrr 的 freshness SLA 是什么？它上游依赖什么？"
        )
        messages = client.build_context(query=query, include_preferences=False)

        content = messages[0]["content"]
        assert "08:30 Asia/Shanghai" in content
        assert "fact_orders" in content
        queries = [call.kwargs["query"] for call in search.call_args_list]
        assert "finance_mrr" in queries
        assert len(queries) <= 4

    @pytest.mark.unit
    def test_file_first_index_rebuild(self, mock_session):
        """File-first: index rebuild uses native /v1/memory/index/rebuild with injected scope."""

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"status": "success", "data": {"rebuilt": True}}
        mock_session.post.return_value = mock_response

        client = MemoryClient("http://localhost:8001", tenant_id="t1", workspace_id="ws1")
        res = client.memory_index_rebuild()

        assert res["status"] == "success"
        called_url = mock_session.post.call_args.args[0]
        assert called_url == "http://localhost:8001/v1/memory/index/rebuild"
        called_payload = mock_session.post.call_args.kwargs.get("json")
        assert called_payload["tenant_id"] == "t1"
        assert called_payload["workspace_id"] == "ws1"

    def test_store_stm(self, mock_session):
        """测试存储STM"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_session.post.return_value = mock_response

        client = MemoryClient("http://localhost:8001")
        result = client.store_stm("conv_1", 1, "Test summary")

        called_payload = mock_session.post.call_args.kwargs.get("json")
        assert mock_session.post.call_args.args[0] == "http://localhost:8001/v1/memory/write"
        assert called_payload["tier"] == "stm"
        assert called_payload["metadata"]["stm_summary"]["final_answer"] == "Test summary"
        assert result["status"] == "success"

    def test_retrieve_stm(self, mock_session):
        """测试检索STM"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": [{"round_id": 1, "summary": "Test"}],
        }
        mock_session.post.return_value = mock_response

        client = MemoryClient("http://localhost:8001")
        result = client.retrieve_stm("conv_1", 10)

        assert result["status"] == "success"
        assert len(result["data"]) == 1
        assert mock_session.post.call_args.args[0] == "http://localhost:8001/v1/memory/read"

    def test_health_check_success(self, mock_session):
        """测试健康检查成功"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_session.get.return_value = mock_response

        client = MemoryClient("http://localhost:8001")
        assert client.health_check() is True

    def test_health_check_failure(self, mock_session):
        """测试健康检查失败"""
        mock_session.get.side_effect = Exception("Connection refused")

        client = MemoryClient("http://localhost:8001")
        assert client.health_check() is False

    @pytest.mark.unit
    def test_http_error_without_response_is_wrapped(self, mock_session):
        """requests.HTTPError 有时没有 response; 客户端应安全包装"""

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("boom")
        mock_session.post.return_value = mock_response

        client = MemoryClient("http://localhost:8001")
        with pytest.raises(MemoryServiceError) as exc:
            client.memory_write(tier="semantic", scope="project", content="x")

        assert "HTTP error" in str(exc.value)

    @pytest.mark.unit
    def test_invalid_json_response_is_wrapped(self, mock_session):
        """服务端返回非 JSON 时，客户端抛出结构化 MemoryServiceError"""

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.text = "not-json"
        mock_response.json.side_effect = json.JSONDecodeError(
            "Expecting value",
            doc="not-json",
            pos=0,
        )
        mock_session.post.return_value = mock_response

        client = MemoryClient("http://localhost:8001")
        with pytest.raises(MemoryServiceError) as exc:
            client.memory_write(tier="semantic", scope="project", content="x")

        assert "Invalid JSON" in str(exc.value)

    @pytest.mark.unit
    def test_close_closes_underlying_session(self, mock_session):
        client = MemoryClient("http://localhost:8001")
        client.close()
        mock_session.close.assert_called_once()

    @pytest.mark.unit
    def test_context_manager_closes_session(self, mock_session):
        with MemoryClient("http://localhost:8001") as client:
            assert client.base_url == "http://localhost:8001"
        mock_session.close.assert_called_once()

    @pytest.mark.unit
    def test_shared_pool_mounts_shared_adapter_without_closing_it(self, mock_session):
        adapter = MagicMock()
        with patch("agent_memory_lib.client._shared_adapter_for", return_value=adapter):
            client = MemoryClient("http://localhost:8001", shared_pool=True)
            assert mock_session.mount.call_count == 2
            client.close()

        mock_session.close.assert_not_called()


class TestMemoryClientBuilder:
    """测试Memory客户端构建器"""

    def test_default_build(self):
        """测试默认构建"""
        client = MemoryClientBuilder().build()

        assert client.base_url == "http://127.0.0.1:8001"
        assert client.timeout == 15
        assert client.max_retries == 3

    def test_custom_build(self):
        """测试自定义构建"""
        client = (
            MemoryClientBuilder()
            .with_url("http://example.com:9000")
            .with_timeout(30)
            .with_retries(5)
            .build()
        )

        assert client.base_url == "http://example.com:9000"
        assert client.timeout == 30
        assert client.max_retries == 5

    def test_chain_pattern(self):
        """测试链式调用"""
        builder = MemoryClientBuilder()

        # 测试返回builder实例
        assert isinstance(builder.with_url("http://test"), MemoryClientBuilder)
        assert isinstance(builder.with_timeout(20), MemoryClientBuilder)
        assert isinstance(builder.with_retries(2), MemoryClientBuilder)
