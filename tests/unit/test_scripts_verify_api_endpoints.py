import types

import pytest

from scripts import verify_api_endpoints as verify


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, responses):
        self._responses = responses
        self._calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        self._calls.append(("get", url))
        return self._responses.get(url, _FakeResponse(404))

    async def post(self, url, json=None, headers=None):
        self._calls.append(("post", url))
        return self._responses.get(url, _FakeResponse(404))


def test_endpoint_result_str():
    res = verify.EndpointResult("GET", "/health", 200, True)
    assert "GET" in str(res)


@pytest.mark.asyncio
async def test_test_endpoint_success(monkeypatch):
    fake = _FakeAsyncClient({"http://x/ok": _FakeResponse(200)})
    result = await verify.test_endpoint(fake, "http://x", "GET", "/ok", None, None)
    assert result.success is True


@pytest.mark.asyncio
async def test_verify_endpoints(monkeypatch):
    responses = {"http://x/portal/v1/login": _FakeResponse(200, {"access_token": "t"})}
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda timeout=10.0: _FakeAsyncClient(responses), ConnectError=Exception)
    monkeypatch.setattr(verify, "httpx", fake_httpx)
    success, total = await verify.verify_endpoints("http://x")
    assert total == len(verify.ENDPOINTS)
    assert success >= 1
