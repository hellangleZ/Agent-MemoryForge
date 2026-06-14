from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_compose_memory_service_requires_internal_api_key_and_is_not_host_published():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    memory_block = compose.split("  memory:", 1)[1].split("  gateway:", 1)[0]

    assert "AGENT_MEMORY_SERVICE_API_KEY=${AGENT_MEMORY_SERVICE_API_KEY:?set AGENT_MEMORY_SERVICE_API_KEY}" in memory_block
    assert "ports:" not in memory_block
    assert 'expose:' in memory_block


def test_gateway_and_distill_worker_receive_internal_memory_key():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    gateway_block = compose.split("  gateway:", 1)[1].split("  distill_worker:", 1)[0]
    worker_block = compose.split("  distill_worker:", 1)[1].split("  portal:", 1)[0]

    required = "AGENT_MEMORY_SERVICE_API_KEY=${AGENT_MEMORY_SERVICE_API_KEY:?set AGENT_MEMORY_SERVICE_API_KEY}"
    assert required in gateway_block
    assert required in worker_block


def test_local_compose_does_not_embed_default_secrets():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "agent_memory_dev_password" not in compose
    assert "dev-secret" not in compose
    assert "dev-gateway-key" not in compose
    assert "POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}" in compose
    assert "NEO4J_PASSWORD=${NEO4J_PASSWORD:?set NEO4J_PASSWORD}" in compose
    assert "AUTH_JWT_SECRET=${AUTH_JWT_SECRET:?set AUTH_JWT_SECRET}" in compose
    assert (
        "AUTH_REFRESH_TOKEN_HASH_SECRET=${AUTH_REFRESH_TOKEN_HASH_SECRET:?set AUTH_REFRESH_TOKEN_HASH_SECRET}"
        in compose
    )
    assert "PORTAL_SECRETS_KEY=${PORTAL_SECRETS_KEY:?set PORTAL_SECRETS_KEY}" in compose


def test_prod_gateway_requires_workspace_secret_encryption_key():
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    gateway_block = compose.split("  gateway:", 1)[1].split("  distill_worker:", 1)[0]

    assert "PORTAL_SECRETS_KEY=${PORTAL_SECRETS_KEY:?set PORTAL_SECRETS_KEY in .env}" in gateway_block
