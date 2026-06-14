from __future__ import annotations

import os

import pytest

from agent_runtime.product.auth_store import SQLiteAuthStore


@pytest.mark.unit
def test_sqlite_auth_store_persists_user_across_instances(tmp_path):
    os.environ.setdefault("AUTH_REFRESH_TOKEN_HASH_SECRET", "test-secret")
    db = tmp_path / "portal_auth.db"

    store1 = SQLiteAuthStore(db_path=str(db))
    store1.create_user(username="alice", password="pw", tenant_id="t_alice", role="user")

    store2 = SQLiteAuthStore(db_path=str(db))
    user = store2.authenticate(username="alice", password="pw")
    assert user is not None
    assert user.username == "alice"
    assert user.tenant_id == "t_alice"
    assert user.role == "user"


@pytest.mark.unit
def test_sqlite_auth_store_persists_admin_role(tmp_path):
    os.environ.setdefault("AUTH_REFRESH_TOKEN_HASH_SECRET", "test-secret")
    db = tmp_path / "portal_auth.db"

    store = SQLiteAuthStore(db_path=str(db))
    store.create_user(
        username="root", password="pw", tenant_id="tenant_acme", role="admin"
    )

    reloaded = SQLiteAuthStore(db_path=str(db)).get_user("root")
    assert reloaded is not None
    assert reloaded.role == "admin"


@pytest.mark.unit
def test_sqlite_auth_store_migrates_legacy_role_column(tmp_path):
    import sqlite3

    db = tmp_path / "portal_auth.db"
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            """
            CREATE TABLE portal_users (
              username TEXT PRIMARY KEY,
              password_hash TEXT NOT NULL,
              tenant_id TEXT NOT NULL,
              created_at INTEGER NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO portal_users(username, password_hash, tenant_id, created_at) VALUES (?,?,?,?)",
            ("root", "legacy-hash", "admin_root", 1),
        )

    store = SQLiteAuthStore(db_path=str(db))
    user = store.get_user("root")

    assert user is not None
    assert user.role == "admin"
