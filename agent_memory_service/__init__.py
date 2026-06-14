"""Memory Service package.

This package hosts the FastAPI memory service without import-time side effects.
Use `agent_memory_service.app:create_app()` to build the application.
"""

from agent_memory_service.app import create_app

__all__ = ["create_app"]
