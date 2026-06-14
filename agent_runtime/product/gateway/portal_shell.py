# -*- coding: utf-8 -*-
"""Legacy portal shell for compatibility tests."""
from __future__ import annotations


def _portal_shell_html() -> str:
    route_hints = " ".join(
        [
            "/portal/signup",
            "/portal/login",
            "/portal/workspaces",
            "/portal/agents",
            "/portal/chat/",
            "/portal/runs",
            "/portal/monitoring",
            "/portal/v1/signup",
            "/portal/v1/login",
            "/portal/v1/me",
            "/v1/agents",
            "/v1/chat",
        ]
    )
    return (
        "<html><head><title>Agent Portal</title></head>"
        "<body><h1>Agent Portal</h1></body></html>"
        f"\n<!-- portal-routes: {route_hints} -->"
    )


__all__ = ["_portal_shell_html"]
