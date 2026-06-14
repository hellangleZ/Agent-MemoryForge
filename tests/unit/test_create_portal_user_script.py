from __future__ import annotations

from agent_runtime.product.auth_store import SQLiteAuthStore
from scripts.create_portal_user import create_portal_user


def test_create_portal_user_creates_admin(tmp_path) -> None:
    db_path = tmp_path / "portal_auth.db"

    action = create_portal_user(
        db_path=db_path,
        username="admin",
        tenant_id="admin",
        role="admin",
        password="password123",
    )

    assert action == "created"
    store = SQLiteAuthStore(db_path=str(db_path))
    user = store.authenticate(username="admin", password="password123")
    assert user is not None
    assert user.tenant_id == "admin"
    assert user.role == "admin"


def test_create_portal_user_requires_replace_for_existing_user(tmp_path) -> None:
    db_path = tmp_path / "portal_auth.db"
    create_portal_user(
        db_path=db_path,
        username="employee",
        tenant_id="tenant_acme",
        role="user",
        password="password123",
    )

    try:
        create_portal_user(
            db_path=db_path,
            username="employee",
            tenant_id="tenant_acme",
            role="admin",
            password="newpass123",
        )
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("expected duplicate user to fail")


def test_create_portal_user_can_replace_password_and_role(tmp_path) -> None:
    db_path = tmp_path / "portal_auth.db"
    create_portal_user(
        db_path=db_path,
        username="employee",
        tenant_id="tenant_acme",
        role="user",
        password="password123",
    )

    action = create_portal_user(
        db_path=db_path,
        username="employee",
        tenant_id="tenant_acme",
        role="admin",
        password="newpass123",
        replace_password=True,
    )

    assert action == "updated"
    store = SQLiteAuthStore(db_path=str(db_path))
    assert store.authenticate(username="employee", password="password123") is None
    user = store.authenticate(username="employee", password="newpass123")
    assert user is not None
    assert user.role == "admin"
