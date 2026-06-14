# -*- coding: utf-8 -*-
"""
conversation_value_filter单元测试
"""

import pytest
from conversation_value_filter import (
    ConversationValueFilter,
    ConversationItem,
    FilterResult,
)


class TestConversationItem:
    """测试ConversationItem数据类"""

    def test_create_conversation_item(self):
        """测试创建对话项"""
        item = ConversationItem(content="测试内容", timestamp=1234567890.0, role="user")
        assert item.content == "测试内容"
        assert item.timestamp == 1234567890.0
        assert item.role == "user"

    def test_conversation_item_with_defaults(self):
        """测试带默认值的对话项"""
        item = ConversationItem(content="测试", timestamp=0.0, role="assistant")
        assert item.user_id == "unknown"
        assert item.context is None


class TestConversationValueFilter:
    """测试对话价值过滤器"""

    @pytest.fixture
    def filter_instance(self):
        """创建过滤器实例"""
        return ConversationValueFilter()

    def test_initialization(self, filter_instance):
        """测试初始化"""
        assert filter_instance.stats["total_processed"] == 0
        assert filter_instance.stats["level1_filtered"] == 0
        assert filter_instance.stats["level2_filtered"] == 0
        assert filter_instance.stats["level3_analyzed"] == 0
        assert isinstance(filter_instance._cache, dict)

    def test_level1_garbage_filter(self, filter_instance):
        """测试Level1垃圾内容过滤"""
        # 测试笑声
        item = ConversationItem(content="哈哈哈", timestamp=0.0, role="user")
        result = filter_instance.filter_conversation(item)
        assert result.memory_level == 1
        assert result.filter_stage == "Level1_QuickRule"

        # 测试简单确认
        item = ConversationItem(content="好的", timestamp=0.0, role="user")
        result = filter_instance.filter_conversation(item)
        assert result.memory_level == 1

        # 测试纯标点
        item = ConversationItem(content="。。。。。", timestamp=0.0, role="user")
        result = filter_instance.filter_conversation(item)
        assert result.memory_level == 1

    def test_cache_functionality(self, filter_instance):
        """测试缓存功能"""
        # 第一次调用
        item1 = ConversationItem(content="测试内容", timestamp=0.0, role="user")
        filter_instance.filter_conversation(item1)

        # 第二次调用相同内容（应该命中缓存）
        item2 = ConversationItem(content="测试内容", timestamp=1.0, role="user")
        filter_instance.filter_conversation(item2)

        # 验证缓存命中
        assert filter_instance.stats["cache_hits"] > 0

    def test_stats_tracking(self, filter_instance):
        """测试统计跟踪"""
        # 添加多个对话项
        items = [
            ConversationItem(content="哈哈哈", timestamp=0.0, role="user"),
            ConversationItem(content="好的", timestamp=1.0, role="user"),
            ConversationItem(
                content="我们需要开个会议讨论项目进度", timestamp=2.0, role="user"
            ),
        ]

        for item in items:
            filter_instance.filter_conversation(item)

        # 验证统计
        assert filter_instance.stats["total_processed"] >= 3
        assert filter_instance.stats["level1_filtered"] >= 2
        assert len(filter_instance.stats["processing_times"]) >= 3


class TestFilterResult:
    """测试FilterResult数据类"""

    def test_create_filter_result(self):
        """测试创建过滤结果"""
        result = FilterResult(
            memory_level=2,
            confidence=0.85,
            reasoning="测试原因",
            processing_time=0.1,
            filter_stage="Level2_KeywordScore",
        )
        assert result.memory_level == 2
        assert result.confidence == 0.85
        assert result.reasoning == "测试原因"
        assert result.processing_time == 0.1
        assert result.filter_stage == "Level2_KeywordScore"
