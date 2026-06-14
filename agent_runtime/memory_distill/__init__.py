"""Async memory distillation (product layer).

This package provides a Redis-backed queue + worker-friendly job schema used by
`agent_runtime/product/agent_gateway.py` to distill each completed turn
into structured memories (STM summary, semantic facts, preferences, KG triples).

Design goal: keep distillation decoupled from the main reasoning LLM and allow a
cheaper model + async execution.
"""
