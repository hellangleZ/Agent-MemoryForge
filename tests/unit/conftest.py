"""Hermetic environment for unit tests.

Unit tests must not depend on a real .env being sourced into the shell. This autouse
fixture clears LLM/embedding provider env vars before each unit test so results are
deterministic. It intentionally does NOT touch MCP_* / backend vars (those tests manage
their own configuration). Tests that need a variable set it explicitly via monkeypatch.
"""
from __future__ import annotations

import os

import pytest

_CLEAR_PREFIXES = (
    "OPENAI_",
    "AZURE_OPENAI_",
    "AZURE_EMBEDDING_",
    "EMBEDDING_",
    "MEMORY_DISTILL_",
    "CONTEXT_PLANNER_",
    "AGENT_GATEWAY_",
)
_CLEAR_EXACT = {
    "LLM_PROVIDER",
    "PORTAL_SIGNUP_ENABLED",
    "DOTENV_PATH",
}


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    for key in list(os.environ):
        if key in _CLEAR_EXACT or any(key.startswith(p) for p in _CLEAR_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    yield
