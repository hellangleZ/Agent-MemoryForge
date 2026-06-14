"""Deterministic first-pass tool routing.

This module is intentionally conservative. It decides which external MCP tools
may be shown to an agent before the LLM gets a chance to choose tools.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable

TOOL_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
DOCUMENTATION_TOOL_NAMESPACES = {"context7"}
DATABASE_TOOL_NAMESPACES = {"neon", "supabase"}
DOCUMENTATION_LOOKUP_HINTS = (
    "api doc",
    "api docs",
    "api reference",
    "documentation",
    "docs",
    "framework",
    "library",
    "official doc",
    "package",
    "reference",
    "sdk",
    "文档",
    "官方文档",
    "库",
    "框架",
    "包",
)
DATABASE_TOOL_LOOKUP_HINTS = (
    "database",
    "db",
    "delete",
    "insert",
    "migration",
    "pgvector",
    "postgres",
    "postgresql",
    "query",
    "rls",
    "schema",
    "select",
    "sql",
    "table",
    "update",
    "upsert",
    "数据库",
    "数据表",
    "表",
    "表结构",
    "迁移",
    "查询",
    "索引",
    "向量库",
)
GENERIC_EXTERNAL_TOOL_HINTS = (
    "mcp",
    "tool",
    "tools",
    "call tool",
    "use tool",
    "调用工具",
    "使用工具",
    "外部工具",
)
TOOL_NAME_STOPWORDS = {
    "api",
    "call",
    "create",
    "delete",
    "execute",
    "fetch",
    "find",
    "get",
    "id",
    "list",
    "read",
    "resolve",
    "run",
    "search",
    "set",
    "tool",
    "update",
    "write",
}


def normalize_query(user_query: str) -> str:
    return str(user_query or "").strip().lower()


def is_external_tool_name(name: str) -> bool:
    return "." in str(name or "").strip()


def tool_namespace(name: str) -> str:
    raw = str(name or "").strip().lower()
    return raw.split(".", 1)[0] if "." in raw else ""


def query_mentions_tool_name(
    namespace: str, raw_tool_name: str, lowered_query: str
) -> bool:
    if namespace and namespace in lowered_query:
        return True
    for token in TOOL_TOKEN_PATTERN.findall(raw_tool_name):
        if len(token) < 3 or token in TOOL_NAME_STOPWORDS:
            continue
        token_pattern = rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])"
        if re.search(token_pattern, lowered_query):
            return True
    return False


def query_matches_tool_description(
    raw_tool_name: str, description: str, lowered_query: str
) -> bool:
    query_tokens = {
        token
        for token in TOOL_TOKEN_PATTERN.findall(lowered_query)
        if len(token) >= 3 and token not in TOOL_NAME_STOPWORDS
    }
    if not query_tokens:
        return False
    tool_tokens = {
        token
        for token in TOOL_TOKEN_PATTERN.findall(f"{raw_tool_name} {description}")
        if len(token) >= 3 and token not in TOOL_NAME_STOPWORDS
    }
    return len(query_tokens.intersection(tool_tokens)) >= 2


def should_discover_namespace(namespace: str, user_query: str) -> bool:
    lowered = normalize_query(user_query)
    ns = str(namespace or "").strip().lower()
    if not lowered or not ns:
        return False
    if ns in lowered:
        return True
    if ns in DOCUMENTATION_TOOL_NAMESPACES:
        return any(hint in lowered for hint in DOCUMENTATION_LOOKUP_HINTS)
    if ns in DATABASE_TOOL_NAMESPACES:
        return any(hint in lowered for hint in DATABASE_TOOL_LOOKUP_HINTS)
    return any(hint in lowered for hint in GENERIC_EXTERNAL_TOOL_HINTS)


def should_discover_external_tools(
    user_query: str,
    *,
    namespaces: Iterable[str] | None = None,
) -> bool:
    lowered = normalize_query(user_query)
    if not lowered:
        return False
    namespace_list = [
        str(namespace or "").strip().lower()
        for namespace in list(namespaces or [])
        if str(namespace or "").strip()
    ]
    if namespace_list:
        return any(
            should_discover_namespace(namespace, lowered)
            for namespace in namespace_list
        )
    hints = (
        DOCUMENTATION_LOOKUP_HINTS
        + DATABASE_TOOL_LOOKUP_HINTS
        + GENERIC_EXTERNAL_TOOL_HINTS
    )
    return any(hint in lowered for hint in hints)


def should_expose_tool(tool: Dict[str, Any], user_query: str) -> bool:
    name = str(tool.get("name") or "").strip()
    if not name or not is_external_tool_name(name):
        return True

    lowered = normalize_query(user_query)
    if not lowered:
        return False

    namespace, raw_tool_name = name.lower().split(".", 1)
    if query_mentions_tool_name(namespace, raw_tool_name, lowered):
        return True
    if namespace in DOCUMENTATION_TOOL_NAMESPACES:
        return any(hint in lowered for hint in DOCUMENTATION_LOOKUP_HINTS)
    if namespace in DATABASE_TOOL_NAMESPACES:
        return any(hint in lowered for hint in DATABASE_TOOL_LOOKUP_HINTS)

    description = str(tool.get("description") or "").strip().lower()
    return query_matches_tool_description(raw_tool_name, description, lowered)
