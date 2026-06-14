import pytest


def test_context_assembler_dedup_and_budget_trace():
    from agent_memory_framework.context import ContextAssembler, ContextBudget
    from agent_memory_lib.text_processing import TextProcessor

    class DummyMemoryManager:
        def retrieve_stm_summaries(self, last_k):
            return []

    assembler = ContextAssembler(
        memory_manager=DummyMemoryManager(),
        text_processor=TextProcessor(),
        config={"stm_top_k": 0, "stm_max_summaries": 0},
    )

    # Make a context that includes duplicates and lots of older messages.
    history = []
    history.append({"role": "user", "content": "hello"})
    history.append({"role": "assistant", "content": "world"})
    history.append({"role": "assistant", "content": "world"})  # dup
    for i in range(30):
        # Use a lot of word-like tokens so the budget compaction deterministically triggers.
        history.append(
            {"role": "user", "content": f"old message {i} " + ("hello " * 50)}
        )

    messages, trace = assembler.build_with_trace(
        user_query="hello",
        conversation_history=history,
        system_prompt="sys",
        budget=ContextBudget(max_tokens=120, reserved_response_tokens=0),
    )

    assert isinstance(trace.context_hash, str)
    assert len(trace.context_hash) == 64
    # Ensure no exact duplicate role/content pairs.
    seen = set()
    for msg in messages:
        key = (msg.get("role"), msg.get("content"))
        assert key not in seen
        seen.add(key)

    # Budget should force dropping some older messages.
    assert any(entry.get("reason") == "budget" for entry in trace.excluded)


@pytest.mark.parametrize(
    "reserved",
    [0, 50],
)
def test_context_budget_available_tokens_non_negative(reserved):
    from agent_memory_framework.context import ContextBudget

    budget = ContextBudget(max_tokens=10, reserved_response_tokens=reserved)
    assert budget.available_tokens >= 0
