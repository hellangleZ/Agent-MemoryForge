
from conversation_value_filter import ConversationItem, ConversationValueFilter


def test_level1_quick_filter_and_cache():
    filt = ConversationValueFilter()
    convo = ConversationItem(content="谢谢", role="user", user_id="u1")
    result = filt.filter_conversation(convo)
    assert result.memory_level == 1
    cached = filt.filter_conversation(convo)
    assert cached.memory_level == 1


def test_level2_keyword_scoring(monkeypatch):
    filt = ConversationValueFilter()
    convo = ConversationItem(content="我们需要讨论预算和成本", role="user", user_id="u1")
    monkeypatch.setattr(filt, "_call_llm_api", lambda *a, **k: {"level": 3, "confidence": 0.6, "reasoning": "ok"})
    result = filt.filter_conversation(convo)
    assert result.filter_stage == "Level2_KeywordScore"


def test_level3_llm_analysis(monkeypatch):
    filt = ConversationValueFilter()
    convo = ConversationItem(content="复杂问题需要深度分析", role="user", user_id="u1")
    monkeypatch.setattr(filt, "_level2_keyword_scoring", lambda *a, **k: None)
    monkeypatch.setattr(filt, "_call_llm_api", lambda *a, **k: {"level": 4, "confidence": 0.7, "reasoning": "deep"})
    result = filt.filter_conversation(convo)
    assert result.filter_stage == "Level3_LLMAnalysis"


def test_get_stats():
    filt = ConversationValueFilter()
    stats = filt.get_stats()
    assert "total_processed" in stats
