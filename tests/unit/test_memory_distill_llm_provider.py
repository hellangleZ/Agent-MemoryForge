import pytest


class _Resp:
    def __init__(self, text: str):
        self.output_text = text


class _FakeResponses:
    def __init__(self):
        self.calls = 0
        self.kwargs_seen = []

    def create(self, **kwargs):
        self.calls += 1
        self.kwargs_seen.append(dict(kwargs))
        if self.calls == 1 and "temperature" in kwargs:
            raise RuntimeError("Unsupported parameter: 'temperature' is not supported with this model.")
        return _Resp("OK")


class _FakeChatCompletions:
    def __init__(self):
        self.calls = 0
        self.kwargs_seen = []

    def create(self, **kwargs):
        self.calls += 1
        self.kwargs_seen.append(dict(kwargs))
        msg = type("Msg", (), {"content": "OK_CHAT"})
        choice = type("Choice", (), {"message": msg})
        return type("ChatResp", (), {"choices": [choice]})


class _FakeChat:
    def __init__(self):
        self.completions = _FakeChatCompletions()


class _FakeOpenAI:
    def __init__(self, api_key=None, **_kwargs):
        self.responses = _FakeResponses()
        self.chat = _FakeChat()


@pytest.mark.unit
def test_distill_llm_drops_temperature_when_unsupported(monkeypatch):
    from agent_memory_framework.memory_distill import llm_provider

    import openai  # type: ignore

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI, raising=True)

    cfg = llm_provider.DistillLLMConfig(
        provider="openai-like",
        model="m",
        temperature=0.2,
        max_output_tokens=200,
        openai_api_key="k",
        openai_base_url="http://example.invalid/v1",
        max_attempts=2,
        retry_base_sleep_s=0.0,
    )
    out = llm_provider.call_distill_llm(cfg=cfg, messages=[{"role": "user", "content": "hi"}])
    assert out == "OK"


@pytest.mark.unit
def test_distill_llm_falls_back_to_chat_completions_when_responses_404(monkeypatch):
    from agent_memory_framework.memory_distill import llm_provider

    import openai  # type: ignore

    class _Responses404:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            err = RuntimeError("404 page not found")
            setattr(err, "status_code", 404)
            raise err

    class _OpenAIWith404(_FakeOpenAI):
        def __init__(self, api_key=None, **_kwargs):
            super().__init__(api_key=api_key, **_kwargs)
            self.responses = _Responses404()

    monkeypatch.setattr(openai, "OpenAI", _OpenAIWith404, raising=True)

    cfg = llm_provider.DistillLLMConfig(
        provider="openai-like",
        model="m",
        temperature=0.2,
        max_output_tokens=200,
        openai_api_key="k",
        openai_base_url="http://example.invalid/v1",
        max_attempts=2,
        retry_base_sleep_s=0.0,
    )
    out = llm_provider.call_distill_llm(cfg=cfg, messages=[{"role": "user", "content": "hi"}])
    assert out == "OK_CHAT"


@pytest.mark.unit
def test_distill_llm_forces_chat_completions(monkeypatch):
    from agent_memory_framework.memory_distill import llm_provider

    import openai  # type: ignore

    class _OpenAIChatOnly(_FakeOpenAI):
        def __init__(self, api_key=None, **_kwargs):
            super().__init__(api_key=api_key, **_kwargs)

        @property
        def responses(self):
            raise AssertionError("forced chat mode must not access responses")

        @responses.setter
        def responses(self, _value):
            return None

    monkeypatch.setattr(openai, "OpenAI", _OpenAIChatOnly, raising=True)

    cfg = llm_provider.DistillLLMConfig(
        provider="openai-like",
        model="m",
        temperature=0.2,
        max_output_tokens=200,
        openai_api_key="k",
        api_style="chat",
        max_attempts=2,
        retry_base_sleep_s=0.0,
    )
    out = llm_provider.call_distill_llm(cfg=cfg, messages=[{"role": "user", "content": "hi"}])
    assert out == "OK_CHAT"


@pytest.mark.unit
def test_distill_llm_configures_client_timeout(monkeypatch):
    from agent_memory_framework.memory_distill import llm_provider

    import openai  # type: ignore

    class _OpenAIWithInitCapture(_FakeOpenAI):
        init_kwargs = {}

        def __init__(self, api_key=None, **kwargs):
            type(self).init_kwargs = dict(kwargs)
            super().__init__(api_key=api_key, **kwargs)

    monkeypatch.setattr(openai, "OpenAI", _OpenAIWithInitCapture, raising=True)

    cfg = llm_provider.DistillLLMConfig(
        provider="openai-like",
        model="m",
        temperature=0.2,
        max_output_tokens=200,
        openai_api_key="k",
        timeout_s=12.5,
        max_attempts=2,
        retry_base_sleep_s=0.0,
    )
    assert llm_provider.call_distill_llm(cfg=cfg, messages=[{"role": "user", "content": "hi"}]) == "OK"
    assert _OpenAIWithInitCapture.init_kwargs["timeout"] == 12.5
    assert _OpenAIWithInitCapture.init_kwargs["max_retries"] == 0
