from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ContextPlannerSettings:
    """Dedicated LLM config for context planning (separate budget/keys).

    This is intentionally separate from both the main reasoning LLM and the
    distillation worker LLM.
    """

    enabled: bool = False

    provider: str = "openai-like"  # openai-like|azure
    model: str = "gpt-4o-mini"
    temperature: float = 0.1
    max_output_tokens: int = 600

    # OpenAI-like
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    api_style: str = "auto"

    # Azure
    azure_api_key: str | None = None
    azure_endpoint: str | None = None
    azure_deployment: str | None = None
    azure_api_version: str = "2024-02-15-preview"

    # Retry / rate limit handling
    max_attempts: int = 6
    retry_base_sleep_s: float = 0.5

    @classmethod
    def from_env(cls) -> "ContextPlannerSettings":
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
            enabled=_bool("CONTEXT_PLANNER_ENABLED", False),
            provider=_str("CONTEXT_PLANNER_PROVIDER", cls.provider),
            model=_str("CONTEXT_PLANNER_MODEL", cls.model),
            temperature=_float("CONTEXT_PLANNER_TEMPERATURE", cls.temperature),
            max_output_tokens=_int(
                "CONTEXT_PLANNER_MAX_OUTPUT_TOKENS", cls.max_output_tokens
            ),
            max_attempts=_int("CONTEXT_PLANNER_MAX_ATTEMPTS", cls.max_attempts),
            retry_base_sleep_s=_float(
                "CONTEXT_PLANNER_RETRY_BASE_SLEEP_S", cls.retry_base_sleep_s
            ),
            openai_api_key=os.getenv("CONTEXT_PLANNER_OPENAI_API_KEY"),
            openai_base_url=os.getenv("CONTEXT_PLANNER_OPENAI_BASE_URL"),
            api_style=_str(
                "CONTEXT_PLANNER_OPENAI_API_STYLE",
                os.getenv("OPENAI_API_STYLE")
                or os.getenv("LLM_API_STYLE")
                or cls.api_style,
            ),
            azure_api_key=os.getenv("CONTEXT_PLANNER_AZURE_OPENAI_API_KEY"),
            azure_endpoint=os.getenv("CONTEXT_PLANNER_AZURE_OPENAI_ENDPOINT"),
            azure_deployment=os.getenv("CONTEXT_PLANNER_AZURE_OPENAI_DEPLOYMENT"),
            azure_api_version=_str(
                "CONTEXT_PLANNER_AZURE_OPENAI_API_VERSION",
                os.getenv("CONTEXT_PLANNER_AZURE_OPENAI_API_VERSION", cls.azure_api_version),
            ),
        )
