import json
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from mcp.server.fastmcp import FastMCP
    _MCP_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only with broken optional deps
    _MCP_IMPORT_ERROR = exc

    class FastMCP:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        def tool(self, *args: Any, **kwargs: Any):
            def _decorator(fn):
                return fn

            return _decorator

        def run(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError(
                "Optional dependency 'mcp' is unavailable or incompatible; "
                "install a compatible MCP package to run agent_memory_mcp_server."
            ) from _MCP_IMPORT_ERROR


def _safe_json_loads(payload: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON payload: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("JSON payload must be an object")
    return parsed


mcp = FastMCP(
    name="agent-memory-local-tools",
    instructions=(
        "Local MCP server exposing a small curated set of legacy skills as tools. "
        "This is a migration path away from the in-repo `skills/` plugin design."
    ),
)


@mcp.tool(
    name="calculate_budget",
    description="Calculate travel budget from a days string and hotel level.",
)
def calculate_budget(days_str: str, hotel_level: str = "5star") -> Dict[str, Any]:
    import re

    if not days_str:
        return {"success": False, "error": "days_str参数不能为空"}

    days_match = re.search(r"\d+", str(days_str))
    days = int(days_match.group()) if days_match else 3

    flight_cost = 1200
    hotel_costs = {"5star": 800, "4star": 500, "3star": 300}
    meal_cost_per_day = 300
    transport_cost = 200

    nightly = hotel_costs.get(hotel_level, 800)
    hotel_cost = nightly * days
    meal_cost = meal_cost_per_day * days
    total = flight_cost + hotel_cost + meal_cost + transport_cost

    result = (
        f"\n💰 差旅预算计算 (共{days}天):\n"
        f"  ✈️  机票: ¥{flight_cost}\n"
        f"  🏨 酒店: ¥{hotel_cost} ({hotel_level}, ¥{nightly}/晚)\n"
        f"  🍽️  餐费: ¥{meal_cost} (¥{meal_cost_per_day}/天)\n"
        f"  🚗 交通: ¥{transport_cost}\n"
        "  ─────────────────\n"
        f"  💳 总计: ¥{total}\n"
    ).strip()

    return {
        "success": True,
        "data": result,
        "message": "预算计算成功",
        "breakdown": {
            "days": days,
            "flight_cost": flight_cost,
            "hotel_cost": hotel_cost,
            "hotel_level": hotel_level,
            "meal_cost": meal_cost,
            "transport_cost": transport_cost,
            "total": total,
        },
    }


@mcp.tool(
    name="format_document",
    description="Format a document by applying basic structure and separators.",
)
def format_document(
    document_text: str, title: str = "文档", style: str = "business"
) -> Dict[str, Any]:
    if not document_text:
        return {"success": False, "error": "document_text参数不能为空"}

    header = f"{title}"
    sep = "=" * 40 if style == "business" else "-" * 40
    formatted = f"{sep}\n{header}\n{sep}\n{document_text.strip()}\n{sep}"
    return {"success": True, "data": formatted, "message": "文档格式化成功"}


@mcp.tool(
    name="generate_itinerary",
    description="Generate a simple itinerary from a JSON payload.",
)
def generate_itinerary(task_data_json: str) -> Dict[str, Any]:
    if not task_data_json:
        return {"success": False, "error": "task_data_json参数不能为空"}

    task_data = _safe_json_loads(task_data_json)
    results = task_data.get("results", {})
    destination = task_data.get("destination", "未知")

    itinerary = (
        "\n========================================\n"
        f"      商务行程单 (任务ID: {task_data.get('task_id')})\n"
        "========================================\n"
        f"目的地: {destination}\n"
        f"航班号: {results.get('flight_confirmation', '待定')} (偏好: {results.get('flight_preference', '无')})\n"
        f"酒店: {results.get('hotel_confirmation', '待定')}\n"
        f"晚宴地点: {results.get('dinner_location', '待定')}\n"
        f"备注: {results.get('notes', '无')}\n"
        "----------------------------------------"
    ).strip()

    return {
        "success": True,
        "data": itinerary,
        "message": "行程单生成成功",
        "task_id": task_data.get("task_id"),
        "destination": destination,
    }


@mcp.tool(
    name="project_gantt",
    description="Generate a lightweight Gantt chart schedule from tasks.",
)
def project_gantt(
    project_name: str,
    tasks: Optional[List[Dict[str, Any]]] = None,
    start_date: Optional[str] = None,
) -> Dict[str, Any]:
    from datetime import timedelta

    if not project_name:
        return {"success": False, "error": "project_name参数不能为空"}

    if start_date is None:
        start_date = datetime.now().strftime("%Y-%m-%d")

    default_tasks: List[Dict[str, Any]] = [
        {"name": "需求分析", "duration": 10, "dependencies": []},
        {"name": "技术方案设计", "duration": 7, "dependencies": ["需求分析"]},
        {"name": "前端开发", "duration": 20, "dependencies": ["技术方案设计"]},
        {"name": "后端开发", "duration": 25, "dependencies": ["技术方案设计"]},
        {"name": "集成测试", "duration": 10, "dependencies": ["前端开发", "后端开发"]},
        {"name": "用户验收测试", "duration": 5, "dependencies": ["集成测试"]},
        {"name": "部署上线", "duration": 3, "dependencies": ["用户验收测试"]},
    ]
    tasks = tasks or default_tasks

    parsed_start = datetime.strptime(start_date, "%Y-%m-%d")
    schedule: Dict[str, Dict[str, Any]] = {}

    def compute_start(task: Dict[str, Any]) -> datetime:
        dep_names = list(task.get("dependencies") or [])
        if not dep_names:
            return parsed_start
        dep_ends: List[datetime] = []
        for dep_name in dep_names:
            if dep_name not in schedule:
                dep_task = next((t for t in tasks if t.get("name") == dep_name), None)
                if dep_task is None:
                    continue
                ensure_task(dep_task)
            dep_ends.append(
                datetime.strptime(schedule[dep_name]["end_date"], "%Y-%m-%d")
            )
        return max(dep_ends) if dep_ends else parsed_start

    def ensure_task(task: Dict[str, Any]) -> None:
        name = str(task.get("name") or "").strip()
        if not name or name in schedule:
            return
        start_dt = compute_start(task)
        duration = int(task.get("duration") or 1)
        end_dt = start_dt + timedelta(days=duration)
        schedule[name] = {
            "name": name,
            "start_date": start_dt.strftime("%Y-%m-%d"),
            "end_date": end_dt.strftime("%Y-%m-%d"),
            "duration_days": duration,
            "dependencies": list(task.get("dependencies") or []),
        }

    for task in tasks:
        ensure_task(task)

    return {
        "success": True,
        "message": "甘特图生成成功",
        "project_name": project_name,
        "start_date": start_date,
        "tasks": list(schedule.values()),
    }


@mcp.tool(
    name="project_risk_assess",
    description="Generate a compact project risk assessment.",
)
def project_risk_assess(
    project_type: str = "e-commerce",
    team_size: int = 12,
    budget: int = 200,
    duration_months: int = 6,
) -> Dict[str, Any]:
    # budget here is in 万元
    risks_by_type: Dict[str, List[Dict[str, Any]]] = {
        "e-commerce": [
            {
                "name": "需求变更频繁",
                "category": "需求风险",
                "probability": 0.8,
                "impact": "高",
                "mitigation": "冻结需求窗口、变更评审、影响分析",
            },
            {
                "name": "第三方API不稳定",
                "category": "技术风险",
                "probability": 0.6,
                "impact": "中",
                "mitigation": "熔断重试、降级方案、SLA监控",
            },
        ],
        "default": [
            {
                "name": "进度延误",
                "category": "进度风险",
                "probability": 0.5,
                "impact": "中",
                "mitigation": "里程碑拆分、关键路径管理、风险缓冲",
            }
        ],
    }

    base = risks_by_type.get(project_type, risks_by_type["default"])

    multiplier = 1.0
    if team_size < 6:
        multiplier += 0.1
    if duration_months <= 3:
        multiplier += 0.1
    if budget < 100:
        multiplier += 0.1

    scored = []
    for risk in base:
        prob = min(0.95, max(0.05, float(risk["probability"]) * multiplier))
        scored.append({**risk, "probability": prob, "score": round(prob * 100, 1)})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return {
        "success": True,
        "message": "风险评估完成",
        "inputs": {
            "project_type": project_type,
            "team_size": team_size,
            "budget_wanyuan": budget,
            "duration_months": duration_months,
        },
        "risks": scored,
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
