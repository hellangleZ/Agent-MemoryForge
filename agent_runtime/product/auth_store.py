from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _refresh_token_ttl_s() -> int:
    try:
        return max(1, int(os.getenv("AUTH_REFRESH_TOKEN_TTL_S", "2592000")))
    except Exception:
        return 2592000


def _is_admin_tenant_id(tenant_id: str) -> bool:
    tenant = str(tenant_id or "").strip()
    return (
        tenant == "admin" or tenant.startswith("admin_") or tenant.startswith("admin:")
    )


def normalize_user_role(role: Optional[str], *, tenant_id: str = "") -> str:
    raw = str(role or "").strip().lower()
    if raw in {"admin", "administrator", "owner"}:
        return "admin"
    if raw in {"user", "member", "employee", "staff"}:
        return "user"
    return "admin" if _is_admin_tenant_id(tenant_id) else "user"


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _pbkdf2_hash(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def hash_password(password: str, *, iterations: int = 150_000) -> str:
    salt = secrets.token_bytes(16)
    digest = _pbkdf2_hash(password, salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64url(salt)}${_b64url(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations_s, salt_b64, digest_b64 = password_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_s)

        import base64

        salt = base64.urlsafe_b64decode(salt_b64 + "==")
        expected = base64.urlsafe_b64decode(digest_b64 + "==")
        got = _pbkdf2_hash(password, salt, iterations)
        return hmac.compare_digest(got, expected)
    except Exception:
        return False


def hash_refresh_token(refresh_token: str) -> str:
    secret = os.getenv("AUTH_REFRESH_TOKEN_HASH_SECRET", "dev-secret")
    if secret == "dev-secret":
        env = (
            os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or ""
        ).strip().lower()
        if env in {"prod", "production"}:
            raise RuntimeError(
                "AUTH_REFRESH_TOKEN_HASH_SECRET must be set to a non-default "
                "value in production (APP_ENV/ENVIRONMENT=production)."
            )
    return hmac.new(
        secret.encode("utf-8"), refresh_token.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


@dataclass
class UserRecord:
    username: str
    password_hash: str
    tenant_id: str
    role: str = "user"
    created_at: Optional[int] = None


@dataclass
class RefreshRecord:
    family_id: str
    token_hash: str
    username: str
    tenant_id: str
    revoked: bool
    issued_at: int
    expires_at: int


class InMemoryAuthStore:
    def __init__(self) -> None:
        self._users_by_username: Dict[str, UserRecord] = {}
        self._refresh_by_hash: Dict[str, RefreshRecord] = {}
        self._family_revoked: Dict[str, bool] = {}

    def create_user(
        self, *, username: str, password: str, tenant_id: str, role: Optional[str] = None
    ) -> UserRecord:
        if username in self._users_by_username:
            raise ValueError("user already exists")
        record = UserRecord(
            username=username,
            password_hash=hash_password(password),
            tenant_id=tenant_id,
            role=normalize_user_role(role, tenant_id=tenant_id),
            created_at=_now_ts(),
        )
        self._users_by_username[username] = record
        return record

    def get_user(self, username: str) -> Optional[UserRecord]:
        return self._users_by_username.get(username)

    def list_users(self) -> list[UserRecord]:
        return list(self._users_by_username.values())

    def authenticate(self, *, username: str, password: str) -> Optional[UserRecord]:
        record = self.get_user(username)
        if not record:
            return None
        if not verify_password(password, record.password_hash):
            return None
        return record

    def update_password(self, *, username: str, new_password: str) -> None:
        record = self.get_user(username)
        if not record:
            raise ValueError("user not found")
        # Replace the whole record rather than mutating in place so a concurrent
        # authenticate() never observes a half-written password_hash.
        self._users_by_username[username] = UserRecord(
            username=record.username,
            password_hash=hash_password(new_password),
            tenant_id=record.tenant_id,
            role=record.role,
            created_at=record.created_at,
        )

    def revoke_refresh_tokens_for_user(self, *, username: str) -> int:
        revoked = 0
        for rec in self._refresh_by_hash.values():
            if rec.username != username:
                continue
            if not rec.revoked:
                revoked += 1
            rec.revoked = True
            self._family_revoked[rec.family_id] = True
        return revoked

    def update_user(
        self,
        *,
        username: str,
        tenant_id: Optional[str] = None,
        role: Optional[str] = None,
    ) -> UserRecord:
        record = self.get_user(username)
        if not record:
            raise ValueError("user not found")
        next_tenant = str(tenant_id if tenant_id is not None else record.tenant_id).strip()
        if not next_tenant:
            raise ValueError("tenant_id required")
        next_role = (
            normalize_user_role(role, tenant_id=next_tenant)
            if role is not None
            else record.role
        )
        updated = UserRecord(
            username=record.username,
            password_hash=record.password_hash,
            tenant_id=next_tenant,
            role=next_role,
            created_at=record.created_at,
        )
        self._users_by_username[username] = updated
        return updated

    def delete_user(self, *, username: str) -> None:
        if username not in self._users_by_username:
            raise ValueError("user not found")
        del self._users_by_username[username]
        for token_hash, rec in list(self._refresh_by_hash.items()):
            if rec.username == username:
                del self._refresh_by_hash[token_hash]

    def issue_refresh(self, *, username: str, tenant_id: str, family_id: str) -> str:
        token = generate_refresh_token()
        token_hash = hash_refresh_token(token)
        self._refresh_by_hash[token_hash] = RefreshRecord(
            family_id=family_id,
            token_hash=token_hash,
            username=username,
            tenant_id=tenant_id,
            revoked=False,
            issued_at=_now_ts(),
            expires_at=_now_ts() + _refresh_token_ttl_s(),
        )
        return token

    def revoke_refresh_family(self, family_id: str) -> None:
        self._family_revoked[family_id] = True
        for rec in self._refresh_by_hash.values():
            if rec.family_id == family_id:
                rec.revoked = True

    def validate_and_rotate_refresh(self, refresh_token: str) -> RefreshRecord:
        token_hash = hash_refresh_token(refresh_token)
        rec = self._refresh_by_hash.get(token_hash)
        if not rec:
            raise ValueError("invalid refresh token")
        if self._family_revoked.get(rec.family_id, False):
            raise ValueError("refresh token family revoked")
        if int(getattr(rec, "expires_at", 0) or 0) <= _now_ts():
            rec.revoked = True
            self._refresh_by_hash[token_hash] = rec
            raise ValueError("refresh token expired")
        if rec.revoked:
            self.revoke_refresh_family(rec.family_id)
            raise ValueError("refresh token reuse detected")

        rec.revoked = True
        self._refresh_by_hash[token_hash] = rec
        return rec


class SQLiteAuthStore:
    """SQLite-backed auth store.

    Stores users and refresh-token material in a local SQLite DB so portal auth
    survives process restarts.
    """

    def __init__(self, *, db_path: str) -> None:
        self._db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS portal_users (
                  username TEXT PRIMARY KEY,
                  password_hash TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  role TEXT NOT NULL DEFAULT 'user',
                  created_at INTEGER NOT NULL
                );
                """
            )
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(portal_users)").fetchall()
            }
            if "role" not in columns:
                conn.execute(
                    "ALTER TABLE portal_users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"
                )
            conn.execute(
                """
                UPDATE portal_users
                   SET role='admin'
                 WHERE (tenant_id='admin' OR tenant_id LIKE 'admin_%' OR tenant_id LIKE 'admin:%')
                   AND (role IS NULL OR role='' OR role='user')
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS portal_refresh_tokens (
                  token_hash TEXT PRIMARY KEY,
                  family_id TEXT NOT NULL,
                  username TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  revoked INTEGER NOT NULL,
                  issued_at INTEGER NOT NULL,
                  expires_at INTEGER NOT NULL,
                  FOREIGN KEY(username) REFERENCES portal_users(username)
                );
                """
            )
            refresh_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(portal_refresh_tokens)").fetchall()
            }
            if "expires_at" not in refresh_columns:
                conn.execute(
                    "ALTER TABLE portal_refresh_tokens ADD COLUMN expires_at INTEGER NOT NULL DEFAULT 0"
                )
                conn.execute(
                    "UPDATE portal_refresh_tokens SET expires_at=issued_at+? WHERE expires_at=0",
                    (_refresh_token_ttl_s(),),
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS portal_refresh_families (
                  family_id TEXT PRIMARY KEY,
                  revoked INTEGER NOT NULL
                );
                """
            )

    def create_user(
        self, *, username: str, password: str, tenant_id: str, role: Optional[str] = None
    ) -> UserRecord:
        created_at = _now_ts()
        record = UserRecord(
            username=username,
            password_hash=hash_password(password),
            tenant_id=tenant_id,
            role=normalize_user_role(role, tenant_id=tenant_id),
            created_at=created_at,
        )
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO portal_users(username, password_hash, tenant_id, role, created_at) VALUES (?,?,?,?,?)",
                    (
                        record.username,
                        record.password_hash,
                        record.tenant_id,
                        record.role,
                        created_at,
                    ),
                )
        except sqlite3.IntegrityError as e:
            raise ValueError("user already exists") from e
        return record

    def get_user(self, username: str) -> Optional[UserRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT username, password_hash, tenant_id, role, created_at FROM portal_users WHERE username=?",
                (username,),
            ).fetchone()
        if not row:
            return None
        return UserRecord(
            username=str(row["username"]),
            password_hash=str(row["password_hash"]),
            tenant_id=str(row["tenant_id"]),
            role=normalize_user_role(row["role"], tenant_id=str(row["tenant_id"])),
            created_at=int(row["created_at"]),
        )

    def list_users(self) -> list[UserRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT username, password_hash, tenant_id, role, created_at FROM portal_users"
            ).fetchall()
        return [
            UserRecord(
                username=str(row["username"]),
                password_hash=str(row["password_hash"]),
                tenant_id=str(row["tenant_id"]),
                role=normalize_user_role(row["role"], tenant_id=str(row["tenant_id"])),
                created_at=int(row["created_at"]),
            )
            for row in rows
        ]

    def authenticate(self, *, username: str, password: str) -> Optional[UserRecord]:
        record = self.get_user(username)
        if not record:
            return None
        if not verify_password(password, record.password_hash):
            return None
        return record

    def update_password(self, *, username: str, new_password: str) -> None:
        password_hash = hash_password(new_password)
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE portal_users SET password_hash=? WHERE username=?",
                (password_hash, username),
            )
        if cur.rowcount == 0:
            raise ValueError("user not found")

    def revoke_refresh_tokens_for_user(self, *, username: str) -> int:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT family_id FROM portal_refresh_tokens WHERE username=?",
                (username,),
            ).fetchall()
            family_ids = [str(row["family_id"]) for row in rows]
            cur = conn.execute(
                "UPDATE portal_refresh_tokens SET revoked=1 WHERE username=? AND revoked=0",
                (username,),
            )
            for family_id in family_ids:
                conn.execute(
                    "INSERT OR REPLACE INTO portal_refresh_families(family_id, revoked) VALUES (?,1)",
                    (family_id,),
                )
        return int(cur.rowcount or 0)

    def update_user(
        self,
        *,
        username: str,
        tenant_id: Optional[str] = None,
        role: Optional[str] = None,
    ) -> UserRecord:
        current = self.get_user(username)
        if not current:
            raise ValueError("user not found")
        next_tenant = str(tenant_id if tenant_id is not None else current.tenant_id).strip()
        if not next_tenant:
            raise ValueError("tenant_id required")
        next_role = (
            normalize_user_role(role, tenant_id=next_tenant)
            if role is not None
            else current.role
        )
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE portal_users SET tenant_id=?, role=? WHERE username=?",
                (next_tenant, next_role, username),
            )
        if cur.rowcount == 0:
            raise ValueError("user not found")
        updated = self.get_user(username)
        if not updated:
            raise ValueError("user not found")
        return updated

    def delete_user(self, *, username: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM portal_refresh_tokens WHERE username=?", (username,))
            cur = conn.execute("DELETE FROM portal_users WHERE username=?", (username,))
        if cur.rowcount == 0:
            raise ValueError("user not found")

    def issue_refresh(self, *, username: str, tenant_id: str, family_id: str) -> str:
        token = generate_refresh_token()
        token_hash = hash_refresh_token(token)
        issued_at = _now_ts()
        expires_at = issued_at + _refresh_token_ttl_s()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO portal_refresh_tokens(token_hash, family_id, username, tenant_id, revoked, issued_at, expires_at) VALUES (?,?,?,?,?,?,?)",
                (token_hash, family_id, username, tenant_id, 0, issued_at, expires_at),
            )
        return token

    def revoke_refresh_family(self, family_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO portal_refresh_families(family_id, revoked) VALUES (?,1)",
                (family_id,),
            )
            conn.execute(
                "UPDATE portal_refresh_tokens SET revoked=1 WHERE family_id=?",
                (family_id,),
            )

    def validate_and_rotate_refresh(self, refresh_token: str) -> RefreshRecord:
        token_hash = hash_refresh_token(refresh_token)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT family_id, token_hash, username, tenant_id, revoked, issued_at, expires_at FROM portal_refresh_tokens WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
            if not row:
                raise ValueError("invalid refresh token")

            fam = conn.execute(
                "SELECT revoked FROM portal_refresh_families WHERE family_id=?",
                (row["family_id"],),
            ).fetchone()
            if fam and int(fam["revoked"]) == 1:
                raise ValueError("refresh token family revoked")

            if int(row["expires_at"]) <= _now_ts():
                conn.execute(
                    "UPDATE portal_refresh_tokens SET revoked=1 WHERE token_hash=?",
                    (token_hash,),
                )
                raise ValueError("refresh token expired")

            if int(row["revoked"]) == 1:
                # Reuse detected.
                conn.execute(
                    "INSERT OR REPLACE INTO portal_refresh_families(family_id, revoked) VALUES (?,1)",
                    (row["family_id"],),
                )
                conn.execute(
                    "UPDATE portal_refresh_tokens SET revoked=1 WHERE family_id=?",
                    (row["family_id"],),
                )
                raise ValueError("refresh token reuse detected")

            conn.execute(
                "UPDATE portal_refresh_tokens SET revoked=1 WHERE token_hash=?",
                (token_hash,),
            )

        return RefreshRecord(
            family_id=str(row["family_id"]),
            token_hash=str(row["token_hash"]),
            username=str(row["username"]),
            tenant_id=str(row["tenant_id"]),
            revoked=True,
            issued_at=int(row["issued_at"]),
            expires_at=int(row["expires_at"]),
        )
