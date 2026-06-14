
import pytest

from agent_runtime.product.gateway import app as gateway_app
from agent_runtime.product.gateway import deps


class _FakeUser:
    def __init__(self, role="admin"):
        self.id = "user-1"
        self.email = "user@example.com"
        self.role = role


class _FakeStore:
    def __init__(self, user=None):
        self._user = user or _FakeUser()

    def get_user_by_id(self, user_id):
        return self._user if user_id == "user-1" else None


def test_get_current_user_from_header(monkeypatch):
    monkeypatch.setattr(deps, "decode_access_token", lambda token: {"sub": "user-1"})
    monkeypatch.setattr(deps, "get_auth_store", lambda: _FakeStore())

    user = deps.get_current_user(authorization="Bearer token", portal_access_token=None)
    assert user["email"] == "user@example.com"


def test_get_current_user_missing_token():
    with pytest.raises(Exception):
        deps.get_current_user(authorization=None, portal_access_token=None)


def test_require_admin_rejects_non_admin():
    with pytest.raises(Exception):
        deps.require_admin({"role": "user"})


def test_optional_user_returns_none(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(
        deps,
        "get_current_user",
        lambda *a, **k: (_ for _ in ()).throw(HTTPException(status_code=401, detail="x")),
    )
    assert deps.optional_user(None, None) is None


def test_create_app_includes_routes():
    app = gateway_app.create_app()
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/portal/v1/signup" in paths
