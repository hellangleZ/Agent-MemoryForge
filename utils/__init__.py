# -*- coding: utf-8 -*-
"""Utilities package.

This repo supports a "minimal install" (library-only) where gateway/service
dependencies are not installed.

Do not import optional third-party dependencies at import time. In particular,
`RedisHelper` depends on the `redis` package, so it is loaded lazily.
"""

from __future__ import annotations

from typing import Any

from .retry_helper import retry_request

__all__ = ["retry_request", "RedisHelper"]


def __getattr__(name: str) -> Any:
    if name == "RedisHelper":
        from .redis_helper import RedisHelper

        return RedisHelper
    raise AttributeError(name)

