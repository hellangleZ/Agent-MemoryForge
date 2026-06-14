# -*- coding: utf-8 -*-
import os
import argparse
import requests
import json
import uuid
import time
import re
import logging
from datetime import datetime
from typing import List, Dict, Any
from collections import Counter
import jieba
from openai import OpenAI
from dotenv import load_dotenv
try:
    from conversation_value_filter import (
        ConversationValueFilter,
        ConversationItem,
        FilterResult,
    )
except ModuleNotFoundError:
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
    from conversation_value_filter import (
        ConversationValueFilter,
        ConversationItem,
        FilterResult,
    )
from examples.task_todo_manager import TaskTodoManager
from config.agent_config import get_config
from agent_memory_lib.client import MemoryClient
from agent_memory_framework.memory_runtime.memory_manager import MemoryManager
from agent_memory_framework.memory_runtime.context_builder import ContextBuilder


# --- 日志配置 ---
def setup_logging():
    """配置日志记录，输出到外部文件"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(
        "project_management_demo.log", mode="w", encoding="utf-8", errors="replace"
    )
    fh.setLevel(logging.INFO)
    debug_fh = logging.FileHandler(
        "project_management_demo_debug.log",
        mode="w",
        encoding="utf-8",
        errors="replace",
    )
    debug_fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - [%(module)s:%(funcName)s:%(lineno)d] - %(message)s"
    )
    fh.setFormatter(formatter)
    debug_fh.setFormatter(formatter)
    logger.addHandler(fh)
    logger.addHandler(debug_fh)


logger = logging.getLogger(__name__)


def main() -> int:
    global MEMORY_SERVICE_URL, USER_ID, AGENT_ID

    parser = argparse.ArgumentParser(
        prog="project_management_demo_real",
        description="Project management agent demo (MCP-first).",
    )
    parser.add_argument(
        "--memory-service-url",
        default=os.getenv("MEMORY_SERVICE_URL", MEMORY_SERVICE_URL),
        help="Memory service base URL (default: from config/env)",
    )
    parser.add_argument(
        "--user-id",
        default=os.getenv("USER_ID", USER_ID),
        help="User id used for memory scoping",
    )
    parser.add_argument(
        "--agent-id",
        default=os.getenv("AGENT_ID", AGENT_ID),
        help="Agent id",
    )
    parser.add_argument(
        "--mcp-config",
        default=os.getenv("AGENT_MEMORY_MCP_CONFIG", ""),
        help="Path to MCP servers JSON file (same schema as AGENT_MEMORY_MCP_SERVERS)",
    )

    args = parser.parse_args()

    if args.mcp_config:
        try:
            from agent_memory_framework.mcp_stdio_client import mcp_servers_from_file

            servers = mcp_servers_from_file(args.mcp_config)
            os.environ["AGENT_MEMORY_MCP_SERVERS"] = json.dumps(servers, ensure_ascii=False)
        except Exception as e:
            print(f"[MCP] Failed to load --mcp-config={args.mcp_config}: {e}")
            return 2

    MEMORY_SERVICE_URL = args.memory_service_url
    USER_ID = args.user_id
    AGENT_ID = args.agent_id

    setup_logging()
    logger.info("================== 项目管理Agent会话开始 ==================")
    _print_mcp_setup_hints()
    agent = ProjectManagementAgent(
        user_id=USER_ID,
        agent_id=AGENT_ID,
        memory_service_url=MEMORY_SERVICE_URL,
    )
    agent.run()
    logger.info("================== 项目管理Agent会话结束 ==================")
    return 0


def _cli_print(msg: str) -> None:
    print(msg)
    logger.info(msg)


def _print_mcp_setup_hints() -> None:
    import os

    has_multi = bool(os.getenv("AGENT_MEMORY_MCP_SERVERS", "").strip())
    has_single = bool(os.getenv("AGENT_MEMORY_MCP_STDIO", "").strip())
    if has_multi or has_single:
        return

    _cli_print("[MCP] No MCP servers configured.")
    _cli_print(
        "[MCP] Set AGENT_MEMORY_MCP_STDIO for a local stdio server, e.g.:\n"
        "  export AGENT_MEMORY_MCP_STDIO='{'\"command\"':'\"python\"','\"args\"':['\"-m\"','\"agent_memory_mcp_server\"']}'"
    )
    _cli_print(
        "[MCP] Or configure multiple servers with namespaces (local vs third-party), e.g.:\n"
        "  export AGENT_MEMORY_MCP_SERVERS='[{\"name\":\"local\",\"transport\":\"stdio\",\"namespace\":\"local\",\"command\":\"python\",\"args\":[\"-m\",\"agent_memory_mcp_server\"]},"
        "{\"name\":\"third\",\"transport\":\"http\",\"namespace\":\"third\",\"url\":\"http://127.0.0.1:8002/mcp\"}]'"
    )


# --- 配置管理 ---
load_dotenv()

# 使用配置类管理所有配置（避免硬编码）
config = get_config()

# 向后兼容：导出全局变量（不推荐使用，建议使用config）
MEMORY_SERVICE_URL = config.memory_service_url
USER_ID = config.user_id
AGENT_ID = config.agent_id


# --- 智能Context构建工具函数 ---
def estimate_tokens(text: str) -> int:
    """估算文本的token数量（中文约1.5字符=1token，英文约4字符=1token）。

    保留该函数用于 demo 输出与排查，不作为核心 context 算法。
    """
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def extract_keywords(text: str, top_k: int = 10) -> List[str]:
    """使用jieba提取关键词。

    说明：该 demo 已迁移为 MCP-first，并推荐使用框架侧的 ContextBuilder。
    这里保留函数仅用于旧逻辑/兼容性，不再作为核心 context 策略。
    """
    words = jieba.cut(text)
    # 过滤停用词和单字符
    stopwords = {
        "的",
        "了",
        "是",
        "我",
        "你",
        "他",
        "她",
        "它",
        "们",
        "在",
        "和",
        "与",
        "或",
        "但",
        "而",
        "如果",
        "那么",
        "因为",
        "所以",
        "这",
        "那",
        "个",
        "位",
        "次",
        "回",
        "什么",
        "怎么",
        "如何",
        "吗",
        "呢",
        "啊",
        "吧",
        "哦",
        "嗯",
    }
    keywords = [w for w in words if len(w) > 1 and w not in stopwords]
    # 返回出现频率最高的关键词
    word_freq = Counter(keywords)
    return [word for word, _ in word_freq.most_common(top_k)]


def calculate_relevance(summary: Dict[str, Any], keywords: List[str]) -> float:
    """计算STM摘要与关键词的相关性分数（legacy）。

    说明：新版本的 context 构建建议交由 memory service + distill worker + ContextBuilder。
    """
    if not keywords:
        return 0.5  # 无关键词时返回中等相关性

    score = 0.0
    user_request = summary.get("user_request", "").lower()
    final_answer = summary.get("final_answer", "").lower()
    combined_text = user_request + " " + final_answer

    # 关键词匹配得分（每个关键词0.2分）
    for keyword in keywords:
        if keyword.lower() in combined_text:
            score += 0.2

    # 记忆类型匹配加分
    memories_used = summary.get("memories_used", [])
    memory_keywords = {
        "semantic",
        "kg",
        "ltm",
        "working",
        "procedural",
        "vector",
        "stm",
    }
    for mem in memories_used:
        if any(keyword in mem.lower() for keyword in memory_keywords):
            score += 0.1

    # 时间衰减因子（最近的对话相关性更高）
    timestamp = summary.get("timestamp", "")
    try:
        summary_time = datetime.fromisoformat(timestamp)
        days_ago = (datetime.now() - summary_time).days
        time_decay = max(0.5, 1.0 - days_ago / 30)  # 30天内的记忆有较高权重
        score *= time_decay
    except (ValueError, TypeError) as e:
        # 时间戳解析失败，使用默认权重
        logger.debug(f"时间戳解析失败: {timestamp}, 错误: {e}")
        pass

    return min(score, 1.0)  # 最高1.0分


def log_memory_usage(query: str, memories_used: Dict[str, Any], token_count: int):
    """可视化显示记忆使用情况"""
    _cli_print(f"\n{'=' * 70}")
    _cli_print(f"📊 当前查询: {query[:60]}...")
    _cli_print("🧠 使用的记忆类型:")

    for mem_type, data in memories_used.items():
        if mem_type == "stm_summaries":
            _cli_print(f"   • STM摘要: {len(data)} 条 (相关性阈值: 0.3)")
            for i, summary in enumerate(data[:3], 1):
                relevance = summary.get("relevance_score", 0)
                user_req = summary.get("user_request", "")[:40]
                _cli_print(f"     {i}. [{relevance:.2f}] {user_req}...")
            if len(data) > 3:
                _cli_print(f"     ... 省略 {len(data) - 3} 条低相关性摘要")
        elif mem_type == "vector_memories":
            _cli_print(f"   • 向量记忆: {len(data)} 条")
        elif mem_type == "ltm_data":
            _cli_print(f"   • 长期偏好: {len(data)} 条")
        else:
            _cli_print(f"   • {mem_type}: {data}")

    _cli_print(f"📏 Context Token估算: {token_count} tokens")
    _cli_print(
        f"💡 相比传统方法节省: {int((1 - token_count / 8000) * 100)}% context空间"
    )
    _cli_print(f"{'=' * 70}\n")


def _get_azure_client_and_model():
    """Late-bind Azure OpenAI client.

    This keeps the demo importable (no side effects at import time).
    """

    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    base_url = os.getenv("AZURE_OPENAI_ENDPOINT")
    model_name = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if not all([api_key, base_url, model_name]):
        raise ValueError(
            "Azure OpenAI 配置不完整。请设置: AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_DEPLOYMENT"
        )

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        default_query={"api-version": "preview"},
        timeout=60.0,
    )
    return client, model_name


# --- 辅助函数 ---
def call_memory_service(endpoint: str, payload: dict) -> dict:
    url = f"{MEMORY_SERVICE_URL}/{endpoint}"
    logger.debug(
        f"准备调用记忆服务: Endpoint={endpoint}, Payload={json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        json_response = response.json()
        logger.debug(f"记忆服务响应: {json.dumps(json_response, ensure_ascii=False)}")
        return json_response
    except requests.exceptions.RequestException as e:
        error_message = f"调用记忆服务失败: {e}"
        logger.error(error_message)
        return {"status": "error", "detail": error_message}


class ProjectManagementAgent:
    def __init__(self, user_id, agent_id, *, memory_service_url: str | None = None):
        self.user_id = user_id
        self.agent_id = agent_id
        if memory_service_url:
            global MEMORY_SERVICE_URL
            MEMORY_SERVICE_URL = memory_service_url
        self.conversation_history = []  # 当前轮次的推理对话
        self.conversation_id = str(uuid.uuid4())  # 为STM同步生成会话ID
        self.round_id = 0  # 对话轮次计数器
        self.current_user_query = ""  # 当前用户查询（用于智能context构建）

        logger.info(f"Agent {self.agent_id} 正在为用户 {self.user_id} 进行初始化...")
        logger.info(f"会话ID: {self.conversation_id}")

        # 初始化对话价值过滤器
        self.conversation_filter = ConversationValueFilter()
        logger.info("✅ 3级漏斗记忆过滤器初始化完成")

        # 初始化Todo追踪管理器
        self.todo_manager = TaskTodoManager()
        logger.info("✅ 任务Todo追踪管理器初始化完成")

        # 优化：添加STM查询缓存（使用配置类）
        self._stm_cache = {}  # STM查询缓存 {cache_key: (timestamp, result)}
        self._stm_cache_ttl = config.stm_cache_ttl  # 从配置读取TTL
        logger.info(f"✅ STM查询缓存初始化完成 (TTL={self._stm_cache_ttl}s)")

        self.tools_definitions, self.tool_functions = self._initialize_tools()
        self._azure_client = None
        self._model_name = None
        logger.info("项目管理Agent已准备就绪。")

    def _get_llm(self):
        if self._azure_client is None or self._model_name is None:
            self._azure_client, self._model_name = _get_azure_client_and_model()
            logger.info("Azure OpenAI 客户端初始化成功 (使用 responses API)")
        return self._azure_client, self._model_name

    def _initialize_tools(self):
        """[项目管理版] 为七大记忆模块提供完整、精确的工具集"""
        tool_functions = {}
        tools_definitions = []

        # 1. MCP工具
        # 推荐使用 multi-server 配置（stdio + http/streamable-http），并用 namespace 区分本地与第三方。
        # 该 demo 直接复用框架的 discover_tools()，避免重复实现 MCP 客户端逻辑。
        try:
            from agent_memory_framework import discover_tools

            discovered = discover_tools()
            for tool in discovered.values():
                tools_definitions.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": tool.schema.get("description")
                        or f"MCP tool: {tool.name}",
                        "parameters": tool.schema.get("parameters")
                        or {"type": "object", "properties": {}},
                    }
                )
                tool_functions[tool.name] = tool.func
            if discovered:
                logger.info("成功加载MCP工具集: %s", len(discovered))
        except Exception as e:
            logger.error(f"加载MCP工具失败: {e}")

        # 2. 加入与记忆模块一一对应的内置工具
        meta_tools_def = [
            {
                "type": "function",
                "name": "query_ltm_preference",
                "description": "查询用户的【长期偏好记忆】。当你需要了解用户的习惯、喜好（如管理风格、会议偏好等）时必须使用此工具。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "要查询的偏好键名，例如 'meeting_style' 或 'management_style'。",
                        }
                    },
                    "required": ["key"],
                },
            },
            {
                "type": "function",
                "name": "query_semantic_memory",
                "description": "查询【语义记忆】，查找客观事实、标准流程或项目管理知识。例如查询敏捷开发最佳实践或查找风险管理流程。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query_text": {
                            "type": "string",
                            "description": "描述你要查找的事实或知识的关键词。",
                        }
                    },
                    "required": ["query_text"],
                },
            },
            {
                "type": "function",
                "name": "query_knowledge_graph",
                "description": "查询【知识图谱】，探索实体之间的关系。例如查询Bob的技能和职责或查询团队协作关系。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string", "description": "关系的主体"},
                        "relation": {
                            "type": "string",
                            "description": "要查询的关系类型",
                        },
                    },
                    "required": ["subject", "relation"],
                },
            },
            {
                "type": "function",
                "name": "query_stm",
                "description": "查询【短期记忆STM】，获取当前对话会话中的历史消息和上下文信息。用于回顾最近的对话内容或查找会话相关的临时信息。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "conversation_id": {
                            "type": "string",
                            "description": "对话会话ID，不填则使用当前会话",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回的记忆条数限制，默认10",
                        },
                    },
                    "required": [],
                },
            },
            {
                "type": "function",
                "name": "manage_working_memory",
                "description": "管理【工作记忆】，用于跟踪一个需要多步骤完成的复杂任务。可以创建(create)、更新(update)、检索(retrieve)或清除(clear)一个任务。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "操作类型，可选 'create', 'update', 'retrieve', 'clear'",
                        },
                        "task_id": {"type": "string", "description": "任务的唯一ID"},
                        "data": {
                            "type": "object",
                            "description": "在create或update时传入的任务数据",
                        },
                    },
                    "required": ["action", "task_id"],
                },
            },
            {
                "type": "function",
                "name": "consolidate_memory",
                "description": "当你成功为用户完成一项重要任务后，调用此工具将关键成果作为新的【情节记忆】存入长期记忆库。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "对需要被记忆的核心成果的简洁概括。",
                        }
                    },
                    "required": ["summary"],
                },
            },
            # 项目管理专项技能
            {
                "type": "function",
                "name": "generate_gantt_chart",
                "description": "生成项目甘特图，展示任务时间安排和依赖关系。帮助项目经理可视化项目进度和资源分配。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_name": {"type": "string", "description": "项目名称"},
                        "tasks": {
                            "type": "array",
                            "description": "任务列表，每个任务包含name、duration、dependencies",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "duration": {"type": "integer"},
                                    "dependencies": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                            },
                        },
                        "start_date": {
                            "type": "string",
                            "description": "项目开始日期，格式YYYY-MM-DD",
                        },
                    },
                    "required": [],
                },
            },
            {
                "type": "function",
                "name": "assess_project_risks",
                "description": "评估项目风险并生成风险管理报告。分析项目中的潜在风险并提供缓解策略。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_type": {
                            "type": "string",
                            "description": "项目类型，如e-commerce",
                        },
                        "team_size": {
                            "type": "integer",
                            "description": "团队规模（人数）",
                        },
                        "budget": {
                            "type": "integer",
                            "description": "项目预算（万元）",
                        },
                        "duration_months": {
                            "type": "integer",
                            "description": "项目周期（月）",
                        },
                    },
                    "required": [],
                },
            },
            {
                "type": "function",
                "name": "end_conversation",
                "description": "当用户明确表示对话结束或任务已全部完成时调用。",
                "parameters": {"type": "object", "properties": {}},
            },
        ]
        tools_definitions.extend(meta_tools_def)
        tool_functions["query_ltm_preference"] = self._query_ltm_preference
        tool_functions["query_semantic_memory"] = self._query_semantic_memory
        tool_functions["query_knowledge_graph"] = self._query_knowledge_graph
        tool_functions["query_stm"] = self._query_stm
        tool_functions["manage_working_memory"] = self._manage_working_memory
        tool_functions["consolidate_memory"] = self._consolidate_memory
        tool_functions["generate_gantt_chart"] = self._generate_gantt_chart
        tool_functions["assess_project_risks"] = self._assess_project_risks
        tool_functions["end_conversation"] = self._end_conversation

        logger.info(f"Agent工具集初始化完成，共加载 {len(tools_definitions)} 个工具。")
        return tools_definitions, tool_functions

    def _get_system_prompt(self):
        """项目管理助手的系统提示"""
        return f"""你是{self.agent_id}，一个专业的项目管理智能助手，为项目经理{self.user_id}提供全方位的项目管理支持。

**【你的专业领域】**
- 📋 项目规划与进度管理
- 👥 团队协调与资源分配  
- 📊 风险识别与质量控制
- 💡 最佳实践建议与决策支持
- 📈 数据分析与报告生成

**【当前项目背景】**
你正在协助管理一个"电商平台重构项目"：
- 项目预算：200万
- 项目周期：6个月
- 团队规模：12人
- 核心功能：用户系统、商品管理、订单处理、支付集成
- 技术栈：React + Node.js + MongoDB + Redis + Docker

**【7大记忆系统使用策略 - 多记忆协同原则】**

⚠️ **重要**: 对于复杂任务，你必须查询多个记忆系统来获得全面信息！

	**【记忆查询组合策略】**
	- 📋 **项目规划任务**: query_semantic_memory(敏捷最佳实践) + query_knowledge_graph(团队技能)
	- 👥 **团队管理问题**: query_ltm_preference(管理风格) + query_knowledge_graph(团队关系)
	- 🚨 **风险评估**: query_semantic_memory(风险管理知识) + assess_project_risks工具
	- 📈 **项目回顾**: query_stm(最近讨论) + query_semantic_memory(回顾流程)

	**【单一记忆系统使用场景】**
	1. **短期记忆STM (query_stm)** - 对话连贯性
	   - 🔑 触发词："刚才"、"之前说过"、"刚刚讨论的"
	   
	2. **语义记忆 (query_semantic_memory)** - 知识库查询  
	   - 🔑 触发词："标准流程"、"最佳实践"、"敏捷开发"、"风险管理"
	   
	3. **长期偏好 (query_ltm_preference)** - 个人习惯
	   - 🔑 触发词："我的风格"、"习惯做法"、"偏好"、"管理方式"
	   
	4. **知识图谱 (query_knowledge_graph)** - 关系网络
	   - 🔑 触发词："团队成员"、"谁负责"、"技能分布"、"协作关系"
	   
	5. **工作记忆 (manage_working_memory)** - 复杂任务跟踪
	   - 🔑 场景：多步骤项目规划、风险评估、团队重组等
	   
	6. **程序记忆 (skills)** - 执行具体操作
	   - 🔑 触发词："生成甘特图"、"风险评估"、"数据分析"

**【智能工作流程】**
1. 📥 理解需求 → 分析用户想要什么
2. 🧠 查询记忆 → 获取相关历史和知识
3. 📊 分析情况 → 结合项目状态和团队情况
4. 💡 制定方案 → 提供具体可行的建议
5. 🛠️ 执行任务 → 调用相应技能完成操作  
6. 📚 归档成果 → 记录重要结果和决策

**【沟通原则】**
- 主动查询相关记忆，提供上下文丰富的回答
- 结合项目实际情况给出可操作的建议
- 识别风险和机会，及时提醒
- 保持专业且易懂的沟通风格
- 每次完成重要任务后都要consolidate_memory

记住：你是一个真正理解项目管理的智能助手，要充分利用7层记忆系统提供专业、精准、有价值的支持！"""

    def run(self):
        """启动Agent的主交互循环"""
        _cli_print("\n" + "=" * 60)
        _cli_print("🚀 项目管理智能助手")
        _cli_print(f"你好 {self.user_id}，我是您的项目管理助手 {self.agent_id}")
        _cli_print("💡 我拥有完整的7层记忆系统，可以协助您进行：")
        _cli_print("   📋 项目规划与甘特图生成")
        _cli_print("   🚨 风险评估与管理")
        _cli_print("   👥 团队协调与资源分配")
        _cli_print("   📊 项目进度跟踪")
        _cli_print("   🧠 基于历史经验的决策支持")
        _cli_print("\n输入 '退出' 来结束对话")
        _cli_print("=" * 60)

        logger.info("项目管理Agent交互循环开始。")

        self.conversation_history = [
            {"role": "system", "content": self._get_system_prompt()}
        ]

        while True:
            raw_input = input(f"\n{self.user_id} > ")
            user_input = raw_input.encode("utf-8", errors="replace").decode("utf-8")
            logger.info(f"收到用户输入: '{user_input}'")
            if user_input.lower() in ["退出", "exit", "quit"]:
                # 完成当前任务（如果有）
                if self.todo_manager.current_task_id:
                    self.todo_manager.complete_task("用户主动退出")
                logger.info("用户请求退出。")
                _cli_print("再见！期待下次为您的项目管理工作提供支持！")
                break

            # 设置当前用户查询（用于智能context构建）
            self.current_user_query = user_input

            # 🎯 开始新任务Todo追踪
            task_id = self.todo_manager.start_new_task(user_input)
            logger.info(f"📋 新任务开始: {task_id}")

            # 🧠 在处理用户输入前，先进行3级漏斗记忆价值分析和转换
            try:
                filter_result, consolidation_success = (
                    self._process_conversation_to_memory(user_input)
                )
                logger.info(
                    f"记忆转换完成 - Level {filter_result.memory_level}, 成功: {consolidation_success}"
                )
            except Exception as e:
                logger.error(f"记忆转换过程出错: {e}")

            # 📈 新轮次开始，增加轮次计数
            self.round_id += 1
            logger.info(f"📈 开始第 {self.round_id} 轮对话")

            # 🧠 构建增强上下文（STM摘要 + 当前对话）
            enhanced_context = self._build_enhanced_context()

            # 重新构建对话历史，包含历史摘要和当前用户输入
            self.conversation_history = enhanced_context
            self.conversation_history.append({"role": "user", "content": user_input})

            # 🔄 实时同步到STM（旧版格式）
            self._sync_message_to_stm({"role": "user", "content": user_input})

            final_answer = self._think_and_act_loop()
            _cli_print(f"\n{self.agent_id} > {final_answer}")

            assistant_message = {"role": "assistant", "content": final_answer}
            self.conversation_history.append(assistant_message)

            # 🔄 实时同步到STM（旧版格式）
            self._sync_message_to_stm(assistant_message)

            logger.info(f"Agent最终回答: '{final_answer}'")

            # 🔚 轮次结束 - 存储对话摘要到STM
            self._finalize_conversation_round(user_input, final_answer)

            # 🧠 智能容量管理
            self._manage_conversation_capacity()

            # 🎯 完成任务Todo追踪
            self.todo_manager.complete_task(
                final_answer[:100] + "..." if len(final_answer) > 100 else final_answer
            )
            logger.info(f"📋 任务完成: {task_id}")

    def _think_and_act_loop(self, max_turns=15):
        """采用强制单工具执行模式 - 彻底解决Azure OpenAI call_id不匹配问题"""
        logger.info("进入强制单工具执行Tool Calling模式...")

        for i in range(max_turns):
            logger.info(f"循环轮次 {i + 1}/{max_turns}")
            try:
                client, model_name = self._get_llm()
                request_args = {
                    "model": model_name,
                    "tools": self.tools_definitions,
                    "input": self.conversation_history,
                }
                logger.debug(
                    f"发送给LLM的请求参数:\n{json.dumps(request_args, indent=2, ensure_ascii=False)}"
                )
                response = client.responses.create(**request_args)
            except Exception as e:
                logger.error("调用LLM API时发生错误")
                logger.exception(e)
                # 快速恢复策略：直接重置并继续
                if "400" in str(e) and "call_id" in str(e):
                    logger.warning("检测到call_id不匹配错误，执行快速重置")
                    # 添加边界检查
                    if len(self.conversation_history) >= 2:
                        system_msg = self.conversation_history[0]  # 系统消息
                        user_msg = self.conversation_history[1]  # 用户请求
                        self.conversation_history = [system_msg, user_msg]
                        logger.info(
                            f"已重置对话历史，保留 {len(self.conversation_history)} 条基础消息"
                        )
                    else:
                        logger.warning("对话历史长度不足，无法重置")
                    continue
                return "抱歉，我在思考时遇到了一点问题，请您稍后再试。"

            response_message = response.output[0]
            self.conversation_history.append(
                response_message.model_dump(exclude_none=True)
            )

            tool_calls = [
                output
                for output in response.output
                if hasattr(output, "type") and output.type == "function_call"
            ]
            text_content = "".join(
                [
                    item.text
                    for output in response.output
                    if hasattr(output, "type") and output.type == "message"
                    for item in output.content
                    if hasattr(item, "type") and item.type == "output_text"
                ]
            )

            if tool_calls:
                logger.info(f"模型决定调用 {len(tool_calls)} 个工具。")
                if text_content:
                    logger.info(f"模型的中间思考过程: {text_content}")

                # 🔥 强制单工具执行策略：彻底避免多工具状态冲突
                executed_tools = []

                # 只执行第一个工具，其他工具在下一轮处理
                tool_call = tool_calls[0]
                if len(tool_calls) > 1:
                    logger.warning(
                        f"检测到 {len(tool_calls)} 个工具调用，强制执行单工具模式，仅执行: {tool_call.name}"
                    )

                function_name = tool_call.name
                function_to_call = self.tool_functions.get(function_name)

                # 检查call_id是否存在
                if not hasattr(tool_call, "call_id") or not tool_call.call_id:
                    logger.error(f"工具调用 {function_name} 缺少call_id")
                    # 不能直接continue，否则LLM会无限等待
                    observation_content = json.dumps(
                        {"error": f"工具调用 {function_name} 缺少call_id"}
                    )
                    call_id = None  # 标记为None
                else:
                    call_id = tool_call.call_id  # 保存call_id供后续使用

                if not function_to_call:
                    observation_content = f"错误: 未知的工具 '{function_name}'"
                    logger.error(observation_content)
                else:
                    try:
                        # 修复：添加JSON解析错误处理
                        json_error = False
                        try:
                            function_args = json.loads(tool_call.arguments)
                        except json.JSONDecodeError as e:
                            logger.error(
                                f"JSON解析失败: {e}, 原始数据: {tool_call.arguments}"
                            )
                            json_error = True
                            observation_content = (
                                f"错误: 工具参数JSON格式错误: {str(e)}"
                            )
                            observation = {"error": observation_content}

                        if not json_error:
                            logger.info(
                                f"准备执行工具 '{function_name}'，参数: {function_args}"
                            )

                            # 🎯 Todo检查：避免重复执行相同操作
                            should_skip, cached_result = (
                                self.todo_manager.should_skip_action(
                                    function_name, function_args
                                )
                            )

                            if should_skip:
                                logger.info(
                                    f"🔄 检测到重复操作，使用缓存结果: {function_name}"
                                )
                                observation = cached_result
                                observation_content = json.dumps(
                                    observation, ensure_ascii=False
                                )
                            else:
                                # 执行新操作
                                start_time = time.time()
                                observation = function_to_call(**function_args)
                                execution_time = time.time() - start_time

                                # 记录操作完成
                                self.todo_manager.mark_action_completed(
                                    function_name,
                                    function_args,
                                    observation,
                                    execution_time,
                                )
                                observation_content = json.dumps(
                                    observation, ensure_ascii=False
                                )

                            logger.info(
                                f"工具 '{function_name}' 的观察结果: {observation}"
                            )
                    except Exception as e:
                        logger.exception(f"执行工具 '{function_name}' 时出错")
                        observation_content = json.dumps(
                            {"status": "error", "detail": str(e)}
                        )

                # 立即添加工具输出
                output_data = {
                    "type": "function_call_output",
                    "output": observation_content,
                }
                # 只有当call_id存在时才添加
                if call_id is not None:
                    output_data["call_id"] = call_id
                self.conversation_history.append(output_data)

                logger.debug(f"已添加工具输出，call_id: {call_id}")
                executed_tools.append(function_name)

                logger.info(
                    f"本轮执行了 {len(executed_tools)} 个工具: {executed_tools}"
                )
                continue
            else:
                logger.info("未检测到工具调用，判定为最终答案。")
                return text_content
        logger.warning(f"已达到最大循环次数 {max_turns}，强制退出循环。")
        return "抱歉，经过几轮深度思考后，我仍然无法找到解决您请求的有效方法。"

    def _execute_skill(
        self, skill_name: str, args: list = [], kwargs: dict = {}
    ) -> dict:
        raise RuntimeError(
            "Legacy procedural_skill is removed. Call the MCP tool directly via tool calling."
        )


    # --- 新增的、与记忆模块一一对应的工具实现 ---
    def _query_ltm_preference(self, key: str) -> dict:
        logger.info(f"执行工具 [query_ltm_preference]: key='{key}'")

        # 🔧 修复：添加key映射逻辑，匹配实际数据库中的key格式
        key_mapping = {
            # 中文key映射
            "管理风格": "work_decision_making_style",
            "决策风格": "work_decision_making_style",
            "数据驱动": "work_decision_making_style",
            "沟通风格": "communication_style",
            "会议风格": "meeting_time_preference",
            "会议时间": "meeting_time_preference",
            "会议偏好": "meeting_time_preference",
            "风险管理": "risk_management",
            # 英文key映射（LLM常用）
            "management_style": "work_decision_making_style",
            "decision_making": "work_decision_making_style",
            "communication_style": "communication_style",
            "meeting_style": "meeting_time_preference",
            "meeting_preference": "meeting_time_preference",
            "meeting_time_preference": "meeting_time_preference",
            "risk_management": "risk_management",
            "risk_management_style": "risk_management",
            "risk_preference": "risk_management",
            # 工作计划相关
            "work_schedule": "work_schedule",
            "schedule": "work_schedule",
        }

        # 尝试映射key，如果没有映射就使用原key
        mapped_key = key_mapping.get(key, key)
        logger.info(f"🔄 Key映射: '{key}' -> '{mapped_key}'")

        payload = {
            "memory_type": "ltm_preference",
            "params": {"user_id": self.user_id, "key": mapped_key},
        }
        return call_memory_service("retrieve", payload)

    def _query_semantic_memory(self, query_text: str) -> dict:
        logger.info(f"执行工具 [query_semantic_memory]: query_text='{query_text}'")
        payload = {"memory_type": "semantic_fact", "params": {"query_text": query_text}}
        return call_memory_service("retrieve", payload)

    def _query_knowledge_graph(self, subject: str, relation: str) -> dict:
        logger.info(
            f"执行工具 [query_knowledge_graph]: subject='{subject}', relation='{relation}'"
        )
        payload = {
            "memory_type": "kg_relation",
            "params": {"subject": subject, "relation": relation},
        }
        return call_memory_service("retrieve", payload)

    def _query_stm(self, conversation_id: str = None, limit: int = 10) -> dict:
        logger.info(
            f"执行工具 [query_stm]: conversation_id='{conversation_id or self.conversation_id}', limit={limit}"
        )
        payload = {
            "memory_type": "stm",
            "params": {
                "conversation_id": conversation_id or self.conversation_id,
                "limit": limit,
            },
        }
        return call_memory_service("retrieve", payload)

    def _manage_working_memory(
        self, action: str, task_id: str, data: dict = None
    ) -> dict:
        logger.info(
            f"执行工具 [manage_working_memory]: action='{action}', task_id='{task_id}'"
        )
        if action in ["create", "update"]:
            payload = {
                "memory_type": "wm",
                "params": {"agent_id": self.agent_id, "task_id": task_id, "data": data},
            }
            return call_memory_service("store", payload)
        elif action == "retrieve":
            payload = {"memory_type": "wm", "params": {"task_id": task_id}}
            return call_memory_service("retrieve", payload)
        elif action == "clear":
            payload = {
                "memory_type": "wm",
                "params": {"agent_id": self.agent_id, "task_id": task_id},
            }
            return call_memory_service("clear", payload)
        return {"status": "error", "detail": "无效的action"}

    def _consolidate_memory(self, summary: str) -> dict:
        logger.info(f"执行工具 [consolidate_memory]: 核心内容='{summary}'")
        payload = {
            "memory_type": "semantic_fact",
            "params": {
                "text": f"任务总结: {summary}",
                "metadata": {
                    "user_id": self.user_id,
                    "type": "task_summary",
                    "timestamp": time.time(),
                },
            },
        }
        result = call_memory_service("store", payload)
        if result.get("status") == "success":
            return {"status": "success", "detail": "关键成果已成功归档。"}
        else:
            return {
                "status": "error",
                "detail": f"归档记忆时发生错误: {result.get('detail')}",
            }

    # === 项目管理专项技能实现 ===
    def _generate_gantt_chart(self, project_name=None, tasks=None, start_date=None):
        """生成项目甘特图"""
        try:
            # 导入甘特图生成技能
            import sys
            import os

            skills_path = os.path.join(os.path.dirname(__file__), "skills")
            if skills_path not in sys.path:
                sys.path.append(skills_path)

            from project_gantt_generator import execute

            # 设置默认值
            if project_name is None:
                project_name = "电商平台重构项目"

            result = execute(
                project_name=project_name, tasks=tasks, start_date=start_date
            )

            if result["success"]:
                return f"✅ 甘特图生成成功！\n\n{result['text_display']}\n\n💡 甘特图数据已生成，总工期：{result['data']['project']['total_duration']}天"
            else:
                return f"❌ 甘特图生成失败：{result['message']}"

        except Exception as e:
            logger.error(f"甘特图生成出错：{e}")
            return f"❌ 甘特图生成出错：{str(e)}"

    def _assess_project_risks(
        self, project_type=None, team_size=None, budget=None, duration_months=None
    ):
        """评估项目风险"""
        try:
            # 导入风险评估技能
            import sys
            import os

            skills_path = os.path.join(os.path.dirname(__file__), "skills")
            if skills_path not in sys.path:
                sys.path.append(skills_path)

            from project_risk_assessor import execute

            # 设置默认值（电商重构项目的参数）
            if project_type is None:
                project_type = "e-commerce"
            if team_size is None:
                team_size = 12
            if budget is None:
                budget = 200
            if duration_months is None:
                duration_months = 6

            result = execute(
                project_type=project_type,
                team_size=team_size,
                budget=budget,
                duration_months=duration_months,
            )

            if result["success"]:
                summary = result["summary"]
                return f"✅ 风险评估完成！\n\n📊 评估摘要：\n• 总风险数：{summary['total_risks']}\n• 高风险项：{summary['high_risks']}\n• 最大风险：{summary['top_risk']}\n\n{result['report_text']}"
            else:
                return f"❌ 风险评估失败：{result['message']}"

        except Exception as e:
            logger.error(f"风险评估出错：{e}")
            return f"❌ 风险评估出错：{str(e)}"

    def _create_conversation_item(self, user_input: str) -> ConversationItem:
        """创建对话项目对象

        Args:
            user_input: 用户输入内容

        Returns:
            ConversationItem: 对话项目对象
        """
        return ConversationItem(
            content=user_input, timestamp=time.time(), role="user", user_id=self.user_id
        )

    def _analyze_conversation_value(
        self, conversation_item: ConversationItem
    ) -> FilterResult:
        """分析对话价值 - 应用3级漏斗过滤器

        Args:
            conversation_item: 对话项目对象

        Returns:
            FilterResult: 过滤结果对象
        """
        # 进行3级漏斗过滤分析
        filter_result = self.conversation_filter.filter_conversation(conversation_item)

        logger.info("📈 3级漏斗分析结果:")
        logger.info(f"  过滤阶段: {filter_result.filter_stage}")
        logger.info(f"  记忆等级: Level {filter_result.memory_level}")
        logger.info(f"  置信度: {filter_result.confidence:.3f}")
        logger.info(f"  处理时间: {filter_result.processing_time:.3f}秒")
        logger.info(f"  判断理由: {filter_result.reasoning}")

        return filter_result

    def _store_level2_semantic_note(
        self, user_input: str, conversation_id: str, filter_result: FilterResult
    ) -> bool:
        """Level 2: 存储为语义记忆（对话事件/事实）

        Args:
            user_input: 用户输入
            conversation_id: 对话ID
            filter_result: 过滤结果

        Returns:
            bool: 存储是否成功
        """
        semantic_text = f"用户对话记录: {user_input}"
        payload = {
            "memory_type": "semantic_fact",
            "params": {
                "text": semantic_text,
                "metadata": {
                    "user_id": self.user_id,
                    "conversation_id": conversation_id,
                    "timestamp": time.time(),
                    "filter_confidence": filter_result.confidence,
                    "filter_stage": filter_result.filter_stage,
                },
            },
        }
        result = call_memory_service("store", payload)
        success = result.get("status") == "success"
        if success:
            logger.info("📝 Level 2转化: 成功存储为语义记忆")
        return success

    def _store_level3_preferences(self, user_input: str) -> bool:
        """Level 3: 提取并存储用户偏好

        Args:
            user_input: 用户输入

        Returns:
            bool: 存储是否成功
        """
        # 检查是否包含偏好相关关键词
        preference_keywords = ["喜欢", "偏好", "习惯", "倾向", "爱好"]
        if not any(keyword in user_input for keyword in preference_keywords):
            return False

        preference_key = f"extracted_preference_{int(time.time())}"
        preference_value = f"从对话提取: {user_input}"
        payload = {
            "memory_type": "ltm_preference",
            "params": {
                "user_id": self.user_id,
                "key": preference_key,
                "value": preference_value,
            },
        }
        result = call_memory_service("store", payload)
        success = result.get("status") == "success"
        if success:
            logger.info("⚙️  Level 3转化: 成功提取并存储用户偏好")
        return success

    def _store_level4_procedural(self, user_input: str) -> bool:
        """Level 4: 提取并存储程序性知识

        Args:
            user_input: 用户输入

        Returns:
            bool: 存储是否成功
        """
        # 检查是否包含程序性知识相关关键词
        procedural_keywords = ["流程", "步骤", "如何", "方法", "操作"]
        if not any(keyword in user_input for keyword in procedural_keywords):
            return False

        # Legacy procedural_skill storage is removed.
        # Suggested replacement: implement extracted procedures as MCP tools in a server,
        # or store them as semantic facts / documents.
        logger.info(
            "🔧 Level 4转化: procedural_skill 已移除，建议将流程写入 semantic_fact 或 ltm_doc，或升级为 MCP tool"
        )
        return False

    def _store_level5_semantic(
        self, user_input: str, filter_result: FilterResult
    ) -> bool:
        """Level 5: 存储为语义知识

        Args:
            user_input: 用户输入
            filter_result: 过滤结果

        Returns:
            bool: 存储是否成功
        """
        semantic_text = f"重要概念讨论: {user_input}"
        payload = {
            "memory_type": "semantic_fact",
            "params": {
                "text": semantic_text,
                "metadata": {
                    "source": "conversation_extraction",
                    "importance": "high",
                    "user_id": self.user_id,
                    "timestamp": time.time(),
                    "filter_confidence": filter_result.confidence,
                },
            },
        }
        result = call_memory_service("store", payload)
        success = result.get("status") == "success"
        if success:
            logger.info("🧠 Level 5转化: 成功存储为语义知识")
        return success

    def _process_conversation_to_memory(
        self, user_input: str, conversation_id: str = None
    ):
        """🧠 3级漏斗记忆转化 - 智能分析对话价值并转换为相应记忆类型

        Args:
            user_input: 用户输入内容
            conversation_id: 对话ID（可选）

        Returns:
            tuple: (filter_result, consolidation_success)
        """
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        logger.info("📊 开始3级漏斗记忆价值分析...")

        # 步骤1: 创建对话项目
        conversation_item = self._create_conversation_item(user_input)

        # 步骤2: 分析对话价值（应用3级漏斗过滤器）
        filter_result = self._analyze_conversation_value(conversation_item)

        consolidation_success = False

        # 步骤3: 根据记忆等级进行不同的存储策略
        if filter_result.memory_level == 1:
            logger.info("🗑️  Level 1判断: 对话价值较低，不做持久化存储")
            consolidation_success = True

        elif filter_result.memory_level == 2:
            # Level 2: 存储为语义记忆
            consolidation_success = self._store_level2_semantic_note(
                user_input, conversation_id, filter_result
            )

        elif filter_result.memory_level == 3:
            # Level 3: 提取用户偏好
            consolidation_success = self._store_level3_preferences(user_input)

        elif filter_result.memory_level == 4:
            # Level 4: 提取程序性知识
            consolidation_success = self._store_level4_procedural(user_input)

        elif filter_result.memory_level == 5:
            # Level 5: 存储为语义知识
            consolidation_success = self._store_level5_semantic(
                user_input, filter_result
            )

        return filter_result, consolidation_success

    def _sync_message_to_stm(self, message):
        """🔄 实时同步消息到短期记忆（带重试机制）"""
        try:
            content = f"[{message['role']}] {message['content']}"
            # 修复参数结构：role和timestamp需要作为顶级参数
            payload = {
                "memory_type": "stm",
                "params": {
                    "conversation_id": self.conversation_id,
                    "content": content,
                    "role": message["role"],
                    "timestamp": datetime.now().isoformat(),
                    "user_id": self.user_id,
                },
            }

            # 修复：添加重试机制
            max_retries = 3
            for attempt in range(max_retries):
                result = call_memory_service("store", payload)
                if result.get("status") == "success":
                    logger.debug(f"🔄 消息已同步到STM: {content[:50]}...")
                    return True
                else:
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"⚠️ STM同步失败 (尝试 {attempt + 1}/{max_retries}), 重试..."
                        )
                        time.sleep(0.5 * (attempt + 1))  # 指数退避
                    else:
                        logger.error(f"❌ STM同步最终失败: {result}")
                        return False
        except Exception as e:
            logger.error(f"❌ STM同步异常: {e}")
            return False

    def _manage_conversation_capacity(self):
        """🧠 智能容量管理 - 工作记忆与STM协调"""
        max_working_memory = 20  # 工作记忆最大容量

        if len(self.conversation_history) > max_working_memory:
            # 转移较早的对话到STM并从工作记忆移除
            overflow_count = len(self.conversation_history) - max_working_memory
            transferred_messages = []

            for i in range(overflow_count):
                old_message = self.conversation_history.pop(
                    1
                )  # 保留系统消息，从索引1开始移除
                # 确保已同步到STM
                self._sync_message_to_stm(old_message)
                transferred_messages.append(old_message)

            logger.info(f"🧠 工作记忆容量管理: 转移 {overflow_count} 条消息到STM")

        # 定期触发STM→长期记忆转化
        if len(self.conversation_history) % 10 == 0:
            self._trigger_memory_consolidation()

    def _trigger_memory_consolidation(self):
        """🔄 触发记忆整合 - STM向长期记忆转化"""
        try:
            # 获取当前对话的STM内容
            payload = {
                "memory_type": "stm",
                "params": {"conversation_id": self.conversation_id, "limit": 50},
            }
            stm_result = call_memory_service("retrieve", payload)

            if stm_result.get("status") == "success":
                stm_memories = stm_result.get("data", [])

                if stm_memories and len(stm_memories) > 10:
                    # 批量分析并转化为长期记忆
                    consolidated_content = "\n".join(
                        [
                            mem.get("content", "")
                            for mem in stm_memories
                            if mem.get("content")
                        ]
                    )

                    # 通过记忆漏斗系统自动分类和存储
                    payload = {
                        "memory_type": "semantic_fact",
                        "params": {
                            "text": f"对话整合记忆 [{self.conversation_id}]: {consolidated_content}",
                            "metadata": {
                                "conversation_id": self.conversation_id,
                                "consolidation_timestamp": datetime.now().isoformat(),
                                "source": "stm_consolidation",
                                "user_id": self.user_id,
                            },
                        },
                    }

                    result = call_memory_service("store", payload)
                    if result.get("status") == "success":
                        logger.info(
                            f"🔄 记忆整合完成: STM→长期记忆 ({len(stm_memories)} 条)"
                        )
                    else:
                        logger.warning(f"⚠️ 长期记忆存储失败: {result}")

        except Exception as e:
            logger.warning(f"⚠️ 记忆整合失败: {e}")

    # NOTE: Legacy STM keyword/relevance-based context selection helpers removed.
    # The demo now uses the framework ContextBuilder.

    def _build_enhanced_context(self):
        """Build context using the framework ContextBuilder.

        This replaces the legacy keyword/relevance heuristics and aligns the demo
        with the current architecture (STM + semantic + preferences + WM).
        """

        try:
            memory_client = MemoryClient(base_url=self.memory_service_url)
            memory_manager = MemoryManager(
                memory_client=memory_client,
                user_id=self.user_id,
                conversation_id=self.conversation_id,
            )
            builder = ContextBuilder(
                memory_manager=memory_manager,
                config={
                    # Keep demo defaults conservative; adjust via config if needed.
                    "preference_keys": [
                        "work_decision_making_style",
                        "communication_style",
                        "meeting_time_preference",
                        "risk_management",
                    ]
                },
            )
            return builder.build_enhanced_context(
                user_query=self.current_user_query,
                conversation_history=[],
                system_prompt=self._get_system_prompt(),
            )
        except Exception as e:
            logger.warning(f"⚠️ ContextBuilder 失败，回退为仅 system prompt: {e}")
            return [{"role": "system", "content": self._get_system_prompt()}]

    def _finalize_conversation_round(self, user_input: str, final_answer: str):
        """🔚 对话轮次结束处理：提取记忆并存储摘要"""
        try:
            # 提取本轮使用的记忆类型（从工具调用中获取）
            memories_used = self._extract_memories_used_in_round()

            # 构建对话摘要
            conversation_summary = {
                "round_id": self.round_id,
                "timestamp": datetime.now().isoformat(),
                "user_request": user_input,
                "final_answer": final_answer,
                "memories_used": memories_used,
                "conversation_length": len(self.conversation_history),
            }

            # 存储到STM摘要系统
            payload = {
                "memory_type": "stm",
                "params": {
                    "conversation_id": self.conversation_id,
                    "conversation_summary": conversation_summary,
                    "round_id": self.round_id,
                },
            }

            result = call_memory_service("store", payload)
            if result.get("status") == "success":
                logger.info(f"🔚 轮次 {self.round_id} 摘要已存储到STM")
            else:
                logger.warning(f"⚠️ 轮次摘要存储失败: {result}")

        except Exception as e:
            logger.warning(f"⚠️ 轮次结束处理失败: {e}")

    def _extract_memories_used_in_round(self):
        """📊 从当前轮次的对话中提取使用的记忆类型"""
        memories_used = []

        # 分析对话历史中的助手消息，查找工具调用模式
        for message in self.conversation_history:
            if message.get("role") == "assistant":
                content = message.get("content", "")
                # 检查常见的记忆操作关键词
                if "retrieve" in content or "查询" in content:
                    if "语义" in content or "semantic" in content:
                        memories_used.append("semantic_memory")
                    if "长期" in content or "ltm" in content:
                        memories_used.append("ltm_memory")
                    if "知识图谱" in content or "kg" in content:
                        memories_used.append("knowledge_graph")
                    if "程序性" in content or "procedural" in content:
                        memories_used.append("procedural_memory")
                    if "工作" in content or "wm" in content:
                        memories_used.append("working_memory")

        return list(set(memories_used))  # 去重

    def _end_conversation(self) -> dict:
        logger.info("执行工具 [end_conversation]")
        self.conversation_history = [
            {"role": "system", "content": self._get_system_prompt()}
        ]
        return {
            "status": "success",
            "message": "好的，很高兴为您的项目管理工作提供支持。",
        }


if __name__ == "__main__":
    raise SystemExit(main())
