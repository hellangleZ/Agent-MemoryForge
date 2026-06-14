from fastapi import FastAPI

from agent_memory_service.gateway import app as service_app


def test_gateway_app_exports_fastapi_app():
    assert isinstance(service_app.app, FastAPI)
