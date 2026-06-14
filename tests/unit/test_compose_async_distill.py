from __future__ import annotations

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


def _env_map(environment: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in environment:
        key, _, value = item.partition("=")
        out[key] = value
    return out


@pytest.mark.unit
@pytest.mark.parametrize("compose_file", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_compose_starts_async_distill_worker(compose_file: str) -> None:
    config = yaml.safe_load((ROOT / compose_file).read_text())
    services = config["services"]

    gateway_env = _env_map(services["gateway"].get("environment", []))
    worker = services["distill_worker"]
    worker_env = _env_map(worker.get("environment", []))

    assert gateway_env["MEMORY_DISTILL_ENABLED"] == "${MEMORY_DISTILL_ENABLED:-1}"
    assert gateway_env["MEMORY_DISTILL_EVERY_N_ROUNDS"] == "${MEMORY_DISTILL_EVERY_N_ROUNDS:-1}"
    assert "PREFERENCE_EXTRACT_LLM_WHEN_NO_RULE" not in gateway_env

    assert worker["command"] == ["python", "-m", "scripts.memory_distill_worker"]
    assert worker_env["MEMORY_DISTILL_ENABLED"] == "${MEMORY_DISTILL_ENABLED:-1}"
    assert worker_env["MEMORY_DISTILL_STORE_PREFERENCES"] == "${MEMORY_DISTILL_STORE_PREFERENCES:-1}"
    assert worker_env["MEMORY_DISTILL_PREFERENCE_REQUIRE_CONFIRMATION"] == "${MEMORY_DISTILL_PREFERENCE_REQUIRE_CONFIRMATION:-0}"
    assert set(worker["depends_on"]) >= {"redis", "memory"}
