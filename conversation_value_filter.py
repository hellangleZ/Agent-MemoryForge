#!/usr/bin/env python3
"""
对话价值判断漏斗过滤器
========================

3级漏斗化过滤架构：
Level 1: 快速规则过滤 (90%案例) - 毫秒级响应
Level 2: 关键词权重评分 (8%案例) - 秒级响应
Level 3: LLM精准分析 (2%案例) - 10秒级响应

目标：实现高效、准确、低成本的对话价值评估
"""

import re
import json
import time
import os
import hashlib
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field
from openai import OpenAI
from utils.logging_config import get_logger

logger = get_logger(__name__)

# 缓存配置
CACHE_MAX_SIZE = 1000  # 最大缓存条目数
CACHE_TTL = 3600  # 缓存过期时间(秒) - 1小时


@dataclass
class ConversationItem:
    """对话项数据结构"""

    content: str
    role: str
    # Allow callers (and tests) to omit timestamp; default to "now".
    timestamp: float = field(default_factory=lambda: time.time())
    user_id: str = "unknown"
    context: Optional[Dict[str, Any]] = None


@dataclass
class FilterResult:
    """过滤结果数据结构"""

    memory_level: int  # 1-5级记忆等级
    confidence: float  # 置信度 0-1
    reasoning: str  # 判断理由
    processing_time: float  # 处理时间(秒)
    filter_stage: str  # 过滤阶段标识


class ConversationValueFilter:
    """对话价值3级漏斗过滤器"""

    def __init__(self):
        # 统计计数器
        self.stats = {
            "total_processed": 0,
            "level1_filtered": 0,  # 快速规则过滤
            "level2_filtered": 0,  # 关键词评分过滤
            "level3_analyzed": 0,  # LLM深度分析
            "processing_times": [],
            "cache_hits": 0,  # 缓存命中次数
        }

        # LRU缓存
        self._cache = {}
        self._cache_timestamps = {}

        # Level 1: 快速规则过滤模式
        self.quick_patterns = self._build_quick_patterns()

        # Level 2: 关键词权重配置
        self.keyword_weights = self._build_keyword_weights()

        # 初始化Azure OpenAI客户端
        try:
            api_key = os.getenv("AZURE_OPENAI_API_KEY")
            base_url = os.getenv("AZURE_OPENAI_ENDPOINT")
            self.model_name = os.getenv("AZURE_OPENAI_DEPLOYMENT")
            if not all([api_key, base_url, self.model_name]):
                raise ValueError("❌ Azure OpenAI 配置不完整")
            self.azure_client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                default_query={"api-version": "preview"},
                timeout=30.0,
            )
            self.llm_available = True
            logger.info("Azure OpenAI client initialized")
        except Exception as e:
            # Missing config is expected in unit tests / local dev unless explicitly set.
            logger.debug("Azure OpenAI not configured/available: %s", e)
            self.azure_client = None
            self.llm_available = False

    def _get_cache_key(self, content: str) -> str:
        """生成缓存键"""
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def _get_from_cache(self, cache_key: str) -> Optional[FilterResult]:
        """从缓存获取结果"""
        # 用 .get 而非 "in + []"，避免并发下 check-then-act 触发 KeyError
        ts = self._cache_timestamps.get(cache_key)
        if ts is not None:
            if time.time() - ts < CACHE_TTL:
                self.stats["cache_hits"] += 1
                return self._cache.get(cache_key)
            # 过期，删除（pop 容忍并发已删除）
            self._cache.pop(cache_key, None)
            self._cache_timestamps.pop(cache_key, None)
        return None

    def _save_to_cache(self, cache_key: str, result: FilterResult):
        """保存结果到缓存"""
        # 如果缓存已满，删除最旧的条目
        if len(self._cache) >= CACHE_MAX_SIZE and self._cache_timestamps:
            oldest_key = min(
                self._cache_timestamps.keys(), key=lambda k: self._cache_timestamps[k]
            )
            self._cache.pop(oldest_key, None)
            self._cache_timestamps.pop(oldest_key, None)

        self._cache[cache_key] = result
        self._cache_timestamps[cache_key] = time.time()

    def _build_quick_patterns(self) -> Dict[int, List[str]]:
        """构建快速规则模式库"""
        return {
            # Level 1: 丢弃 - 日常闲聊、无意义内容
            1: [
                r"^(哈{2,}|呵{2,}|嘿{2,})",  # 笑声
                r"^(嗯{1,3}|额{1,3}|呃{1,3})$",  # 语气词
                r"^(好的{1,2}|知道了|收到|明白了?)$",  # 简单确认
                r"^[!！。.，,、？?]{1,5}$",  # 纯标点
                r"^(再见|拜拜|88|下次见)$",  # 告别
                r"(天气|吃饭了吗|在吗|忙吗)(?!.*工作)",  # 日常寒暄(非工作)
                r"^.{1,3}$",  # 超短内容
                r"^(谢谢|thank|thx)$",  # 简单感谢
            ],
            # Level 2: 情景记忆 - 具体事件、时间地点
            2: [
                r"(昨天|今天|明天|后天|上周|下周|上月|下月)",  # 时间引用
                r"(会议|meeting|讨论|汇报|presentation)",  # 会议事件
                r"(北京|上海|深圳|广州|出差|travel|flight)",  # 地点事件
                r"(签约|合同|contract|客户|拜访)",  # 商务事件
                r"(培训|training|学习|workshop)",  # 学习事件
                r"(发布|launch|上线|go-live)",  # 产品事件
            ],
            # Level 3: 偏好记忆 - 个人喜好、习惯模式
            3: [
                r"(喜欢|偏好|习惯|通常|一般)",  # 偏好表达
                r"(不要|避免|不喜欢|讨厌)",  # 负面偏好
                r"(每次|总是|经常|很少|从不)",  # 频率模式
                r"(提醒|remind|通知|notify)",  # 提醒偏好
                r"(格式|format|风格|style)",  # 格式偏好
                r"(时间|timing|schedule|安排)",  # 时间偏好
            ],
            # Level 4: 程序记忆 - 工作流程、操作步骤
            4: [
                r"(流程|process|步骤|step|workflow)",  # 流程关键词
                r"(如何|怎么|how to|方法|method)",  # 方法询问
                r"(操作|operation|执行|execute)",  # 操作描述
                r"(检查|check|验证|validate|测试)",  # 验证流程
                r"(配置|config|设置|setup)",  # 配置流程
                r"(部署|deploy|发布|release)",  # 部署流程
            ],
            # Level 5: 语义记忆 - 知识性内容、概念定义
            5: [
                r"(什么是|定义|definition|概念|concept)",  # 概念询问
                r"(架构|architecture|设计|design)",  # 架构知识
                r"(原理|principle|机制|mechanism)",  # 原理知识
                r"(标准|standard|规范|specification)",  # 标准规范
                r"(算法|algorithm|技术|technology)",  # 技术知识
                r"(策略|strategy|方针|policy)",  # 策略知识
            ],
        }

    def _build_keyword_weights(self) -> Dict[str, Dict[str, float]]:
        """构建关键词权重矩阵"""
        return {
            # 时间维度权重
            "temporal": {
                "紧急": 2.0,
                "urgent": 2.0,
                "立即": 2.0,
                "asap": 2.0,
                "今天": 1.5,
                "明天": 1.3,
                "本周": 1.2,
                "下周": 1.1,
                "上月": 0.8,
                "去年": 0.6,
                "历史": 0.5,
            },
            # 人员维度权重
            "personnel": {
                "CEO": 3.0,
                "董事长": 3.0,
                "总裁": 2.8,
                "CTO": 2.5,
                "CFO": 2.5,
                "COO": 2.5,
                "VP": 2.2,
                "副总": 2.2,
                "总监": 2.0,
                "经理": 1.5,
                "主管": 1.3,
                "员工": 1.0,
            },
            # 事件维度权重
            "events": {
                "董事会": 3.0,
                "股东大会": 3.0,
                "战略会议": 2.8,
                "产品发布": 2.5,
                "重大合同": 2.5,
                "融资": 2.5,
                "项目启动": 2.0,
                "客户会议": 1.8,
                "培训": 1.2,
                "日常会议": 1.0,
                "闲聊": 0.3,
                "寒暄": 0.2,
            },
            # 结果维度权重
            "outcomes": {
                "决策": 2.5,
                "签约": 2.5,
                "成功": 2.0,
                "完成": 1.8,
                "失败": 1.8,
                "延期": 1.5,
                "取消": 1.2,
                "讨论": 1.0,
                "了解": 0.8,
                "考虑": 0.6,
            },
            # 商业价值权重
            "business_value": {
                "收入": 2.8,
                "利润": 2.8,
                "成本": 2.5,
                "预算": 2.2,
                "投资": 2.0,
                "客户": 1.8,
                "市场": 1.5,
                "竞争": 1.5,
                "品牌": 1.3,
                "文化": 1.0,
                "福利": 0.8,
            },
        }

    def filter_conversation(self, conversation: ConversationItem) -> FilterResult:
        """
        3级漏斗过滤主函数（带缓存）

        Args:
            conversation: 对话内容

        Returns:
            FilterResult: 过滤结果
        """
        # 检查缓存
        cache_key = self._get_cache_key(conversation.content)
        cached_result = self._get_from_cache(cache_key)
        if cached_result is not None:
            return cached_result

        start_time = time.time()
        self.stats["total_processed"] += 1

        # Level 1: 快速规则过滤 (目标: 90%案例)
        level1_result = self._level1_quick_filter(conversation)
        if level1_result:
            self.stats["level1_filtered"] += 1
            processing_time = time.time() - start_time
            self.stats["processing_times"].append(processing_time)

            result = FilterResult(
                memory_level=level1_result,
                confidence=0.95,  # 规则匹配高置信度
                reasoning=f"Level1快速规则匹配: {self._get_pattern_match_reason(conversation.content, level1_result)}",
                processing_time=processing_time,
                filter_stage="Level1_QuickRule",
            )
            self._save_to_cache(cache_key, result)
            return result

        # Level 2: 关键词权重评分 (目标: 8%案例)
        level2_result = self._level2_keyword_scoring(conversation)
        if level2_result:
            self.stats["level2_filtered"] += 1
            processing_time = time.time() - start_time
            self.stats["processing_times"].append(processing_time)

            result = FilterResult(
                memory_level=level2_result["level"],
                confidence=level2_result["confidence"],
                reasoning=f"Level2关键词评分: {level2_result['reasoning']}",
                processing_time=processing_time,
                filter_stage="Level2_KeywordScore",
            )
            self._save_to_cache(cache_key, result)
            return result

        # Level 3: LLM精准分析 (目标: 2%案例)
        self.stats["level3_analyzed"] += 1
        level3_result = self._level3_llm_analysis(conversation)
        processing_time = time.time() - start_time
        self.stats["processing_times"].append(processing_time)

        result = FilterResult(
            memory_level=level3_result["level"],
            confidence=level3_result["confidence"],
            reasoning=f"Level3LLM分析: {level3_result['reasoning']}",
            processing_time=processing_time,
            filter_stage="Level3_LLMAnalysis",
        )
        self._save_to_cache(cache_key, result)
        return result

    def _level1_quick_filter(self, conversation: ConversationItem) -> Optional[int]:
        """Level 1: 快速规则过滤 - 只处理明确垃圾"""
        content = conversation.content.strip()

        # 只处理明确的垃圾内容，不做复杂分类
        garbage_patterns = [
            r"^(哈{2,}|呵{2,}|嘿{2,})",  # 笑声
            r"^(嗯{1,3}|额{1,3}|呃{1,3})$",  # 语气词
            r"^(好的{1,2}|知道了|收到|明白了?)$",  # 简单确认
            r"^[!！。.，,、？?]{1,5}$",  # 纯标点
            r"^(再见|拜拜|88|下次见)$",  # 告别
            r"(天气|吃饭了吗|在吗|忙吗)(?!.*工作)",  # 日常寒暄(非工作)
            r"^.{1,3}$",  # 超短内容
            r"^(谢谢|thank|thx)$",  # 简单感谢
        ]

        for pattern in garbage_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return 1  # 垃圾，直接丢弃

        return None  # 无法确定，交给后续阶段处理

    def _level2_keyword_scoring(self, conversation: ConversationItem) -> Dict[str, Any]:
        """Level 2: LLM轻量分析 - 快速分类"""
        try:
            # 构建轻量级LLM分析提示词
            prompt = f"""分析对话记忆价值等级(1-5):

对话内容: "{conversation.content}"

等级定义:
1-垃圾: 无意义闲聊、简单确认
2-事件: 具体事件、时间地点、会议记录  
3-偏好: 个人习惯、喜好、工作风格
4-流程: 操作步骤、工作流程、方法论
5-知识: 概念定义、技术原理、深度思考

要求: 只返回JSON格式 {{"level": 数字, "confidence": 0-1小数, "reasoning": "简短理由"}}"""

            # 调用LLM API
            llm_result = self._call_llm_api(prompt, simple=True)
            if llm_result:
                return llm_result

        except Exception as e:
            logger.warning("Level2 LLM analysis failed; falling back: %s", e)

        # LLM失败时回退到关键词评分
        return self._keyword_scoring_fallback(conversation)

    def _level3_llm_analysis(self, conversation: ConversationItem) -> Dict[str, Any]:
        """Level 3: LLM深度分析 - 复杂语义理解"""
        try:
            # 构建详细的LLM分析提示词
            prompt = f"""请深度分析以下对话的记忆价值:

对话内容: "{conversation.content}"
对话角色: {conversation.role}
用户ID: {conversation.user_id}
时间: {datetime.fromtimestamp(conversation.timestamp)}

请从以下维度进行深度分析:
1. 语义复杂度和隐含信息
2. 长期记忆价值评估
3. 与用户画像的关联性
4. 情感色彩和意图分析
5. 潜在的知识提取可能性

记忆等级定义:
1级-丢弃: 日常闲聊、无意义内容、简单确认
2级-情景: 具体事件、时间地点、会议记录、任务安排
3级-偏好: 个人习惯、喜好模式、工作风格、价值观
4级-程序: 工作流程、操作步骤、方法论、经验总结
5级-语义: 知识概念、技术原理、战略思考、深度洞察

要求: 返回详细JSON格式分析结果
{{"level": 数字, "confidence": 0-1小数, "reasoning": "详细分析理由", "extracted_info": {{"key_entities": [], "relations": [], "insights": ""}}}}"""

            # 调用LLM API进行深度分析
            llm_result = self._call_llm_api(prompt, simple=False)
            if llm_result:
                return llm_result

        except Exception as e:
            logger.warning("Level3 LLM analysis failed; falling back: %s", e)

        # LLM失败时回退到启发式分析
        return self._heuristic_analysis(conversation)

    def _call_llm_api(self, prompt: str, simple: bool = True) -> Dict[str, Any]:
        """调用Azure OpenAI进行分析"""
        if not self.llm_available:
            logger.debug("Azure OpenAI unavailable; skipping LLM call")
            return None

        try:
            # 根据simple参数选择不同的系统提示
            if simple:
                system_prompt = "你是一个对话价值评估专家,需要快速准确地评估对话的记忆价值等级。返回简洁的JSON格式结果。"
            else:
                system_prompt = "你是一个高级语义分析专家,具备深度理解对话内容的能力。请进行详细的记忆价值分析,包括隐含信息挖掘和知识提取。"

            # 构建Azure OpenAI请求
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]

            # 使用Azure OpenAI responses API
            request_args = {
                "model": self.model_name,
                "input": messages,
                "temperature": 0.1,
            }

            response = self.azure_client.responses.create(**request_args)

            # 解析响应内容
            if response.output and len(response.output) > 0:
                # 获取第一个输出的文本内容
                first_output = response.output[0]
                if hasattr(first_output, "content") and first_output.content:
                    # 提取text内容
                    text_content = ""
                    for content_item in first_output.content:
                        if hasattr(content_item, "text"):
                            text_content += content_item.text

                    if text_content:
                        try:
                            return json.loads(text_content)
                        except json.JSONDecodeError:
                            # 如果不是JSON格式，尝试从文本中提取结构化信息
                            logger.debug("LLM returned non-JSON; attempting parse")
                            return self._parse_llm_text_response(text_content)

            logger.debug("Azure OpenAI response parse failed")
            return None

        except Exception as e:
            logger.warning("Azure OpenAI call failed: %s", e)
            return None

    def _parse_llm_text_response(self, text: str) -> Dict[str, Any]:
        """从文本响应中解析结构化信息"""
        try:
            # 尝试提取level
            level_match = re.search(r"(?:level|等级).*?(\d)", text, re.IGNORECASE)
            level = int(level_match.group(1)) if level_match else 3

            # 尝试提取confidence
            conf_match = re.search(
                r"(?:confidence|置信度).*?(\d+\.?\d*)", text, re.IGNORECASE
            )
            confidence = float(conf_match.group(1)) if conf_match else 0.7

            # 如果confidence大于1，假设是百分比，除以100
            if confidence > 1:
                confidence = confidence / 100

            return {
                "level": level,
                "confidence": confidence,
                "reasoning": f"从文本解析: {text[:100]}...",
            }
        except Exception as e:
            logger.warning("Failed to parse LLM text response; using defaults: %s", e)
            return {
                "level": 3,
                "confidence": 0.5,
                "reasoning": "文本解析失败，使用默认值",
            }

    def _keyword_scoring_fallback(
        self, conversation: ConversationItem
    ) -> Dict[str, Any]:
        """关键词评分的回退方案"""
        content = conversation.content.lower()
        score = 0
        keywords_found = []

        # 高价值关键词
        high_value_patterns = {
            "preference": ["喜欢", "不喜欢", "偏好", "习惯", "倾向于", "更愿意"],
            "procedural": ["流程", "步骤", "方法", "如何", "怎么", "操作"],
            "semantic": ["概念", "原理", "理论", "分析", "思考", "观点"],
            "temporal": ["会议", "时间", "日期", "安排", "计划", "项目"],
        }

        for category, keywords in high_value_patterns.items():
            for keyword in keywords:
                if keyword in content:
                    score += 0.3
                    keywords_found.append((keyword, category))

        # 确定等级
        if score >= 0.9:
            level = 4
        elif score >= 0.6:
            level = 3
        elif score >= 0.3:
            level = 2
        else:
            level = 1

        return {
            "level": level,
            "confidence": min(score, 1.0),
            "reasoning": f"关键词评分回退: {score:.2f}, 发现关键词: {keywords_found}",
        }

    def _heuristic_analysis(self, conversation: ConversationItem) -> Dict[str, Any]:
        content = conversation.content

        # 长度分析
        if len(content) < 10:
            return {"level": 1, "confidence": 0.8, "reasoning": "内容过短"}

        # 问号分析
        if "?" in content or "？" in content:
            if any(kw in content for kw in ["什么", "如何", "为什么", "怎么"]):
                return {"level": 4, "confidence": 0.6, "reasoning": "包含方法询问"}
            else:
                return {"level": 2, "confidence": 0.5, "reasoning": "包含询问"}

        # 默认情况
        return {"level": 2, "confidence": 0.4, "reasoning": "启发式默认分类"}

    def _get_context_multiplier(self, conversation: ConversationItem) -> float:
        """根据上下文计算权重倍数"""
        multiplier = 1.0

        # 用户角色权重
        if "ceo" in conversation.user_id.lower():
            multiplier *= 1.5
        elif "vp" in conversation.user_id.lower():
            multiplier *= 1.3

        # 时间敏感性
        time_diff = time.time() - conversation.timestamp
        if time_diff < 3600:  # 1小时内
            multiplier *= 1.2
        elif time_diff > 86400 * 7:  # 1周前
            multiplier *= 0.8

        # 对话长度
        if len(conversation.content) > 200:
            multiplier *= 1.1

        return multiplier

    def _get_pattern_match_reason(self, content: str, level: int) -> str:
        """获取模式匹配原因"""
        patterns = self.quick_patterns.get(level, [])
        for pattern in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return f"匹配模式: {pattern}"
        return "规则匹配"

    def get_stats(self) -> Dict[str, Any]:
        """获取过滤统计信息"""
        total = self.stats["total_processed"]
        if total == 0:
            return self.stats

        avg_time = (
            sum(self.stats["processing_times"]) / len(self.stats["processing_times"])
            if self.stats["processing_times"]
            else 0
        )

        return {
            **self.stats,
            "level1_percentage": (self.stats["level1_filtered"] / total) * 100,
            "level2_percentage": (self.stats["level2_filtered"] / total) * 100,
            "level3_percentage": (self.stats["level3_analyzed"] / total) * 100,
            "average_processing_time": avg_time,
            "efficiency_target_met": self.stats["level1_filtered"] / total
            >= 0.80,  # 目标80%以上Level1处理
        }


# 使用示例
if __name__ == "__main__":
    filter_system = ConversationValueFilter()

    # 测试用例
    test_conversations = [
        ConversationItem("哈哈哈", time.time(), "user", "test_001"),
        ConversationItem(
            "明天董事会会议讨论AI战略规划", time.time(), "user", "ceo_001"
        ),
        ConversationItem("我习惯用PDF格式的报告", time.time(), "user", "vp_001"),
        ConversationItem("请解释一下微服务架构的原理", time.time(), "user", "cto_001"),
        ConversationItem("如何配置Kubernetes集群", time.time(), "user", "dev_001"),
    ]

    print("=== 对话价值3级漏斗过滤测试 ===\n")

    for i, conv in enumerate(test_conversations, 1):
        result = filter_system.filter_conversation(conv)
        print(f"测试 {i}:")
        print(f"  内容: {conv.content}")
        print(f"  等级: Level {result.memory_level}")
        print(f"  置信度: {result.confidence:.3f}")
        print(f"  过滤阶段: {result.filter_stage}")
        print(f"  处理时间: {result.processing_time:.3f}秒")
        print(f"  理由: {result.reasoning}")
        print()

    # 显示统计信息
    stats = filter_system.get_stats()
    print("=== 过滤统计信息 ===")
    print(f"总处理数: {stats['total_processed']}")
    print(
        f"Level1快速过滤: {stats['level1_filtered']} ({stats['level1_percentage']:.1f}%)"
    )
    print(
        f"Level2关键词过滤: {stats['level2_filtered']} ({stats['level2_percentage']:.1f}%)"
    )
    print(
        f"Level3LLM分析: {stats['level3_analyzed']} ({stats['level3_percentage']:.1f}%)"
    )
    print(f"平均处理时间: {stats['average_processing_time']:.3f}秒")
    print(f"效率目标达成: {'✓' if stats['efficiency_target_met'] else '✗'}")
