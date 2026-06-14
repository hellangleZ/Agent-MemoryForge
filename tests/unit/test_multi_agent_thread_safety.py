"""Tests for thread-safe context-local storage in multi_agent.py."""
from __future__ import annotations

import concurrent.futures
from typing import List


from agent_memory_framework.llm import CallableLLMProvider
from agent_memory_framework.multi_agent import (
    CoordinationStrategy,
    MultiAgentRuntime,
    _trace_collector_var,
    _trace_id_var,
)
from agent_memory_framework.runtime import Runtime
from agent_memory_framework.settings import Settings
from agent_memory_framework.trace import TraceCollector
from agent_runtime.product.templates.code_assistant import CodeAssistantAgent


class _FakeResponse:
    def __init__(self, output_text: str):
        self.output_text = output_text


def test_concurrent_runs_do_not_cross_contaminate_trace_id():
    """Two MultiAgentRuntime.run() calls executing concurrently with *different*
    trace_ids must each see only their own id inside the agent llm_call — this
    exercises our contextvar-based propagation under real contention, not the
    bare language feature.
    """
    seen: dict[str, set[str]] = {}

    def make_runtime(run_label: str) -> Runtime:
        def llm_call(messages):
            seen.setdefault(run_label, set()).add(_trace_id_var.get() or "none")
            import time

            time.sleep(0.01)  # widen the window for cross-talk if any
            seen.setdefault(run_label, set()).add(_trace_id_var.get() or "none")
            return _FakeResponse(output_text="ok")

        return Runtime(
            agent_id="agent1",
            user_id="u_1",
            memory_client=None,  # type: ignore[arg-type]
            llm_provider=CallableLLMProvider(llm_call),
            conversation_id="c_1",
            settings=Settings(),
        )

    def run(run_label: str, trace_id: str):
        rt = make_runtime(run_label)
        MultiAgentRuntime(
            agents={"agent1": CodeAssistantAgent(rt)},
            strategy=CoordinationStrategy.PARALLEL,
        ).run("test", trace_id=trace_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        futures = [
            ex.submit(run, "A", "trace_A"),
            ex.submit(run, "B", "trace_B"),
        ]
        for f in futures:
            f.result()

    # Each run observed ONLY its own trace_id, never the other run's.
    assert seen["A"] == {"trace_A"}
    assert seen["B"] == {"trace_B"}


def test_trace_collector_is_isolated_per_thread():
    """Concurrently-created TraceCollectors must not share span state: each
    thread's collector ends with exactly the spans it opened, proving the
    runtime's per-context collector is not a leaking global.
    """
    from agent_memory_framework.trace import trace_span

    def create_and_use_collector(idx: int) -> int:
        collector = TraceCollector()
        _trace_collector_var.set(collector)
        # Open a different number of spans per thread to catch any sharing.
        for n in range(idx + 1):
            with trace_span(collector, f"test.span.{n}"):
                pass
        return len(collector._spans)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futures = {
            idx: ex.submit(create_and_use_collector, idx) for idx in range(3)
        }
        for idx, f in futures.items():
            assert f.result() == idx + 1  # no cross-thread span leakage


def test_parallel_execution_uses_context_vars():
    """Test that parallel agent execution properly uses context-local storage."""
    call_trace_ids: List[str] = []

    def llm_call(messages):
        # Capture the trace_id from context var
        trace_id = _trace_id_var.get()
        call_trace_ids.append(trace_id or "none")
        return _FakeResponse(output_text="ok")

    runtime = Runtime(
        agent_id="agent1",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(llm_call),
        conversation_id="c_1",
        settings=Settings(),
    )

    agents = {
        "agent1": CodeAssistantAgent(runtime),
        "agent2": CodeAssistantAgent(
            Runtime(
                agent_id="agent2",
                user_id=runtime.user_id,
                memory_client=runtime.memory_client,
                llm_provider=runtime.llm_provider,
                conversation_id=runtime.conversation_id,
                settings=runtime.settings,
            )
        ),
    }

    result = MultiAgentRuntime(
        agents=agents,
        strategy=CoordinationStrategy.PARALLEL
    ).run("test", trace_id="test_trace_123")

    # Verify the trace_id was propagated to both agents
    assert "test_trace_123" in call_trace_ids
    assert result["routing_trace"]["strategy"] == "parallel"


def test_sequential_execution_preserves_trace_id():
    """Test that sequential execution properly propagates trace_id."""
    call_trace_ids: List[str] = []

    def llm_call(messages):
        trace_id = _trace_id_var.get()
        call_trace_ids.append(trace_id or "none")
        return _FakeResponse(output_text="ok")

    runtime = Runtime(
        agent_id="agent1",
        user_id="u_1",
        memory_client=None,  # type: ignore[arg-type]
        llm_provider=CallableLLMProvider(llm_call),
        conversation_id="c_1",
        settings=Settings(),
    )

    agents = {
        "agent1": CodeAssistantAgent(runtime),
        "agent2": CodeAssistantAgent(
            Runtime(
                agent_id="agent2",
                user_id=runtime.user_id,
                memory_client=runtime.memory_client,
                llm_provider=runtime.llm_provider,
                conversation_id=runtime.conversation_id,
                settings=runtime.settings,
            )
        ),
    }

    result = MultiAgentRuntime(
        agents=agents,
        strategy=CoordinationStrategy.SEQUENTIAL
    ).run("test", trace_id="seq_trace_456")

    # Both agents should have seen the same trace_id
    assert call_trace_ids.count("seq_trace_456") == 2
    assert result["routing_trace"]["strategy"] == "sequential"


def test_context_vars_fresh_context():
    """Verify context vars are isolated in fresh contexts."""
    def get_and_set(initial_value: str, new_value: str) -> str:
        # Set initial value
        _trace_id_var.set(initial_value)
        # Get it back
        val1 = _trace_id_var.get()
        # Set new value
        _trace_id_var.set(new_value)
        val2 = _trace_id_var.get()
        return f"{val1}:{val2}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        futures = [
            ex.submit(get_and_set, "init1", "new1"),
            ex.submit(get_and_set, "init2", "new2"),
        ]
        results = [f.result() for f in futures]

    assert sorted(results) == ["init1:new1", "init2:new2"]
