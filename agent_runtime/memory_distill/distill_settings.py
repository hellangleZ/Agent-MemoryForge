from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryDistillSettings:
    enabled: bool = False

    # Redis queue
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_max_connections: int = 20

    queue_key: str = "am:distill:queue"
    dedupe_set_key: str = "am:distill:dedupe"
    dedupe_ttl_s: int = 7 * 24 * 3600

    # Worker behavior
    job_result_prefix: str = "am:distill:job:"
    job_result_ttl_s: int = 7 * 24 * 3600
    max_attempts: int = 5

    # Retry tuning for LLM rate limits
    llm_max_attempts: int = 8
    llm_retry_base_sleep_s: float = 0.8
    timeout_s: float = 45.0

    # LLM provider (separate from main reasoning)
    provider: str = "openai-like"  # openai-like|azure
    model: str = "gpt-4o-mini"
    temperature: float = 0.2
    max_output_tokens: int = 800

    # OpenAI-like
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    api_style: str = "auto"

    # Azure
    azure_api_key: str | None = None
    azure_endpoint: str | None = None
    azure_deployment: str | None = None
    azure_api_version: str = "2024-02-15-preview"

    @classmethod
    def from_env(cls) -> "MemoryDistillSettings":
        def _bool(name: str, default: bool) -> bool:
            val = os.getenv(name)
            if val is None:
                return default
            return val.strip().lower() in {"1", "true", "yes", "y", "on"}

        def _int(name: str, default: int) -> int:
            val = os.getenv(name)
            if val is None or not val.strip():
                return default
            return int(val)

        def _float(name: str, default: float) -> float:
            val = os.getenv(name)
            if val is None or not val.strip():
                return default
            return float(val)

        def _str(name: str, default: str) -> str:
            val = os.getenv(name)
            return (val.strip() if val and val.strip() else default)

        return cls(
            enabled=_bool("MEMORY_DISTILL_ENABLED", False),
            redis_host=_str("REDIS_HOST", "localhost"),
            redis_port=_int("REDIS_PORT", 6379),
            redis_db=_int("REDIS_DB", 0),
            redis_max_connections=_int("REDIS_MAX_CONNECTIONS", 20),
            queue_key=_str("MEMORY_DISTILL_QUEUE_KEY", cls.queue_key),
            dedupe_set_key=_str("MEMORY_DISTILL_DEDUPE_SET_KEY", cls.dedupe_set_key),
            dedupe_ttl_s=_int("MEMORY_DISTILL_DEDUPE_TTL_S", cls.dedupe_ttl_s),
            job_result_prefix=_str(
                "MEMORY_DISTILL_JOB_RESULT_PREFIX", cls.job_result_prefix
            ),
            job_result_ttl_s=_int("MEMORY_DISTILL_JOB_RESULT_TTL_S", cls.job_result_ttl_s),
            max_attempts=_int("MEMORY_DISTILL_MAX_ATTEMPTS", cls.max_attempts),

            llm_max_attempts=_int(
                "MEMORY_DISTILL_LLM_MAX_ATTEMPTS",
                _int("MEMORY_DISTILL_MAX_ATTEMPTS", cls.llm_max_attempts),
            ),
            llm_retry_base_sleep_s=_float(
                "MEMORY_DISTILL_RETRY_BASE_SLEEP_S",
                cls.llm_retry_base_sleep_s,
            ),
            timeout_s=_float("MEMORY_DISTILL_TIMEOUT_S", cls.timeout_s),
            provider=_str(
                "MEMORY_DISTILL_PROVIDER",
                (os.getenv("LLM_PROVIDER") or cls.provider),
            ),
            # In Azure/OpenAI-compatible setups, "model" is typically a deployment name.
            # Default to the main configured model/deployment to avoid accidental 404s.
            model=_str(
                "MEMORY_DISTILL_MODEL",
                (
                    os.getenv("OPENAI_MODEL")
                    or os.getenv("AZURE_OPENAI_DEPLOYMENT")
                    or cls.model
                ),
            ),
            temperature=_float("MEMORY_DISTILL_TEMPERATURE", cls.temperature),
            max_output_tokens=_int(
                "MEMORY_DISTILL_MAX_OUTPUT_TOKENS", cls.max_output_tokens
            ),
            openai_api_key=os.getenv("MEMORY_DISTILL_OPENAI_API_KEY")
            or os.getenv("OPENAI_API_KEY"),
            openai_base_url=os.getenv("MEMORY_DISTILL_OPENAI_BASE_URL")
            or os.getenv("OPENAI_BASE_URL"),
            api_style=_str(
                "MEMORY_DISTILL_OPENAI_API_STYLE",
                os.getenv("OPENAI_API_STYLE")
                or os.getenv("LLM_API_STYLE")
                or cls.api_style,
            ),
            azure_api_key=os.getenv("MEMORY_DISTILL_AZURE_OPENAI_API_KEY")
            or os.getenv("AZURE_OPENAI_API_KEY"),
            azure_endpoint=os.getenv("MEMORY_DISTILL_AZURE_OPENAI_ENDPOINT")
            or os.getenv("AZURE_OPENAI_ENDPOINT"),
            azure_deployment=os.getenv("MEMORY_DISTILL_AZURE_OPENAI_DEPLOYMENT")
            or os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            azure_api_version=_str(
                "MEMORY_DISTILL_AZURE_OPENAI_API_VERSION",
                os.getenv("AZURE_OPENAI_API_VERSION", cls.azure_api_version),
            ),
        )
