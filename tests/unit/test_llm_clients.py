import types


from agent_memory_framework import llm_clients


class _FakeOpenAI:
    def __init__(self, api_key=None, timeout=None, **kwargs):
        self.api_key = api_key
        self.timeout = timeout
        self.kwargs = kwargs


def _install_fake_openai(monkeypatch):
    fake_module = types.SimpleNamespace(OpenAI=_FakeOpenAI)
    monkeypatch.setitem(__import__("sys").modules, "openai", fake_module)


def test_create_openai_like_client_openai(monkeypatch):
    _install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://openai")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    client, model = llm_clients.create_openai_like_client()
    assert isinstance(client, _FakeOpenAI)
    assert model == "gpt"
    assert client.kwargs["base_url"] == "http://openai"


def test_create_openai_like_client_azure(monkeypatch):
    _install_fake_openai(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "http://azure")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "akey")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "deploy")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-02-15")

    client, model = llm_clients.create_openai_like_client()
    assert model == "deploy"
    assert client.kwargs["base_url"] == "http://azure"
    assert client.kwargs["default_query"]["api-version"] == "2024-02-15"


def test_normalized_llm_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert llm_clients._normalized_llm_provider() is None
