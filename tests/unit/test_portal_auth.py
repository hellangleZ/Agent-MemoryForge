import pytest

from agent_runtime.product import agent_gateway
from agent_runtime.product.auth_models import (
    LoginRequest,
    LogoutRequest,
    PasswordChangeRequest,
    SignupRequest,
    TokenRefreshRequest,
)
from agent_runtime.product.auth_store import InMemoryAuthStore


@pytest.fixture(autouse=True)
def _enable_signup(monkeypatch):
    # Signup is gated by PORTAL_SIGNUP_ENABLED; enable it for these auth tests.
    monkeypatch.setenv("PORTAL_SIGNUP_ENABLED", "1")


def test_signup_login_me_and_refresh_rotation(monkeypatch) -> None:
    monkeypatch.setattr(agent_gateway, "_auth_store", InMemoryAuthStore())
    username = "alice"
    password = "pw"

    agent_gateway.portal_signup(SignupRequest(username=username, password=password))

    tokens = agent_gateway.portal_login(LoginRequest(username=username, password=password))
    assert tokens.access_token
    assert tokens.refresh_token
    assert tokens.expires_in > 0

    me = agent_gateway.portal_me(tokens.access_token)
    assert me.id == username
    assert me.role == "user"

    refreshed = agent_gateway.portal_refresh(
        TokenRefreshRequest(refresh_token=tokens.refresh_token)
    )
    assert refreshed.access_token
    assert refreshed.refresh_token
    assert refreshed.refresh_token != tokens.refresh_token

    refreshed2 = agent_gateway.portal_refresh(
        TokenRefreshRequest(refresh_token=refreshed.refresh_token)
    )
    assert refreshed2.refresh_token != refreshed.refresh_token

    # Reusing the original refresh token revokes the whole family.
    with pytest.raises(Exception):
        agent_gateway._auth_store.validate_and_rotate_refresh(tokens.refresh_token)

    with pytest.raises(Exception):
        agent_gateway.portal_refresh(
            TokenRefreshRequest(refresh_token=refreshed2.refresh_token)
        )


def test_logout_revokes_refresh_family(monkeypatch) -> None:
    monkeypatch.setattr(agent_gateway, "_auth_store", InMemoryAuthStore())
    username = "bob"
    password = "pw"

    agent_gateway.portal_signup(SignupRequest(username=username, password=password))
    tokens = agent_gateway.portal_login(LoginRequest(username=username, password=password))

    agent_gateway.portal_logout(LogoutRequest(refresh_token=tokens.refresh_token))

    with pytest.raises(Exception):
        agent_gateway.portal_refresh(
            TokenRefreshRequest(refresh_token=tokens.refresh_token)
        )


def test_refresh_token_expires_server_side(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_REFRESH_TOKEN_TTL_S", "1")
    store = InMemoryAuthStore()
    monkeypatch.setattr(agent_gateway, "_auth_store", store)
    username = "erin"
    password = "pw"

    agent_gateway.portal_signup(SignupRequest(username=username, password=password))
    tokens = agent_gateway.portal_login(LoginRequest(username=username, password=password))
    rec = store._refresh_by_hash[next(iter(store._refresh_by_hash))]
    store._refresh_by_hash[rec.token_hash] = type(rec)(
        family_id=rec.family_id,
        token_hash=rec.token_hash,
        username=rec.username,
        tenant_id=rec.tenant_id,
        revoked=rec.revoked,
        issued_at=rec.issued_at,
        expires_at=0,
    )

    with pytest.raises(Exception):
        agent_gateway.portal_refresh(TokenRefreshRequest(refresh_token=tokens.refresh_token))


def test_logout_allows_empty_body_for_cookie_only_flow(monkeypatch) -> None:
    monkeypatch.setattr(agent_gateway, "_auth_store", InMemoryAuthStore())

    assert agent_gateway.portal_logout(LogoutRequest())["status"] == "success"
    assert agent_gateway.portal_logout(None)["status"] == "success"


def test_bearer_token_accepts_cookie() -> None:
    token = "tok_123"
    assert agent_gateway._bearer_token_from_headers(
        authorization=None, portal_access_token=token
    ) == token

    with pytest.raises(Exception):
        agent_gateway._bearer_token_from_headers(authorization=None, portal_access_token=None)


def test_password_change_updates_credentials(monkeypatch) -> None:
    monkeypatch.setattr(agent_gateway, "_auth_store", InMemoryAuthStore())
    username = "carol"
    password = "pw"
    new_password = "pw2longer"

    agent_gateway.portal_signup(SignupRequest(username=username, password=password))

    agent_gateway.portal_change_password(
        PasswordChangeRequest(current_password=password, new_password=new_password),
        token=agent_gateway.portal_login(
            LoginRequest(username=username, password=password)
        ).access_token,
    )

    with pytest.raises(Exception):
        agent_gateway.portal_login(LoginRequest(username=username, password=password))

    new_tokens = agent_gateway.portal_login(
        LoginRequest(username=username, password=new_password)
    )
    assert new_tokens.access_token


def test_password_change_revokes_refresh_tokens(monkeypatch) -> None:
    monkeypatch.setattr(agent_gateway, "_auth_store", InMemoryAuthStore())
    username = "dave"
    password = "pw"
    new_password = "pw2longer"

    agent_gateway.portal_signup(SignupRequest(username=username, password=password))
    tokens = agent_gateway.portal_login(LoginRequest(username=username, password=password))

    agent_gateway.portal_change_password(
        PasswordChangeRequest(current_password=password, new_password=new_password),
        token=tokens.access_token,
    )

    with pytest.raises(Exception):
        agent_gateway.portal_refresh(
            TokenRefreshRequest(refresh_token=tokens.refresh_token)
        )
