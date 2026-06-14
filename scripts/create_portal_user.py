#!/usr/bin/env python
"""Create or update a local Agent-MemoryForge Portal user.

The script writes to the same SQLite auth database mounted into the local
Gateway container. It intentionally prompts for passwords by default so README
quick-start commands do not teach users to put credentials in shell history.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = REPO_ROOT / ".runtime" / "portal_auth.db"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_runtime.product.auth_store import SQLiteAuthStore


def _read_password(*, password_stdin: bool) -> str:
    if password_stdin:
        password = sys.stdin.readline().rstrip("\n")
        if not password:
            raise ValueError("password from stdin is empty")
        return password

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise ValueError("passwords do not match")
    return password


def create_portal_user(
    *,
    db_path: Path,
    username: str,
    tenant_id: str,
    role: str,
    password: str,
    replace_password: bool = False,
) -> str:
    username = username.strip()
    tenant_id = tenant_id.strip()
    role = role.strip().lower()

    if not username:
        raise ValueError("username is required")
    if not tenant_id:
        raise ValueError("tenant id is required")
    if role not in {"admin", "user"}:
        raise ValueError("role must be admin or user")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")

    store = SQLiteAuthStore(db_path=str(db_path))
    existing = store.get_user(username)
    if existing:
        if not replace_password:
            raise ValueError(
                f"user {username!r} already exists; pass --replace-password to update it"
            )
        store.update_user(username=username, tenant_id=tenant_id, role=role)
        store.update_password(username=username, new_password=password)
        return "updated"

    store.create_user(
        username=username,
        password=password,
        tenant_id=tenant_id,
        role=role,
    )
    return "created"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a local Portal user in .runtime/portal_auth.db."
    )
    parser.add_argument("--username", required=True, help="Portal username")
    parser.add_argument(
        "--tenant-id",
        default="admin",
        help="Tenant id for the user (default: admin)",
    )
    parser.add_argument(
        "--role",
        choices=["admin", "user"],
        default="admin",
        help="Portal role (default: admin)",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(os.getenv("PORTAL_AUTH_DB", DEFAULT_DB_PATH)),
        help=f"SQLite auth DB path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read one password line from stdin for automation",
    )
    parser.add_argument(
        "--replace-password",
        action="store_true",
        help="Update tenant/role/password when the user already exists",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        password = _read_password(password_stdin=bool(args.password_stdin))
        action = create_portal_user(
            db_path=args.db_path,
            username=args.username,
            tenant_id=args.tenant_id,
            role=args.role,
            password=password,
            replace_password=bool(args.replace_password),
        )
    except Exception as exc:
        print(f"create_portal_user failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Portal user {args.username!r} {action} "
        f"(tenant_id={args.tenant_id!r}, role={args.role!r}, db={args.db_path})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
