from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import jwt

_DEV_SECRET = "dev-secret"


def _is_production() -> bool:
    env = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    return env in {"prod", "production"}


def _jwt_secret() -> str:
    # For production deployments this must be set to a strong, unique value.
    secret = os.getenv("AUTH_JWT_SECRET", _DEV_SECRET)
    if _is_production() and secret == _DEV_SECRET:
        raise RuntimeError(
            "AUTH_JWT_SECRET must be set to a non-default value in production "
            "(APP_ENV/ENVIRONMENT=production)."
        )
    return secret


def _jwt_algorithm() -> str:
    return os.getenv("AUTH_JWT_ALG", "HS256")


def create_access_token(
    *, sub: str, tenant_id: str, expires_in_s: int, aud: str = "portal"
) -> str:
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": sub,
        "tenant_id": tenant_id,
        "aud": aud,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_s)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=_jwt_algorithm())


def decode_access_token(token: str, *, aud: str = "portal") -> Dict[str, Any]:
    return jwt.decode(token, _jwt_secret(), algorithms=[_jwt_algorithm()], audience=aud)
