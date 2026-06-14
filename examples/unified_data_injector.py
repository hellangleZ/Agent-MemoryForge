#!/usr/bin/env python3
"""
统一智能数据注入器 v3.0
=======================

整合了smart_data_inject.py、smart_data_inject_pm.py、inject_project_demo_data.py三个文件
基于smart_data_inject_pm.py的架构，提供完整的7层记忆系统数据注入功能

功能特性：
- 🧠 完整的7种记忆类型注入
- 📊 项目管理专用场景数据
- 🔄 智能数据变化生成
- 🧹 模板数据清理功能
- 📈 注入进度实时显示
"""

import requests
import sqlite3
import redis
import json
import time
import random
import sys
import os
from datetime import datetime, timedelta

from utils.logging_config import get_logger


logger = get_logger(__name__)


def _cli_print(msg: str) -> None:
    print(msg)
    logger.info(msg)


def _cli_error(msg: str) -> None:
    print(msg)
    logger.error(msg)


# === 配置 ===
MEMORY_SERVICE_URL = "http://127.0.0.1:8001"
EMBEDDING_SERVICE_URL = "http://127.0.0.1:7999/v1/embeddings"
USER_ID = "project_manager_alice"
AGENT_ID = "agent_project_management_assistant"


class UnifiedDataInjector:
    """统一数据注入器 - 整合所有记忆类型的数据注入功能"""

    def __init__(self):
        self.redis_client = redis.Redis(decode_responses=True)
        # 使用当前工作目录下的数据库
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ltm.db")
        self.sqlite_conn = sqlite3.connect(db_path)
        # 自动初始化数据库表结构
        self._init_database_schema()

    def _init_database_schema(self):
        """自动初始化数据库表结构，确保所有必要的字段都存在"""
        _cli_print("🔧 初始化数据库表结构...")

        # 自动修复数据库文件权限
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ltm.db")
        try:
            import stat

            if os.path.exists(db_path):
                current_mode = oct(stat.S_IMODE(os.lstat(db_path).st_mode))
                if current_mode != "0o666":
                    _cli_print(f"🔒 当前数据库权限: {current_mode}, 尝试修复为 666...")
                    try:
                        os.chmod(db_path, 0o666)
                        _cli_print("✅ 数据库权限修复成功")
                    except PermissionError as e:
                        _cli_print(f"⚠️ 权限修复失败: {e}，继续尝试操作")
                else:
                    _cli_print("✅ 数据库权限正常")
        except Exception as e:
            _cli_print(f"⚠️ 权限检查跳过: {e}")

        cursor = self.sqlite_conn.cursor()

        try:
            # 检查vector_metadata表是否存在
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='vector_metadata'"
            )
            table_exists = cursor.fetchone()

            if not table_exists:
                # 创建完整的vector_metadata表
                cursor.execute("""
                    CREATE TABLE vector_metadata (
                        vector_id INTEGER PRIMARY KEY,
                        memory_type TEXT,
                        text TEXT,
                        content TEXT,
                        metadata TEXT
                    )
                """)
                _cli_print("✅ 创建vector_metadata表")
            else:
                # 检查并添加缺失的字段
                cursor.execute("PRAGMA table_info(vector_metadata)")
                columns = [column[1] for column in cursor.fetchall()]

                if "content" not in columns:
                    cursor.execute(
                        "ALTER TABLE vector_metadata ADD COLUMN content TEXT"
                    )
                    _cli_print("✅ 添加content字段到vector_metadata表")

                if "text" not in columns:
                    cursor.execute("ALTER TABLE vector_metadata ADD COLUMN text TEXT")
                    _cli_print("✅ 添加text字段到vector_metadata表")

            # 检查ltm_preferences表是否存在（匹配内存服务的查找逻辑）
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ltm_preferences'"
            )
            if not cursor.fetchone():
                cursor.execute("""
                    CREATE TABLE ltm_preferences (
                        user_id TEXT,
                        key TEXT,
                        value TEXT,
                        updated_at REAL,
                        PRIMARY KEY (user_id, key)
                    )
                """)
                _cli_print("✅ 创建ltm_preferences表")

            # 保持兼容性，也创建preferences表
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='preferences'"
            )
            if not cursor.fetchone():
                cursor.execute("""
                    CREATE TABLE preferences (
                        user_id TEXT,
                        key TEXT,
                        value TEXT,
                        updated_at REAL,
                        PRIMARY KEY (user_id, key)
                    )
                """)
                _cli_print("✅ 创建preferences表（兼容性）")

            # 提交更改
            self.sqlite_conn.commit()
            _cli_print("✅ 数据库表结构初始化完成")

        except sqlite3.OperationalError as e:
            if "readonly database" in str(e) or "database is locked" in str(e):
                _cli_print(f"❌ 数据库操作错误: {e}")
                _cli_print("🔧 尝试修复数据库权限...")

                # 重新尝试权限修复
                try:
                    os.chmod("/aml/agent_memory/ltm.db", 0o666)
                    try:
                        os.chown("/aml/agent_memory/ltm.db", os.getuid(), os.getgid())
                    except (PermissionError, OSError):
                        pass  # chown可能失败，但chmod成功已足够
                    _cli_print("✅ 权限修复完成，请重新运行程序")
                    sys.exit(1)
                except Exception as perm_e:
                    _cli_print(f"❌ 权限修复失败: {perm_e}")
                    _cli_print("💡 请手动执行: sudo chmod 666 /aml/agent_memory/ltm.db")
                    sys.exit(1)
            else:
                raise

        except Exception as e:
            _cli_print(f"⚠️ 数据库初始化错误: {e}")
            _cli_print("💡 继续执行，某些功能可能受限")

        finally:
            cursor.close()

    def check_services(self):
        """检查所有必要服务的状态"""
        _cli_print("🔍 检查服务状态...")

        # 检查Redis
        try:
            self.redis_client.ping()
            _cli_print("✅ Redis服务: 正常")
        except Exception as e:
            _cli_print(f"❌ Redis服务: 异常 - {e}")
            return False

        # 检查内存服务API
        try:
            response = requests.get(f"{MEMORY_SERVICE_URL}/health", timeout=5)
            if response.status_code == 200:
                _cli_print("✅ 内存服务API: 正常")
            else:
                _cli_print(f"❌ 内存服务API: 异常 - 状态码{response.status_code}")
                return False
        except Exception as e:
            _cli_print(f"❌ 内存服务API: 异常 - {e}")
            return False

        # 检查Embedding服务
        try:
            response = requests.get(
                f"{EMBEDDING_SERVICE_URL.replace('/v1/embeddings', '')}/health",
                timeout=5,
            )
            if response.status_code == 200:
                _cli_print("✅ Embedding服务: 正常")
            else:
                _cli_print("⚠️ Embedding服务: 可能异常，但继续执行")
        except Exception as e:
            _cli_print(f"⚠️ Embedding服务: 可能异常 - {e}，但继续执行")

        _cli_print("✅ 服务检查完成")
        return True

    def generate_comprehensive_scenarios(self):
        """生成全面的业务场景数据（整合原有三个文件的数据）"""
            scenarios = [
                # === 项目管理核心场景 (来自smart_data_inject_pm.py) ===
                {
                    "type": "semantic",
                    "content": "电商重构项目启动会议：确定项目预算200万，周期6个月，团队12人。技术栈选择React+Node.js+MongoDB。第一个里程碑设定为2024年1月15日完成用户系统模块。",
                    "metadata": {
                        "date": "2024-01-01",
                        "type": "项目启动",
                    "event_type": "project_kickoff",
                    "importance": 0.9,
                    "category": "项目管理",
                },
                },
                {
                    "type": "semantic",
                    "content": "Sprint-1规划会议：决定采用2周Sprint周期，每日站会9:30AM，Sprint回顾会每两周五下午。用户故事拆分为32个任务，优先开发用户注册登录功能。",
                    "metadata": {
                        "date": "2024-01-15",
                        "type": "Sprint规划",
                    "event_type": "sprint_planning",
                    "sprint": "Sprint-1",
                    "importance": 0.7,
                },
                },
                {
                    "type": "semantic",
                    "content": "里程碑M1评审会议：用户系统模块提前3天完成，功能测试100%通过，性能测试达标。发现用户密码重置流程存在安全隐患，已记录为高优先级bug，分配给安全团队处理。",
                    "metadata": {
                        "date": "2024-02-01",
                        "type": "里程碑评审",
                    "event_type": "milestone_review",
                    "milestone": "M1_user_system",
                    "importance": 0.8,
                },
            },
                # === 商务会议场景 (来自smart_data_inject.py) ===
                {
                    "type": "semantic",
                    "content": "2024年Q1董事会会议：CEO提出数字化转型三年规划，预算2000万，重点投资AI和云计算基础设施。",
                    "metadata": {
                        "date": "2024-03-15",
                        "type": "董事会会议",
                    "importance": 0.9,
                    "category": "战略决策",
                },
                },
                {
                    "type": "semantic",
                    "content": "与华为技术团队的技术交流会：讨论了5G+AI解决方案，华为承诺提供专门的技术支持团队。",
                    "metadata": {
                        "date": "2024-04-10",
                        "type": "技术会议",
                    "importance": 0.7,
                    "category": "合作伙伴",
                },
                },
                {
                    "type": "semantic",
                    "content": "深圳出差安排：拜访比亚迪总部，讨论智能制造解决方案合作，住宿深圳湾1号酒店，预算12000元。",
                    "metadata": {
                        "date": "2024-06-05",
                        "type": "出差方案",
                    "location": "深圳",
                    "budget": 12000,
                    "importance": 0.6,
                },
            },
            # === 客户相关场景 ===
            {
                "type": "semantic",
                "content": "重点客户腾讯：年合作金额500万，主要业务为企业级AI解决方案，联系人张总（技术VP）。客户满意度95%，续约概率高。",
                "metadata": {
                    "type": "客户信息",
                    "category": "大客户",
                    "importance": 0.9,
                    "customer": "腾讯",
                },
            },
            {
                "type": "semantic",
                "content": "阿里云合作项目：提供云原生架构咨询服务，项目周期6个月，合同金额300万。目前进度正常，客户反馈积极。",
                "metadata": {
                    "type": "项目信息",
                    "category": "云服务",
                    "importance": 0.8,
                    "partner": "阿里云",
                },
            },
            # === 技术和流程知识 ===
            {
                "type": "semantic",
                "content": "敏捷项目管理最佳实践：1.Sprint周期2-4周 2.每日站会15分钟 3.Sprint回顾会必不可少 4.用户故事要有明确验收标准 5.技术债务要在每个Sprint中分配20%时间处理",
                "metadata": {
                    "category": "项目管理",
                    "topic": "敏捷方法论",
                    "importance": 0.9,
                    "source": "PMI标准",
                },
            },
            {
                "type": "semantic",
                "content": "代码评审标准：每个PR至少2人review，单元测试覆盖率>80%，SonarQube评分A级以上，无严重漏洞，API文档必须更新。",
                "metadata": {
                    "category": "质量管理",
                    "topic": "代码审查",
                    "importance": 0.8,
                    "source": "团队规范",
                },
            },
            {
                "type": "semantic",
                "content": "风险管理四步法：识别(Identify)→分析(Analyze)→应对(Response)→监控(Monitor)，高风险项目需要每周评估。",
                "metadata": {
                    "category": "风险管理",
                    "topic": "风险流程",
                    "importance": 0.8,
                    "source": "PMBOK",
                },
            },
            # === 政策和制度 ===
            {
                "type": "semantic",
                "content": "差旅费用标准：总监级别商务舱+五星酒店，经理级别经济舱+四星酒店，每日餐补300元。",
                "metadata": {
                    "type": "政策制度",
                    "category": "差旅管理",
                    "importance": 0.7,
                },
            },
            {
                "type": "semantic",
                "content": "项目审批流程：10万以下部门经理审批，50万以下VP审批，100万以上CEO+董事会审批。",
                "metadata": {
                    "type": "政策制度",
                    "category": "审批流程",
                    "importance": 0.8,
                },
            },
            # === 技术架构 ===
            {
                "type": "semantic",
                "content": "技术栈架构：前端React+TypeScript，后端Python+FastAPI，数据库PostgreSQL+Redis，部署Kubernetes。",
                "metadata": {
                    "type": "技术文档",
                    "category": "系统架构",
                    "importance": 0.7,
                },
            },
            {
                "type": "semantic",
                "content": "AI产品线规划：智能客服系统、数据分析平台、自动化运维工具，预计年营收增长40%。",
                "metadata": {
                    "type": "产品规划",
                    "category": "技术战略",
                    "importance": 0.8,
                },
            },
        ]

        return scenarios

    def inject_semantic_memory(self):
        """注入语义记忆：项目管理知识库、最佳实践、标准流程"""
        _cli_print("🧠 注入语义记忆 - 项目管理知识库...")

        semantic_data = [
            {
                "memory_type": "semantic_fact",
                "metadata": {
                    "category": "project_management_best_practices",
                    "topic": "agile_methodology",
                    "importance": 0.9,
                },
                "content": "敏捷项目管理最佳实践：1.Sprint周期2-4周 2.每日站会15分钟 3.Sprint回顾会必不可少 4.用户故事要有明确验收标准 5.技术债务要在每个Sprint中分配20%时间处理",
            },
            {
                "memory_type": "semantic_fact",
                "metadata": {
                    "category": "risk_management",
                    "topic": "common_risks",
                    "importance": 0.8,
                },
                "content": "电商项目常见风险：1.需求变更频繁(概率80%) 2.第三方API不稳定(概率60%) 3.性能压测不达标(概率40%) 4.数据迁移风险(概率30%) 5.安全漏洞(概率20%)",
            },
            {
                "memory_type": "semantic_fact",
                "metadata": {
                    "category": "quality_standards",
                    "topic": "code_review",
                    "importance": 0.7,
                },
                "content": "代码评审标准：1.每个PR至少2人review 2.单元测试覆盖率>80% 3.SonarQube评分A级以上 4.无严重漏洞 5.API文档必须更新",
            },
            {
                "memory_type": "semantic_fact",
                "metadata": {
                    "category": "project_standards",
                    "topic": "milestone_criteria",
                    "importance": 0.8,
                },
                "content": "项目里程碑验收标准：1.功能完整性100% 2.性能指标达标 3.安全测试通过 4.用户验收测试通过 5.文档完备 6.部署成功",
            },
            {
                "memory_type": "semantic_fact",
                "metadata": {
                    "category": "team_management",
                    "topic": "performance_metrics",
                    "importance": 0.8,
                },
                "content": "团队效率指标：开发速度(Velocity)、缺陷逃逸率(<5%)、需求变更率(<15%)、按时交付率(>90%)、代码质量评分、团队满意度调研",
            },
        ]

        for data in semantic_data:
            response = requests.post(
                f"{MEMORY_SERVICE_URL}/store",
                json={
                    "memory_type": data["memory_type"],
                    "params": {"text": data["content"], "metadata": data["metadata"]},
                },
            )
            if response.status_code == 200:
                _cli_print(f"✅ 语义记忆注入成功: {data['metadata']['topic']}")
            else:
                _cli_error(
                    f"❌ 语义记忆注入失败: {data['metadata']['topic']} - {response.text}"
                )
            time.sleep(0.1)

    def inject_event_memory(self):
        """注入事件/会议纪要：作为 semantic_fact 存储，便于 File-First + FTS 检索。"""
        _cli_print("📅 注入事件/会议纪要(semantic_fact) - 项目历史事件...")

        base_time = datetime.now() - timedelta(days=60)  # 60天前开始

        event_data = [
            {
                "memory_type": "semantic_fact",
                "timestamp": (base_time + timedelta(days=1)).isoformat(),
                "metadata": {
                    "event_type": "project_kickoff",
                    "participants": ["Alice", "Bob", "Carol", "David"],
                    "importance": 0.9,
                },
                "content": "电商重构项目启动会议：确定项目预算200万，周期6个月，团队12人。技术栈选择React+Node.js+MongoDB。第一个里程碑设定为2024年1月15日完成用户系统模块。",
            },
            {
                "memory_type": "semantic_fact",
                "timestamp": (base_time + timedelta(days=15)).isoformat(),
                "metadata": {
                    "event_type": "sprint_planning",
                    "sprint": "Sprint-1",
                    "importance": 0.7,
                },
                "content": "Sprint-1规划会议：决定采用2周Sprint周期，每日站会9:30AM，Sprint回顾会每两周五下午。用户故事拆分为32个任务，优先开发用户注册登录功能。",
            },
            {
                "memory_type": "semantic_fact",
                "timestamp": (base_time + timedelta(days=30)).isoformat(),
                "metadata": {
                    "event_type": "milestone_review",
                    "milestone": "M1_user_system",
                    "importance": 0.8,
                },
                "content": "里程碑M1评审会议：用户系统模块提前3天完成，功能测试100%通过，性能测试达标。发现用户密码重置流程存在安全隐患，已记录为高优先级bug，分配给安全团队处理。",
            },
            {
                "memory_type": "semantic_fact",
                "timestamp": (base_time + timedelta(days=45)).isoformat(),
                "metadata": {
                    "event_type": "risk_assessment",
                    "risk_level": "high",
                    "importance": 0.9,
                },
                "content": "风险评估会议：识别出支付API集成风险。第三方支付平台通知将在2周后升级API版本，旧版本3个月后停用。已制定应对策略：立即启动API升级适配，分配2名开发人员专项处理。",
            },
            {
                "memory_type": "semantic_fact",
                "timestamp": (base_time + timedelta(days=50)).isoformat(),
                "metadata": {
                    "event_type": "team_retrospective",
                    "sprint": "Sprint-3",
                    "importance": 0.6,
                },
                "content": "Sprint-3回顾会议：团队反馈代码评审效率低，平均PR等待时间3天。决定引入自动化代码检查工具，设置评审超时自动提醒。Bob提出MongoDB查询性能优化建议，已采纳。",
            },
        ]

        for data in event_data:
            response = requests.post(
                f"{MEMORY_SERVICE_URL}/store",
                json={
                    "memory_type": data["memory_type"],
                    "params": {"text": data["content"], "metadata": data["metadata"]},
                },
            )
            if response.status_code == 200:
                _cli_print(f"✅ 情节记忆注入成功: {data['metadata']['event_type']}")
            else:
                _cli_error(
                    f"❌ 情节记忆注入失败: {data['metadata']['event_type']} - {response.text}"
                )
            time.sleep(0.1)

    def inject_ltm_preference(self):
        """注入长期偏好：用户个人管理风格、会议偏好、工作习惯"""
        _cli_print("💝 注入长期偏好 - 项目经理个人偏好...")

        # 使用与项目管理demo相匹配的key命名
        preference_data = [
            {
                "key": "work_decision_making_style",  # 对应"管理风格"、"决策风格"、"数据驱动"
                "value": "Alice的管理风格：1.重视团队自主性，不喜欢微观管理 2.每周一对一沟通了解团队成员状态 3.鼓励创新和试错 4.重视工作生活平衡 5.偏好数据驱动的决策",
            },
            {
                "key": "communication_style",  # 对应"沟通风格"
                "value": "Alice的沟通偏好：1.紧急事务直接电话 2.日常沟通优先Slack 3.正式决策必须邮件确认 4.喜欢可视化图表展示数据 5.重要信息要有书面记录",
            },
            {
                "key": "meeting_time_preference",  # 对应"会议风格"、"会议时间"、"会议偏好"
                "value": "Alice偏好简洁高效的会议：1.会议时长控制在30分钟内 2.提前发送议程 3.会议必须有明确结论和行动项 4.周五下午不安排会议 5.喜欢用白板画图说明复杂问题",
            },
            {
                "key": "work_schedule",
                "value": "Alice的工作习惯：1.上午9点到达办公室 2.深度工作时间是上午10-12点 3.午休时间不接受会议安排 4.下午主要处理团队沟通和评审 5.晚上7点后不处理工作邮件",
            },
            {
                "key": "risk_management",
                "value": "Alice的风险管理偏好：1.保守型风险偏好，优先保证质量和进度 2.设置20%缓冲时间 3.重要决策需要数据支撑 4.定期风险评估会议 5.制定详细的应急预案",
            },
        ]

        success_count = 0
        for data in preference_data:
            try:
                response = requests.post(
                    f"{MEMORY_SERVICE_URL}/store",
                    json={
                        "memory_type": "ltm_preference",
                        "params": {
                            "user_id": USER_ID,
                            "key": data["key"],
                            "value": data["value"],
                        },
                    },
                )
                if response.status_code == 200:
                    _cli_print(f"✅ 长期偏好注入成功: {data['key']}")
                    success_count += 1
                else:
                    _cli_error(f"❌ 长期偏好注入失败: {data['key']} - {response.text}")
            except Exception as e:
                logger.exception("长期偏好注入异常: %s", data["key"])
                _cli_error(f"❌ 长期偏好注入异常: {data['key']} - {e}")
            time.sleep(0.1)

        _cli_print(f"📊 LTM偏好注入完成: {success_count}/5 成功")

        # 验证注入结果
        _cli_print("\n🔍 验证注入结果...")
        for data in preference_data:
            try:
                response = requests.post(
                    f"{MEMORY_SERVICE_URL}/retrieve",
                    json={
                        "memory_type": "ltm_preference",
                        "params": {"user_id": USER_ID, "key": data["key"]},
                    },
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get("data"):
                        _cli_print(f"✅ 验证成功: {data['key']} - 数据已存储")
                    else:
                        _cli_print(f"⚠️ 验证失败: {data['key']} - 数据为空")
                else:
                    _cli_error(f"❌ 验证错误: {data['key']} - {response.text}")
            except Exception as e:
                logger.exception("验证异常: %s", data["key"])
                _cli_error(f"❌ 验证异常: {data['key']} - {e}")
            time.sleep(0.1)

    def inject_knowledge_graph(self):
        """注入知识图谱：团队成员关系、技能、协作网络"""
        _cli_print("🕸️ 注入知识图谱 - 团队关系网络...")

        knowledge_graph_data = [
            {
                "subject": "Bob Chen",
                "relation": "specializes_in",
                "obj": "React, TypeScript, Vue.js",
            },
            {"subject": "Bob Chen", "relation": "leads", "obj": "前端开发团队(4人)"},
            {"subject": "Bob Chen", "relation": "reports_to", "obj": "Alice"},
            {
                "subject": "Carol Wang",
                "relation": "specializes_in",
                "obj": "用户体验设计, 原型设计, 设计系统",
            },
            {
                "subject": "Carol Wang",
                "relation": "collaborates_with",
                "obj": "Bob(前端), David(产品)",
            },
            {
                "subject": "David Liu",
                "relation": "specializes_in",
                "obj": "Node.js, MongoDB, Redis, Docker",
            },
            {"subject": "David Liu", "relation": "leads", "obj": "后端开发团队(3人)"},
            {"subject": "前端开发", "relation": "depends_on", "obj": "后端API接口"},
            {"subject": "支付模块", "relation": "depends_on", "obj": "第三方支付平台"},
            {
                "subject": "Eva Zhang",
                "relation": "specializes_in",
                "obj": "自动化测试, 性能测试, 安全测试",
            },
        ]

        for data in knowledge_graph_data:
            response = requests.post(
                f"{MEMORY_SERVICE_URL}/store",
                json={
                    "memory_type": "kg_relation",
                    "params": {
                        "subject": data["subject"],
                        "relation": data["relation"],
                        "obj": data["obj"],
                    },
                },
            )
            if response.status_code == 200:
                _cli_print(
                    f"✅ 知识图谱注入成功: {data['subject']} -> {data['relation']} -> {data['obj']}"
                )
            else:
                _cli_error(
                    f"❌ 知识图谱注入失败: {data['subject']} -> {data['relation']} - {response.text}"
                )
            time.sleep(0.1)

    def inject_working_memory(self):
        """注入工作记忆：当前进行中的复杂任务"""
        _cli_print("🧮 注入工作记忆 - 当前任务跟踪...")

        working_memory_data = [
            {
                "memory_type": "working_memory",
                "metadata": {
                    "task_id": "sprint_planning_current",
                    "task_type": "multi_step_planning",
                    "status": "in_progress",
                    "importance": 0.9,
                },
                "content": "当前Sprint-4规划任务：1.已完成：需求梳理，技术方案评审 2.进行中：用户故事拆分(40%完成) 3.待完成：工作量评估，任务分配，Sprint目标确定 4.风险点：商品推荐算法复杂度超预期",
            },
            {
                "memory_type": "working_memory",
                "metadata": {
                    "task_id": "performance_optimization",
                    "task_type": "technical_investigation",
                    "status": "investigation",
                    "importance": 0.8,
                },
                "content": "性能优化调研任务：1.已识别：首页加载时间3.2秒，目标<2秒 2.分析中：数据库查询瓶颈，Redis缓存命中率 3.待测试：CDN加速方案，图片压缩优化 4.负责人：David Liu",
            },
            {
                "memory_type": "working_memory",
                "metadata": {
                    "task_id": "api_integration_payment",
                    "task_type": "integration_task",
                    "status": "blocked",
                    "importance": 0.9,
                },
                "content": "支付API集成任务：1.当前状态：等待第三方API文档更新 2.已完成：技术方案设计，开发环境搭建 3.阻塞因素：支付平台API升级延期 4.应对措施：联系技术支持，准备备用方案",
            },
        ]

        for data in working_memory_data:
            response = requests.post(
                f"{MEMORY_SERVICE_URL}/store",
                json={
                    "memory_type": "wm",
                    "params": {
                        "agent_id": AGENT_ID,
                        "task_id": data["metadata"]["task_id"],
                        "data": {
                            "content": data["content"],
                            "metadata": data["metadata"],
                        },
                    },
                },
            )
            if response.status_code == 200:
                _cli_print(f"✅ 工作记忆注入成功: {data['metadata']['task_id']}")
            else:
                _cli_error(
                    f"❌ 工作记忆注入失败: {data['metadata']['task_id']} - {response.text}"
                )
            time.sleep(0.1)

    def inject_stm_data(self):
        """为STM注入一些对话历史数据"""
        _cli_print("💭 注入STM数据 - 对话历史...")

        stm_data = [
            {
                "role": "user",
                "content": "你好，我想了解一下当前项目的整体进展情况",
                "timestamp": (datetime.now() - timedelta(minutes=30)).isoformat(),
            },
            {
                "role": "assistant",
                "content": "您好Alice！根据项目数据，电商重构项目目前进展良好：已完成用户系统模块，正在进行商品管理模块开发，整体进度符合预期。有什么具体想了解的吗？",
                "timestamp": (datetime.now() - timedelta(minutes=29)).isoformat(),
            },
            {
                "role": "user",
                "content": "下周的Sprint规划会议准备得怎么样了？",
                "timestamp": (datetime.now() - timedelta(minutes=10)).isoformat(),
            },
            {
                "role": "assistant",
                "content": "Sprint-4规划会议准备中：需求梳理和技术方案评审已完成，目前正在进行用户故事拆分（40%完成）。还需要完成工作量评估和任务分配。有个风险点需要注意：商品推荐算法的复杂度可能超出预期。",
                "timestamp": (datetime.now() - timedelta(minutes=9)).isoformat(),
            },
        ]

        # 注入STM数据
        try:
            conversation_id = f"{USER_ID}_{AGENT_ID}_conversation_default"

            for msg in stm_data:
                stm_key = f"stm:{conversation_id}"
                self.redis_client.lpush(stm_key, json.dumps(msg))

            self.redis_client.expire(stm_key, 3600)  # 1小时过期
            _cli_print(f"✅ STM数据注入成功: {len(stm_data)}条对话记录")

        except Exception as e:
            logger.exception("STM数据注入失败")
            _cli_error(f"❌ STM数据注入失败: {e}")

    def inject_comprehensive_scenarios(self, num_scenarios=30):
        """注入综合场景数据（整合所有场景类型）"""
        base_scenarios = self.generate_comprehensive_scenarios()

        _cli_print(f"📊 开始注入 {num_scenarios} 条综合场景数据...")

        for i in range(num_scenarios):
            # 随机选择基础场景并进行变化
            base = random.choice(base_scenarios)

            # 生成变化的内容
            content = self._generate_variation(base["content"], i)
            metadata = base["metadata"].copy()
            metadata["injection_id"] = f"unified_inject_{i}"
            metadata["created_at"] = time.time()
            metadata["user_id"] = USER_ID

            try:
                memory_type = base["type"]
                if memory_type == "semantic":
                    response = requests.post(
                        f"{MEMORY_SERVICE_URL}/store",
                        json={
                            "memory_type": "semantic_fact",
                            "params": {"text": content, "metadata": metadata},
                        },
                    )

                if response.status_code == 200:
                    _cli_print(
                        f"✅ 成功注入 {i + 1}/{num_scenarios}: {content[:60]}..."
                    )
                else:
                    _cli_error(f"❌ 注入失败 {i + 1}: {response.text}")

            except Exception as e:
                logger.exception("注入错误 %s", i + 1)
                _cli_error(f"❌ 注入错误 {i + 1}: {e}")

            # 避免过快请求
            time.sleep(0.1)

    def _generate_variation(self, base_content, index):
        """基于基础内容生成变化"""

        # 公司名称变化
        companies = [
            "腾讯",
            "阿里巴巴",
            "字节跳动",
            "美团",
            "小米",
            "华为",
            "百度",
            "京东",
            "网易",
            "滴滴",
        ]
        locations = [
            "北京",
            "上海",
            "深圳",
            "杭州",
            "广州",
            "成都",
            "武汉",
            "南京",
            "西安",
            "苏州",
        ]
        amounts = [
            "100万",
            "200万",
            "300万",
            "500万",
            "800万",
            "1000万",
            "1500万",
            "2000万",
        ]

        content = base_content

        # 随机替换一些关键词
        if index % 3 == 0:
            for company in companies:
                if company in content:
                    new_company = random.choice([c for c in companies if c != company])
                    content = content.replace(company, new_company, 1)
                    break

        if index % 4 == 0:
            for location in locations:
                if location in content:
                    new_location = random.choice(
                        [
                            candidate_location
                            for candidate_location in locations
                            if candidate_location != location
                        ]
                    )
                    content = content.replace(location, new_location, 1)
                    break

        if index % 5 == 0:
            for amount in amounts:
                if amount in content:
                    new_amount = random.choice([a for a in amounts if a != amount])
                    content = content.replace(amount, new_amount, 1)
                    break

        return content

    def clean_template_data(self):
        """清理模板化数据"""
        _cli_print("🧹 开始清理模板化数据...")

        try:
            cursor = self.sqlite_conn.cursor()

            # 检查表是否存在
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='vector_metadata'"
            )
            if not cursor.fetchone():
                _cli_print("⚠️ vector_metadata表不存在，跳过清理")
                cursor.close()
                return

            # 查找模板数据
            cursor.execute(
                "SELECT vector_id FROM vector_metadata WHERE content LIKE '%{%}%'"
            )
            template_ids = [row[0] for row in cursor.fetchall()]

            _cli_print(f"找到 {len(template_ids)} 条模板数据")

            if len(template_ids) > 0:
                # 删除数据库记录
                placeholders = ",".join(["?" for _ in template_ids])
                cursor.execute(
                    f"DELETE FROM vector_metadata WHERE vector_id IN ({placeholders})",
                    template_ids,
                )
                self.sqlite_conn.commit()

                _cli_print(f"✅ 已删除 {len(template_ids)} 条模板数据")
                _cli_print("⚠️  建议重新运行 quick_fix.py 重建向量索引以同步删除")

            cursor.close()

        except Exception as e:
            logger.exception("清理模板数据跳过")
            _cli_print(f"⚠️ 清理模板数据跳过: {e}")
            _cli_print("💡 这是正常的，表结构将在首次数据注入时自动创建")

    def inject_all_memory_types(self):
        """注入所有7种记忆类型的数据"""
        _cli_print("🚀 开始统一数据注入流程...")
        _cli_print(f"👤 用户: {USER_ID}")
        _cli_print(f"🤖 助手: {AGENT_ID}")
        _cli_print("=" * 60)

        # 检查服务状态
        if not self.check_services():
            _cli_error("❌ 服务检查失败，请启动相关服务后重试")
            return

        _cli_print("\n" + "=" * 50)

        try:
            # 1. 清理旧的模板数据
            self.clean_template_data()
            _cli_print("\n" + "=" * 50)

            # 2. 注入语义记忆
            self.inject_semantic_memory()
            _cli_print("\n" + "=" * 50)

            # 3. 注入事件/会议纪要(semantic_fact)
            self.inject_event_memory()
            _cli_print("\n" + "=" * 50)

            # 4. 注入长期偏好
            self.inject_ltm_preference()
            _cli_print("\n" + "=" * 50)

            # 5. 注入知识图谱
            self.inject_knowledge_graph()
            _cli_print("\n" + "=" * 50)

            # 6. 注入工作记忆
            self.inject_working_memory()
            _cli_print("\n" + "=" * 50)

            # 7. 注入STM数据
            self.inject_stm_data()
            _cli_print("\n" + "=" * 50)

            # 8. 注入综合场景数据
            self.inject_comprehensive_scenarios(25)

            _cli_print("\n🎉 统一数据注入完成！")
            _cli_print("📊 已注入所有7种记忆类型的数据")
            _cli_print(
                "💡 现在可以运行 project_management_demo_real.py 体验完整的记忆系统！"
            )

        except Exception as e:
            logger.exception("数据注入过程中出现错误")
            _cli_print(f"❌ 数据注入过程中出现错误: {e}")
            sys.exit(1)


def main():
    """主函数：选择注入模式"""
    _cli_print("=== 统一智能数据注入器 v3.0 ===")
    _cli_print(
        "整合了smart_data_inject.py、smart_data_inject_pm.py、inject_project_demo_data.py"
    )
    _cli_print("基于smart_data_inject_pm.py架构，提供完整的7层记忆系统数据注入\n")

    _cli_print("请选择注入模式：")
    _cli_print("1. 完整注入 - 所有7种记忆类型 (推荐)")
    _cli_print("2. 仅注入语义记忆")
    _cli_print("3. 仅注入事件/会议纪要(semantic_fact)")
    _cli_print("4. 仅注入LTM偏好 (修复后)")
    _cli_print("5. 仅注入知识图谱")
    _cli_print("6. 仅注入工作记忆")
    _cli_print("7. 仅注入STM数据")
    _cli_print("8. 仅注入综合场景")
    _cli_print("9. 仅清理模板数据")

    choice = input("\n请输入选择 (1-9): ").strip()

    injector = UnifiedDataInjector()

    if choice == "1":
        injector.inject_all_memory_types()
    elif choice == "2":
        injector.inject_semantic_memory()
    elif choice == "3":
        injector.inject_event_memory()
    elif choice == "4":
        injector.inject_ltm_preference()
    elif choice == "5":
        injector.inject_knowledge_graph()
    elif choice == "6":
        injector.inject_working_memory()
    elif choice == "7":
        injector.inject_stm_data()
    elif choice == "8":
        injector.inject_comprehensive_scenarios(30)
    elif choice == "9":
        injector.clean_template_data()
    else:
        _cli_print("❌ 无效选择，执行完整注入...")
        injector.inject_all_memory_types()


if __name__ == "__main__":
    main()
