"""
文本处理工具模块
提供Token估计、关键词提取、相关性计算等纯文本处理功能
"""

import os
import re
from typing import List, Dict, Set, Optional
from collections import Counter
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _lazy_jieba_analyse():
    """Import jieba lazily to avoid heavy import-time cost during pytest collection."""

    if os.getenv("AGENT_MEMORY_DISABLE_JIEBA") == "1":
        raise RuntimeError("jieba disabled")

    import jieba.analyse  # type: ignore

    return jieba.analyse


def _simple_segment(text: str) -> List[str]:
    if not text:
        return []
    # Chinese blocks / ASCII words / numbers.
    parts = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z]+|\d+", text)
    out: List[str] = []
    for part in parts:
        if not part or part.isspace():
            continue
        out.append(part)
        # Add bigrams for Chinese blocks to approximate segmentation.
        if re.fullmatch(r"[\u4e00-\u9fff]+", part) and len(part) >= 2:
            out.extend(part[i : i + 2] for i in range(len(part) - 1))
    return out


# 停用词列表
DEFAULT_STOPWORDS = {
    "的",
    "了",
    "在",
    "是",
    "我",
    "有",
    "和",
    "就",
    "不",
    "人",
    "都",
    "一",
    "一个",
    "上",
    "也",
    "很",
    "到",
    "说",
    "要",
    "去",
    "你",
    "会",
    "着",
    "没有",
    "看",
    "好",
    "自己",
    "这",
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "up",
    "about",
    "into",
    "over",
    "after",
}


class TextProcessor:
    """
    文本处理工具类
    提供各种文本处理和分析功能
    """

    def __init__(self, stopwords: Optional[Set[str]] = None):
        """
        初始化文本处理器

        Args:
            stopwords: 可选的自定义停用词集合
        """
        self.stopwords = stopwords or DEFAULT_STOPWORDS
        logger.debug("TextProcessor initialized")

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        估算文本的token数量

        使用简单的启发式方法：中文按字符计算，英文按单词计算

        Args:
            text: 输入文本

        Returns:
            估算的token数量

        Examples:
            >>> TextProcessor.estimate_tokens("Hello world")
            2
            >>> TextProcessor.estimate_tokens("你好世界")
            2
        """
        if not text:
            return 0

        # 统计中文字符数（不包括空格和标点）
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))

        # 统计英文单词数
        english_words = len(re.findall(r"\b[a-zA-Z]+\b", text))

        # 总token估算 = 中文字符 + 英文单词
        # 中文字符通常1字符约等于1token，英文单词约1-2tokens
        return chinese_chars + int(english_words * 1.3)

    def extract_keywords(
        self, text: str, top_k: int = 10, method: str = "tfidf"
    ) -> List[str]:
        """
        从文本中提取关键词

        Args:
            text: 输入文本
            top_k: 返回前k个关键词
            method: 提取方法，支持 "tfidf" 或 "textrank"

        Returns:
            关键词列表，按重要性排序

        Examples:
            >>> processor = TextProcessor()
            >>> processor.extract_keywords("项目管理需要协调团队和资源")
            ["项目管理", "协调", "团队", "资源"]
        """
        if not text or len(text.strip()) < 2:
            return []

        try:
            jieba_analyse = _lazy_jieba_analyse()
            # Ensure jieba is initialized promptly when enabled.
            import jieba  # type: ignore

            jieba.initialize()
            if method == "tfidf":
                keywords = jieba_analyse.extract_tags(
                    text, topK=top_k, withWeight=False
                )
            elif method == "textrank":
                keywords = jieba_analyse.textrank(text, topK=top_k, withWeight=False)
            else:
                logger.warning(f"Unknown method: {method}, using tfidf")
                keywords = jieba_analyse.extract_tags(
                    text, topK=top_k, withWeight=False
                )

            # 过滤停用词
            filtered_keywords = [
                kw
                for kw in keywords
                if kw.lower() not in self.stopwords and len(kw) > 1
            ]

            return filtered_keywords[:top_k]

        except Exception as e:
            logger.error(f"Failed to extract keywords: {e}")
            # Fallback: simple regex-based segmentation + frequency.
            words = self.segment_text(text)
            words = [w for w in words if w.lower() not in self.stopwords and len(w) > 1]
            freq = Counter(words)
            return [w for w, _ in freq.most_common(top_k)]

    def calculate_relevance(
        self, text: str, keywords: List[str], method: str = "overlap"
    ) -> float:
        """
        计算文本与关键词的相关性得分

        Args:
            text: 输入文本
            keywords: 关键词列表
            method: 计算方法，支持 "overlap"（重叠度）或 "frequency"（词频）

        Returns:
            相关性得分（0.0-1.0）

        Examples:
            >>> processor = TextProcessor()
            >>> processor.calculate_relevance("项目管理很重要", ["项目", "管理"])
            1.0
        """
        if not text or not keywords:
            return 0.0

        try:
            # 分词
            words = set(self.segment_text(text))

            # 过滤停用词
            words = {w for w in words if w.lower() not in self.stopwords and len(w) > 1}

            if method == "overlap":
                # 重叠度计算：匹配的关键词数 / 总关键词数
                matched = sum(
                    1 for kw in keywords if any(kw in w or w in kw for w in words)
                )
                return matched / len(keywords) if keywords else 0.0

            elif method == "frequency":
                # 词频加权计算
                word_freq = Counter(words)
                total_freq = sum(word_freq.values())

                if total_freq == 0:
                    return 0.0

                # 计算关键词在文本中的总频率
                keyword_freq = sum(word_freq.get(kw, 0) for kw in keywords)

                # 归一化得分
                return min(keyword_freq / total_freq, 1.0)

            else:
                logger.warning(f"Unknown relevance method: {method}, using overlap")
                return self.calculate_relevance(text, keywords, method="overlap")

        except Exception as e:
            logger.error(f"Failed to calculate relevance: {e}")
            return 0.0

    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """
        简单的实体提取（基于模式匹配）

        Args:
            text: 输入文本

        Returns:
            实体字典，包含人名、时间、数字等
        """
        entities = {"numbers": [], "emails": [], "urls": [], "dates": []}

        try:
            # 提取数字
            entities["numbers"] = re.findall(r"\d+\.?\d*", text)

            # 提取邮箱（不使用单词边界，兼容中文文本）
            entities["emails"] = re.findall(
                r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text
            )

            # 提取URL
            entities["urls"] = re.findall(
                r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+",
                text,
            )

            # 提取日期（简单模式）
            entities["dates"] = re.findall(
                r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?", text
            )

        except Exception as e:
            logger.error(f"Failed to extract entities: {e}")

        return entities

    def segment_text(self, text: str) -> List[str]:
        """
        中文分词

        Args:
            text: 输入文本

        Returns:
            分词结果列表
        """
        if not text:
            return []

        try:
            if os.getenv("AGENT_MEMORY_DISABLE_JIEBA") == "1":
                words = _simple_segment(text)
            else:
                import jieba  # type: ignore

                jieba.initialize()
                words = list(jieba.cut(text))
            # 过滤空格和停用词
            return [w for w in words if w.strip() and w.lower() not in self.stopwords]
        except Exception as e:
            logger.error(f"Failed to segment text: {e}")
            return [
                w
                for w in _simple_segment(text)
                if w.strip() and w.lower() not in self.stopwords
            ]

    def summarize_text(self, text: str, max_sentences: int = 3) -> str:
        """
        简单的文本摘要（提取前N个句子）

        Args:
            text: 输入文本
            max_sentences: 最大句子数

        Returns:
            摘要文本
        """
        if not text:
            return ""

        try:
            # 按句子分割（简单处理中英文句号）
            sentences = re.split(r"[。！？.!?]+", text)

            # 过滤空句子
            sentences = [s.strip() for s in sentences if s.strip()]

            # 返回前N个句子
            selected = sentences[:max_sentences]

            return "。".join(selected) + ("。" if selected else "")

        except Exception as e:
            logger.error(f"Failed to summarize text: {e}")
            return text[:100]  # 降级：返回前100个字符


# 便捷函数
def estimate_tokens(text: str) -> int:
    """估算token数量的便捷函数"""
    return TextProcessor.estimate_tokens(text)


def extract_keywords(text: str, top_k: int = 10) -> List[str]:
    """提取关键词的便捷函数"""
    processor = TextProcessor()
    return processor.extract_keywords(text, top_k=top_k)


def calculate_relevance(text: str, keywords: List[str]) -> float:
    """计算相关性的便捷函数"""
    processor = TextProcessor()
    return processor.calculate_relevance(text, keywords)
