import types

import pytest

from agent_memory_framework.memory_distill import llm_provider as distill_provider
from agent_memory_framework.memory_runtime import openai_like_llm as openai_like


class _FakeResponse:
    def __init__(self, text: str):
        self.output_text = text


class _RateLimitError(Exception):
    status_code = 429

    def __init__(self, message: str = "rate limit"):
        super().__init__(message)
        self.response = types.SimpleNamespace(headers={"Retry-After": "0"})


class _FakeOpenAI:
    def __init__(self, *args, **kwargs):
        self._calls = []
        self.responses = self
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._chat_create)
        )

    def create(self, *args, **kwargs):
        self._calls.append(kwargs)
        if len(self._calls) == 1:
            raise _RateLimitError()
        return _FakeResponse("ok")

    def _chat_create(self, *args, **kwargs):
        self._calls.append({"chat": kwargs})
        msg = types.SimpleNamespace(content="ok-chat")
        choice = types.SimpleNamespace(message=msg)
        return types.SimpleNamespace(choices=[choice])


class _FakeAzureOpenAI:
    def __init__(self, *args, **kwargs):
        self.responses = self

    def create(self, *args, **kwargs):
        return _FakeResponse("azure")


def _install_fake_openai(monkeypatch):
    fake_module = types.SimpleNamespace(OpenAI=_FakeOpenAI, AzureOpenAI=_FakeAzureOpenAI)
    monkeypatch.setitem(__import__("sys").modules, "openai", fake_module)


def test_openai_like_normalization_dict():
    text = openai_like._normalize_openai_response_to_text({"output_text": "hi"})
    assert text == "hi"


def test_openai_like_parse_retry_after_seconds():
    exc = _RateLimitError()
    assert openai_like._parse_retry_after_seconds(exc) == 0.0


def test_openai_like_call_retries(monkeypatch):
    _install_fake_openai(monkeypatch)
    monkeypatch.setattr(openai_like.time, "sleep", lambda *_: None)
    monkeypatch.setattr(openai_like.random, "random", lambda: 0)

    cfg = openai_like.OpenAILikeLLMConfig(
        provider="openai", model="gpt", temperature=0.1, max_output_tokens=5
    )
    text = openai_like.call_openai_like_llm(cfg=cfg, messages=[{"role": "user", "content": "hi"}])
    assert text == "ok"


def test_openai_like_call_forces_chat_api(monkeypatch):
    _install_fake_openai(monkeypatch)

    cfg = openai_like.OpenAILikeLLMConfig(
        provider="openai",
        model="gpt",
        temperature=0.1,
        max_output_tokens=5,
        api_style="chat",
    )
    text = openai_like.call_openai_like_llm(cfg=cfg, messages=[{"role": "user", "content": "hi"}])
    assert text == "ok-chat"


def test_openai_like_azure_missing_config():
    cfg = openai_like.OpenAILikeLLMConfig(
        provider="azure", model="gpt", temperature=0.1, max_output_tokens=5
    )
    with pytest.raises(RuntimeError, match="Azure LLM config is incomplete"):
        openai_like.call_openai_like_llm(cfg=cfg, messages=[])


def test_openai_like_azure_success(monkeypatch):
    _install_fake_openai(monkeypatch)
    cfg = openai_like.OpenAILikeLLMConfig(
        provider="azure",
        model="gpt",
        temperature=0.1,
        max_output_tokens=5,
        azure_api_key="key",
        azure_endpoint="endpoint",
        azure_deployment="deploy",
    )
    text = openai_like.call_openai_like_llm(cfg=cfg, messages=[])
    assert text == "azure"


def test_distill_llm_openai_like(monkeypatch):
    _install_fake_openai(monkeypatch)
    monkeypatch.setattr(distill_provider.time, "sleep", lambda *_: None)
    monkeypatch.setattr(distill_provider.random, "random", lambda: 0)

    cfg = distill_provider.DistillLLMConfig(
        provider="openai", model="gpt", temperature=0.1, max_output_tokens=5
    )
    text = distill_provider.call_distill_llm(cfg=cfg, messages=[{"role": "user", "content": "hi"}])
    assert text == "ok"


def test_distill_llm_azure_missing_config():
    cfg = distill_provider.DistillLLMConfig(
        provider="azure", model="gpt", temperature=0.1, max_output_tokens=5
    )
    with pytest.raises(RuntimeError, match="Azure distill config is incomplete"):
        distill_provider.call_distill_llm(cfg=cfg, messages=[])


def test_distill_llm_unsupported_provider():
    cfg = distill_provider.DistillLLMConfig(
        provider="unknown", model="gpt", temperature=0.1, max_output_tokens=5
    )
    with pytest.raises(RuntimeError, match="Unsupported MEMORY_DISTILL_PROVIDER"):
        distill_provider.call_distill_llm(cfg=cfg, messages=[])
