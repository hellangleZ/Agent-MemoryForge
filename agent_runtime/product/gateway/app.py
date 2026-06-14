# -*- coding: utf-8 -*-
"""FastAPI app wiring for Agent Gateway."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.dependencies.utils import get_dependant
from fastapi.routing import APIRoute

from agent_runtime.product.gateway.core_routes import router as core_router
from agent_runtime.product.gateway.portal_routes import router as portal_router
from agent_runtime.product.gateway.rate_limit import LoginRateLimitMiddleware
from utils.logging_config import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    dotenv_path = os.getenv("DOTENV_PATH")
    if dotenv_path:
        load_dotenv(dotenv_path)
    else:
        load_dotenv(dotenv_path=".env")

    try:
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            if route.path in {
                "/portal/v1/workspace/config",
            }:
                dependant = get_dependant(path=route.path_format, call=route.endpoint)
                route.dependant = dependant
                route.body_field = (
                    dependant.body_params[0] if dependant.body_params else None
                )
    except Exception as exc:  # noqa: BLE001
        # Route re-binding is a best-effort startup optimization; if it fails
        # the app still serves, but log it so a real misconfiguration is visible
        # instead of silently swallowed.
        logger.warning("workspace route re-bind skipped: %s", exc)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Agent Gateway API", version="2.0.0", lifespan=lifespan)
    app.add_middleware(LoginRateLimitMiddleware)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower() in {
            "prod",
            "production",
        }:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response

    app.include_router(core_router)
    app.include_router(portal_router)
    return app


app = create_app()

__all__ = ["app", "create_app"]
