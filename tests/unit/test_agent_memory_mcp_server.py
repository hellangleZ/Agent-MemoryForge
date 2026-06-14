import json

import pytest

import agent_memory_mcp_server as mcp_server


def test_safe_json_loads_accepts_object():
    payload = json.dumps({"task_id": "t1"})
    assert mcp_server._safe_json_loads(payload) == {"task_id": "t1"}


def test_safe_json_loads_rejects_invalid_json():
    with pytest.raises(ValueError, match="Invalid JSON payload"):
        mcp_server._safe_json_loads("{bad}")


def test_safe_json_loads_rejects_non_object():
    with pytest.raises(ValueError, match="JSON payload must be an object"):
        mcp_server._safe_json_loads("[1, 2]")


def test_calculate_budget_handles_empty_days():
    result = mcp_server.calculate_budget("")
    assert result["success"] is False
    assert "days_str" in result["error"]


def test_calculate_budget_parses_days_and_level():
    result = mcp_server.calculate_budget("5 days", hotel_level="4star")
    assert result["success"] is True
    breakdown = result["breakdown"]
    assert breakdown["days"] == 5
    assert breakdown["hotel_level"] == "4star"
    assert breakdown["total"] > 0


def test_format_document_requires_text():
    result = mcp_server.format_document("")
    assert result["success"] is False


def test_format_document_formats_content():
    result = mcp_server.format_document("Hello", title="Title", style="casual")
    assert result["success"] is True
    assert "Title" in result["data"]
    assert "Hello" in result["data"]


def test_generate_itinerary_requires_payload():
    result = mcp_server.generate_itinerary("")
    assert result["success"] is False


def test_generate_itinerary_builds_output():
    payload = json.dumps(
        {
            "task_id": "task-1",
            "destination": "Tokyo",
            "results": {"flight_confirmation": "JL12"},
        }
    )
    result = mcp_server.generate_itinerary(payload)
    assert result["success"] is True
    assert result["task_id"] == "task-1"
    assert "Tokyo" in result["data"]


def test_project_gantt_defaults_and_dependencies():
    result = mcp_server.project_gantt("Alpha")
    assert result["success"] is True
    tasks = result["tasks"]
    assert tasks
    names = {task["name"] for task in tasks}
    assert "需求分析" in names


def test_project_risk_assess_scoring():
    result = mcp_server.project_risk_assess(project_type="e-commerce", team_size=4)
    assert result["success"] is True
    assert result["risks"]
    score = result["risks"][0]["score"]
    prob = result["risks"][0]["probability"]
    assert round(score, 1) == round(prob * 100, 1)
