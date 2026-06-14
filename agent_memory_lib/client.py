"""
Memory服务客户端SDK
提供类型安全的Memory服务访问接口
"""

import os
import re
import threading
import time
from urllib.parse import urlsplit

import requests
from typing import Any, Dict, List, Optional
from utils.logging_config import get_logger
from utils.exceptions import MemoryServiceError

logger = get_logger(__name__)
_ADAPTER_LOCK = threading.Lock()
_SHARED_ADAPTERS: Dict[str, requests.adapters.HTTPAdapter] = {}
SDK_MEMORY_CONTEXT_RULES = """## Memory Use Rules
- Use the memory context as supporting evidence for the next answer.
- Prefer the user's current message if it conflicts with memory.
- Do not expose internal memory identifiers or storage details unless the user asks for sources.
"""
_NON_IDEMPOTENT_POST_ENDPOINTS = {"v1/memory/write"}


def _clean_context_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<!--\s*am:entry\b.*?-->", "", text, flags=re.DOTALL)
    if "-->" in text:
        text = text.rsplit("-->", 1)[-1]
    if "-[" not in text:
        text = text.replace("[", "").replace("]", "")
    text = re.sub(r"\s+", " ", text).strip()
    if re.search(
        r'"(?:created_at|entry_id|memory_kind|source|tenant_id|workspace_id|score)"\s*:',
        text,
    ):
        return ""
    return text.strip(" …")


def _hit_context_text(hit: Dict[str, Any]) -> str:
    metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
    subject = str(metadata.get("subject") or "").strip()
    relation = str(metadata.get("relation") or "").strip()
    obj = str(metadata.get("obj") or "").strip()
    if subject and relation and obj:
        return f"{subject} -[{relation}]-> {obj}"
    return _clean_context_text(
        hit.get("snippet") or hit.get("content") or hit.get("text")
    )


def _shared_adapter_for(base_url: str) -> requests.adapters.HTTPAdapter:
    parsed = urlsplit(str(base_url or ""))
    key = parsed.scheme or "http"
    with _ADAPTER_LOCK:
        adapter = _SHARED_ADAPTERS.get(key)
        if adapter is None:
            try:
                pool_connections = int(os.getenv("MEMORY_CLIENT_POOL_CONNECTIONS") or "32")
                pool_maxsize = int(os.getenv("MEMORY_CLIENT_POOL_MAXSIZE") or "128")
            except Exception:
                pool_connections = 32
                pool_maxsize = 128
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=max(1, pool_connections),
                pool_maxsize=max(1, pool_maxsize),
                pool_block=True,
            )
            _SHARED_ADAPTERS[key] = adapter
        return adapter


class MemoryClient:
    """
    Memory服务客户端

    提供类型安全的API来访问Memory服务的存储和检索功能
    """

    def __init__(
        self,
        base_url: str,
        timeout: int = 15,
        max_retries: int = 3,
        tenant_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        shared_pool: bool = False,
        api_key: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        actor_role: Optional[str] = None,
        access_token: Optional[str] = None,
    ):
        """
        初始化Memory客户端

        Args:
            base_url: Memory服务的基础URL
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.tenant_id = tenant_id
        self.workspace_id = workspace_id
        self.shared_pool = bool(shared_pool)
        self.actor_user_id = actor_user_id
        self.actor_role = actor_role
        self.api_key = (
            api_key
            or os.getenv("MEMORY_SERVICE_API_KEY")
            or os.getenv("AGENT_MEMORY_SERVICE_API_KEY")
        )
        self.access_token = access_token or os.getenv("AGENT_MEMORY_GATEWAY_ACCESS_TOKEN")
        self.session = requests.Session()
        if self.shared_pool:
            adapter = _shared_adapter_for(self.base_url)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)
        logger.info(f"MemoryClient initialized: {self.base_url}")

    def with_scope(self, *, tenant_id: str, workspace_id: str) -> "MemoryClient":
        """Return a shallow clone of this client with default tenant/workspace scope."""

        return MemoryClient(
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=self.max_retries,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            shared_pool=self.shared_pool,
            api_key=self.api_key,
            actor_user_id=self.actor_user_id,
            actor_role=self.actor_role,
            access_token=self.access_token,
        )

    def clone(
        self,
        *,
        tenant_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        actor_role: Optional[str] = None,
    ) -> "MemoryClient":
        """Return a shallow clone of this client.

        This is primarily used to avoid sharing a single `requests.Session`
        across threads.
        """

        return MemoryClient(
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=self.max_retries,
            tenant_id=self.tenant_id if tenant_id is None else tenant_id,
            workspace_id=self.workspace_id if workspace_id is None else workspace_id,
            shared_pool=self.shared_pool,
            api_key=self.api_key,
            actor_user_id=self.actor_user_id if actor_user_id is None else actor_user_id,
            actor_role=self.actor_role if actor_role is None else actor_role,
            access_token=self.access_token,
        )

    def with_actor(
        self, *, actor_user_id: str, actor_role: str = "user"
    ) -> "MemoryClient":
        """Return a scoped clone that carries caller identity for server-side RBAC."""

        return self.clone(actor_user_id=actor_user_id, actor_role=actor_role)

    def _inject_scope(self, params: Dict[str, Any]) -> Dict[str, Any]:
        scoped = dict(params or {})
        if self.tenant_id and "tenant_id" not in scoped:
            scoped["tenant_id"] = self.tenant_id
        if self.workspace_id and "workspace_id" not in scoped:
            scoped["workspace_id"] = self.workspace_id
        return scoped

    def _inject_actor(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        scoped = dict(payload or {})
        if self.actor_user_id and "actor_user_id" not in scoped:
            scoped["actor_user_id"] = self.actor_user_id
        if self.actor_role and "actor_role" not in scoped:
            scoped["actor_role"] = self.actor_role
        return scoped

    def _request(
        self, method: str, endpoint: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        内部请求方法，支持重试

        Args:
            method: HTTP方法 (POST/GET/DELETE)
            endpoint: API端点
            payload: 请求payload

        Returns:
            响应数据

        Raises:
            MemoryServiceError: 服务调用失败
        """
        url = f"{self.base_url}/{endpoint}"
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["x-agent-memory-service-key"] = self.api_key
        if self.access_token:
            headers["authorization"] = f"Bearer {self.access_token}"
        if self.workspace_id:
            headers["x-workspace-id"] = self.workspace_id
        request_headers = headers or None

        max_attempts = int(self.max_retries)
        if method.upper() == "POST" and endpoint in _NON_IDEMPOTENT_POST_ENDPOINTS:
            max_attempts = 1

        for attempt in range(max_attempts):
            try:
                if method.upper() == "POST":
                    response = self.session.post(
                        url, json=payload, timeout=self.timeout, headers=request_headers
                    )
                elif method.upper() == "GET":
                    response = self.session.get(url, timeout=self.timeout, headers=request_headers)
                elif method.upper() == "DELETE":
                    response = self.session.delete(url, timeout=self.timeout, headers=request_headers)
                else:
                    raise ValueError(f"Unsupported method: {method}")

                response.raise_for_status()

                try:
                    return response.json()
                except ValueError as e:
                    logger.error(
                        "Invalid JSON response",
                        extra={"url": url, "status_code": response.status_code},
                    )
                    raise MemoryServiceError(
                        "Invalid JSON response from memory service",
                        status_code=response.status_code,
                        details={"url": url, "response": response.text},
                    ) from e

            except requests.Timeout as e:
                logger.warning(
                    f"Request timeout (attempt {attempt + 1}/{max_attempts}): {e}"
                )
                if attempt == max_attempts - 1:
                    raise MemoryServiceError(
                        f"Request timeout after {max_attempts} attempts",
                        status_code=408,
                        details={"url": url, "timeout": self.timeout},
                    ) from e
                time.sleep(2**attempt)  # 指数退避

            except requests.ConnectionError as e:
                logger.warning(
                    f"Connection error (attempt {attempt + 1}/{max_attempts}): {e}"
                )
                if attempt == max_attempts - 1:
                    raise MemoryServiceError(
                        f"Connection failed after {max_attempts} attempts",
                        status_code=503,
                        details={"url": url},
                    ) from e
                time.sleep(2**attempt)

            except requests.HTTPError as e:
                response = getattr(e, "response", None)
                status_code = getattr(response, "status_code", None)
                response_text = getattr(response, "text", None)
                logger.error(
                    "HTTP error",
                    extra={"url": url, "status_code": status_code},
                )
                raise MemoryServiceError(
                    f"HTTP error: {e}",
                    status_code=status_code,
                    details={"url": url, "response": response_text},
                ) from e

            except Exception as e:
                logger.exception("Unexpected error", extra={"url": url})
                raise MemoryServiceError(
                    f"Unexpected error: {e}", details={"url": url}
                ) from e

    def stats(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fetch scoped memory stats."""
        payload = self._inject_scope(params or {})
        result = self._request("POST", "v1/memory/stats", payload)

        if result.get("status") != "success":
            raise MemoryServiceError(
                f"Stats failed: {result.get('message', 'Unknown error')}",
                details={"params": payload},
            )

        return result

    # ---- File-first APIs (Markdown truth) ----

    def memory_write(
        self,
        *,
        tier: str,
        scope: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        target: Optional[str] = None,
        tenant_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "tenant_id": tenant_id or self.tenant_id,
            "workspace_id": workspace_id or self.workspace_id,
            "tier": tier,
            "scope": scope,
            "content": content,
            "metadata": metadata or {},
            "target": target,
            "conversation_id": conversation_id,
            "task_id": task_id,
        }
        payload = self._inject_actor(payload)
        result = self._request("POST", "v1/memory/write", payload)
        if result.get("status") != "success":
            raise MemoryServiceError("memory_write failed", details={"payload": payload, "result": result})
        return result

    def memory_search(
        self,
        *,
        query: str,
        top_k: int = 5,
        tiers: Optional[List[str]] = None,
        scopes: Optional[List[str]] = None,
        memory_kinds: Optional[List[str]] = None,
        path_prefixes: Optional[List[str]] = None,
        tenant_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "tenant_id": tenant_id or self.tenant_id,
            "workspace_id": workspace_id or self.workspace_id,
            "query": query,
            "top_k": int(top_k),
            "tiers": tiers,
            "scopes": scopes,
            "memory_kinds": memory_kinds,
            "path_prefixes": path_prefixes,
        }
        payload = self._inject_actor(payload)
        result = self._request("POST", "v1/memory/search", payload)
        if result.get("status") != "success":
            raise MemoryServiceError("memory_search failed", details={"payload": payload, "result": result})
        return result

    def memory_read(
        self,
        *,
        tier: str,
        conversation_id: Optional[str] = None,
        task_id: Optional[str] = None,
        user_id: Optional[str] = None,
        key: Optional[str] = None,
        query: Optional[str] = None,
        limit: Optional[int] = None,
        top_k: Optional[int] = None,
        scopes: Optional[List[str]] = None,
        tenant_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "tenant_id": tenant_id or self.tenant_id,
            "workspace_id": workspace_id or self.workspace_id,
            "tier": tier,
            "conversation_id": conversation_id,
            "task_id": task_id,
            "user_id": user_id,
            "key": key,
            "query": query,
            "limit": limit,
            "top_k": top_k,
            "scopes": scopes,
        }
        payload = self._inject_actor(payload)
        result = self._request("POST", "v1/memory/read", payload)
        if result.get("status") != "success":
            raise MemoryServiceError("memory_read failed", details={"payload": payload, "result": result})
        return result

    def memory_get(
        self,
        *,
        path: str,
        start_line: Optional[int] = None,
        max_lines: Optional[int] = None,
        tenant_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "tenant_id": tenant_id or self.tenant_id,
            "workspace_id": workspace_id or self.workspace_id,
            "path": path,
            "start_line": start_line,
            "max_lines": max_lines,
        }
        payload = self._inject_actor(payload)
        result = self._request("POST", "v1/memory/get", payload)
        if result.get("status") != "success":
            raise MemoryServiceError("memory_get failed", details={"payload": payload, "result": result})
        return result

    def memory_index_rebuild(
        self,
        *,
        tenant_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rebuild the derived search index for the scoped workspace.

        This is gated on the server by `AGENT_MEMORY_INDEX_REBUILD_ENABLED=1`.
        """

        payload: Dict[str, Any] = {
            "tenant_id": tenant_id or self.tenant_id,
            "workspace_id": workspace_id or self.workspace_id,
        }
        result = self._request("POST", "v1/memory/index/rebuild", payload)
        if result.get("status") != "success":
            raise MemoryServiceError(
                "memory_index_rebuild failed", details={"payload": payload, "result": result}
            )
        return result

    def build_context(
        self,
        *,
        query: str,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        top_k: int = 5,
        semantic_top_k: Optional[int] = None,
        graph_top_k: Optional[int] = None,
        stm_last_k: int = 2,
        preference_limit: int = 50,
        include_preferences: bool = True,
        include_stm: bool = True,
        include_semantic: bool = True,
        include_graph: bool = True,
        include_sources: bool = False,
        fail_open: bool = True,
        max_chars: int = 6000,
        max_search_queries: int = 2,
    ) -> List[Dict[str, str]]:
        """Build agent-ready memory context for an external agent.

        The SDK does not require callers to adopt this repository's demo agent.
        Customers can prepend the returned messages to their own LangChain,
        LangGraph, OpenAI Agents SDK, or custom LLM message list.
        """

        sections: List[str] = []
        if system_prompt and str(system_prompt).strip():
            sections.append(str(system_prompt).strip())
        sections.append(SDK_MEMORY_CONTEXT_RULES.strip())

        def _call_memory(fn, *args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception:
                if not fail_open:
                    raise
                logger.debug("memory context fetch failed", exc_info=True)
                return None

        if include_preferences and user_id:
            prefs = _call_memory(
                self.memory_read,
                tier="preferences",
                user_id=user_id,
                limit=int(preference_limit),
            )
            pref_context = self._format_preferences_context(prefs)
            if pref_context:
                sections.append(pref_context)

        if include_stm and conversation_id and int(stm_last_k or 0) > 0:
            stm = _call_memory(
                self.memory_read,
                tier="stm",
                conversation_id=conversation_id,
                limit=int(stm_last_k),
            )
            stm_context = self._format_stm_context(stm)
            if stm_context:
                sections.append(stm_context)

        search_query = str(query or "").strip()
        if search_query and include_semantic:
            semantic = _call_memory(
                self._memory_search_with_fallback,
                query=search_query,
                top_k=int(semantic_top_k or top_k),
                tiers=["semantic"],
                max_queries=int(max_search_queries or 1),
            )
            semantic_context = self._format_hits_context(
                "Relevant Semantic Facts",
                semantic,
                include_sources=include_sources,
            )
            if semantic_context:
                sections.append(semantic_context)

        if search_query and include_graph:
            graph = _call_memory(
                self._memory_search_with_fallback,
                query=search_query,
                top_k=int(graph_top_k or top_k),
                tiers=["graph"],
                max_queries=int(max_search_queries or 1),
            )
            graph_context = self._format_hits_context(
                "Knowledge Graph",
                graph,
                include_sources=include_sources,
            )
            if graph_context:
                sections.append(graph_context)

        content = "\n\n".join(section for section in sections if section.strip())
        if max_chars and len(content) > int(max_chars):
            content = content[: int(max_chars)].rstrip() + "\n..."
        return [{"role": "system", "content": content}]

    def _memory_search_with_fallback(
        self,
        *,
        query: str,
        top_k: int,
        tiers: List[str],
        max_queries: int = 2,
    ) -> Dict[str, Any]:
        last_result: Dict[str, Any] = {}
        query_limit = max(1, int(max_queries or 1))
        for candidate in self._context_search_queries(query)[:query_limit]:
            last_result = self.memory_search(
                query=candidate,
                top_k=top_k,
                tiers=tiers,
            )
            data = last_result.get("data") if isinstance(last_result, dict) else {}
            hits = data.get("hits") if isinstance(data, dict) else []
            if hits:
                return last_result
        return last_result

    @staticmethod
    def _context_search_queries(query: str) -> List[str]:
        original = str(query or "").strip()
        queries: List[str] = []
        seen: set[str] = set()

        def add(candidate: str) -> None:
            value = str(candidate or "").strip()
            if value and value not in seen:
                seen.add(value)
                queries.append(value)

        add(original)
        generic = {
            "answer",
            "memory",
            "metadata",
            "path",
            "score",
            "source",
            "what",
            "when",
            "where",
            "which",
            "不要",
            "那个",
            "这个",
            "什么",
        }
        raw_tokens: List[str] = []
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", original):
            if token.lower() in generic:
                continue
            if token not in raw_tokens:
                raw_tokens.append(token)
        tokens = sorted(
            raw_tokens,
            key=lambda token: (
                0 if ("_" in token or "." in token) else 1,
                raw_tokens.index(token),
            ),
        )
        for token in tokens:
            add(token)
            if len(queries) >= 6:
                return queries
        for i in range(len(tokens) - 1):
            add(f"{tokens[i]} {tokens[i + 1]}")
            if len(queries) >= 8:
                return queries
        return queries

    def _format_preferences_context(self, result: Optional[Dict[str, Any]]) -> str:
        data = result.get("data") if isinstance(result, dict) else None
        if not data:
            return ""
        lines = ["## User Preferences"]
        if isinstance(data, dict):
            for key, value in list(data.items())[:50]:
                lines.append(f"- {key}: {value}")
        elif isinstance(data, list):
            for item in data[:50]:
                if not isinstance(item, dict):
                    continue
                key = item.get("key") or item.get("name")
                value = item.get("value") or item.get("content")
                if key and value is not None:
                    lines.append(f"- {key}: {value}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_stm_context(self, result: Optional[Dict[str, Any]]) -> str:
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, list) or not data:
            return ""
        lines = ["## Recent Conversation Memory"]
        for item in data[:10]:
            if isinstance(item, dict):
                text = (
                    item.get("final_answer")
                    or item.get("summary")
                    or item.get("conversation_summary")
                    or item.get("content")
                    or item.get("snippet")
                )
            else:
                text = item
            text = _clean_context_text(text)
            if text:
                lines.append(f"- {text}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_hits_context(
        self,
        title: str,
        result: Optional[Dict[str, Any]],
        *,
        include_sources: bool = False,
    ) -> str:
        data = result.get("data") if isinstance(result, dict) else None
        hits = data.get("hits") if isinstance(data, dict) else data
        if not isinstance(hits, list) or not hits:
            return ""
        lines = [f"## {title}"]
        for hit in hits[:20]:
            if isinstance(hit, dict):
                text = _hit_context_text(hit)
                source = self._format_hit_source(hit) if include_sources else ""
            else:
                text = _clean_context_text(hit)
                source = ""
            if not text:
                continue
            suffix = f" ({source})" if source else ""
            lines.append(f"- {text}{suffix}")
        return "\n".join(lines) if len(lines) > 1 else ""

    @staticmethod
    def _format_hit_source(hit: Dict[str, Any]) -> str:
        path = str(hit.get("path") or "").strip()
        line = hit.get("line") or hit.get("line_start")
        if path and line:
            return f"{path}:{line}"
        return path

    # 便捷方法：特定记忆类型的快速访问

    def store_stm(
        self, conversation_id: str, round_id: int, summary: str
    ) -> Dict[str, Any]:
        """Store a short-term conversation checkpoint."""
        return self.memory_write(
            tier="stm",
            scope="user",
            content=str(summary or ""),
            metadata={
                "conversation_id": conversation_id,
                "round_id": int(round_id),
                "stm_summary": {"final_answer": summary},
                **({"user_id": self.actor_user_id} if self.actor_user_id else {}),
            },
            conversation_id=conversation_id,
        )

    def retrieve_stm(self, conversation_id: str, last_k: int = 15) -> Dict[str, Any]:
        """Read short-term conversation checkpoints."""
        return self.memory_read(tier="stm", conversation_id=conversation_id, limit=int(last_k))

    def store_wm(
        self, user_id: str, task_id: str, state: Dict[str, Any], ttl_s: int | None = None
    ) -> Dict[str, Any]:
        """Store working memory state."""
        metadata: Dict[str, Any] = {"user_id": user_id, "task_id": task_id, "state": state}
        if ttl_s is not None:
            metadata["ttl_s"] = int(ttl_s)
        return self.memory_write(
            tier="wm",
            scope="user",
            content="",
            metadata=metadata,
            task_id=task_id,
        )

    def retrieve_wm(self, user_id: str, task_id: str) -> Dict[str, Any]:
        """Read working memory state."""
        return self.memory_read(tier="wm", user_id=user_id, task_id=task_id)

    def store_ltm_preference(
        self, user_id: str, key: str, value: Any
    ) -> Dict[str, Any]:
        """Store a durable user preference."""
        return self.memory_write(
            tier="preferences",
            scope="user",
            content=str(value),
            metadata={"user_id": user_id, "key": key, "value": value},
        )

    def retrieve_ltm_preference(self, user_id: str, key: str) -> Dict[str, Any]:
        """Read a durable user preference."""
        return self.memory_read(tier="preferences", user_id=user_id, key=key)

    def list_ltm_preferences(self, user_id: str, limit: int = 50) -> Dict[str, Any]:
        """List durable preferences for a user."""
        return self.memory_read(tier="preferences", user_id=user_id, limit=int(limit))

    def health_check(self) -> bool:
        """
        健康检查

        Returns:
            服务是否健康
        """
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=5)
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

    def close(self) -> None:
        """关闭客户端，释放资源"""
        if self.shared_pool:
            self.session.cookies.clear()
            logger.info("MemoryClient closed (shared pool retained)")
            return
        self.session.close()
        logger.info("MemoryClient closed")

    def __enter__(self) -> "MemoryClient":
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ) -> None:
        self.close()


class MemoryClientBuilder:
    """
    Memory客户端构建器
    提供链式API来配置客户端
    """

    def __init__(self):
        self.base_url = "http://127.0.0.1:8001"
        self.timeout = 15
        self.max_retries = 3

    def with_url(self, url: str) -> "MemoryClientBuilder":
        """设置URL"""
        self.base_url = url
        return self

    def with_timeout(self, timeout: int) -> "MemoryClientBuilder":
        """设置超时"""
        self.timeout = timeout
        return self

    def with_retries(self, max_retries: int) -> "MemoryClientBuilder":
        """设置重试次数"""
        self.max_retries = max_retries
        return self

    def build(self) -> MemoryClient:
        """构建客户端"""
        return MemoryClient(
            base_url=self.base_url, timeout=self.timeout, max_retries=self.max_retries
        )
