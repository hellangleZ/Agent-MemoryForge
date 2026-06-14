# -*- coding: utf-8 -*-
"""E) Conservative per-IP rate limiting for auth endpoints (brute-force / abuse guard).

Only throttles POSTs to login/signup/token-refresh. Defaults are generous so real
users are unaffected; tune via env. Disable with LOGIN_RATE_LIMIT_DISABLED=1.
In-memory sliding window (per process) - good enough for a single gateway worker;
move to Redis if you scale to multiple workers.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

_AUTH_PATHS = {
    "/portal/v1/login",
    "/portal/v1/signup",
    "/portal/v1/token/refresh",
}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except Exception:
        return default


class LoginRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._max = max(1, _int_env("LOGIN_RATE_LIMIT_MAX", 20))
        self._window = float(max(1, _int_env("LOGIN_RATE_LIMIT_WINDOW_S", 60)))
        self._disabled = str(os.getenv("LOGIN_RATE_LIMIT_DISABLED", "")).strip().lower() in {
            "1", "true", "yes", "on",
        }
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def _client_ip(request) -> str:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request, call_next):
        if (
            self._disabled
            or request.method != "POST"
            or request.url.path not in _AUTH_PATHS
        ):
            return await call_next(request)

        ip = self._client_ip(request)
        now = time.time()
        with self._lock:
            dq = self._hits[ip]
            while dq and now - dq[0] > self._window:
                dq.popleft()
            if len(dq) >= self._max:
                retry_after = int(self._window - (now - dq[0])) + 1
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many attempts; please slow down."},
                    headers={"Retry-After": str(max(1, retry_after))},
                )
            dq.append(now)
            # opportunistic cleanup to bound memory
            if len(self._hits) > 10000:
                stale = [k for k, v in self._hits.items() if not v or now - v[-1] > self._window]
                for k in stale[:5000]:
                    self._hits.pop(k, None)
        return await call_next(request)
