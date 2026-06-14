from agent_memory_framework.tool_intent import (
    should_discover_external_tools,
    should_discover_namespace,
    should_expose_tool,
)


def test_business_memory_question_does_not_discover_context7_or_database_tools():
    query = (
        "我现在这个 Northstar DW Ops 里，"
        "finance_mrr 的 freshness SLA 是什么？它上游依赖什么？"
    )

    assert should_discover_namespace("context7", query) is False
    assert should_discover_namespace("supabase", query) is False
    assert should_discover_external_tools(query, namespaces=["context7", "supabase"]) is False
    assert should_expose_tool({"name": "context7.resolve-library-id"}, query) is False


def test_documentation_question_discovers_context7_only():
    query = "查一下 React useEffect 的官方文档"

    assert should_discover_namespace("context7", query) is True
    assert should_discover_namespace("supabase", query) is False
    assert should_discover_external_tools(query, namespaces=["context7", "supabase"]) is True
    assert should_expose_tool({"name": "context7.resolve-library-id"}, query) is True


def test_database_question_discovers_database_tools_only():
    query = "帮我查一下 Supabase 的表结构和 SQL"

    assert should_discover_namespace("context7", query) is False
    assert should_discover_namespace("supabase", query) is True
    assert should_discover_external_tools(query, namespaces=["context7", "supabase"]) is True
    assert should_expose_tool({"name": "supabase.execute-sql"}, query) is True


def test_unknown_tool_requires_explicit_namespace_or_description_match():
    tool = {
        "name": "warehouse.lookup-lineage",
        "description": "Lookup data warehouse table lineage and upstream dependencies.",
    }

    assert should_discover_namespace("warehouse", "finance_mrr 上游依赖是什么？") is False
    assert should_discover_namespace("warehouse", "用 warehouse 查 finance_mrr 上游依赖") is True
    assert should_expose_tool(tool, "finance_mrr 上游依赖是什么？") is False
    assert should_expose_tool(tool, "用 warehouse 查 finance_mrr 上游依赖") is True
