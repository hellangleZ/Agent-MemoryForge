from __future__ import annotations

import os
from typing import Any, Tuple


LLM_PROVIDER_CONFIGURATION_ERROR_MESSAGE = (
    "LLM provider is not configured for this deployment. Configure provider "
    "credentials and restart the gateway."
)


class LLMProviderConfigurationError(RuntimeError):
    """Raised when the deployment has no usable LLM provider credentials."""


def _normalized_llm_provider() -> str | None:
    v = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    return v or None


def create_openai_like_client() -> Tuple[Any, str]:
    """Create an OpenAI-compatible client.

    This project standardizes on OpenAI-compatible APIs (including the
    Azure OpenAI *OpenAI-compatible* endpoints). Prefer configuring these env
    vars:
    - OPENAI_BASE_URL
    - OPENAI_API_KEY
    - OPENAI_MODEL

    Back-compat: if OPENAI_* are missing, falls back to AZURE_OPENAI_*.
    """

    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "openai package is required for create_openai_like_client()"
        ) from exc

    provider = _normalized_llm_provider()

    # When LLM_PROVIDER is explicitly set, do not fall back across providers.
    if provider in {"openai-like", "openai_like", "openai"}:
        base_url = os.getenv("OPENAI_BASE_URL")
        api_key = os.getenv("OPENAI_API_KEY")
    elif provider in {"azure", "azure-openai", "azure_openai"}:
        base_url = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
    else:
        base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY")

    # In OpenAI-compatible mode, `model` should be deployment name for Azure.
    model_name = (
        os.getenv("OPENAI_MODEL")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_MODEL")
        or "gpt-4o-mini"
    )

    if not base_url or not api_key:  # pragma: no cover
        raise LLMProviderConfigurationError(LLM_PROVIDER_CONFIGURATION_ERROR_MESSAGE)

    # Some Azure endpoints require api-version as query.
    # Only apply AZURE_OPENAI_API_VERSION when provider is explicitly azure.
    api_version = None
    if provider in {"azure", "azure-openai", "azure_openai"}:
        api_version = os.getenv("AZURE_OPENAI_API_VERSION")
    # Allow OPENAI_API_VERSION for truly OpenAI-like proxies if user set it.
    if not api_version:
        api_version = os.getenv("OPENAI_API_VERSION")
    client_kwargs: dict[str, Any] = {"base_url": base_url}
    if api_version:
        client_kwargs["default_query"] = {"api-version": api_version}

    client = OpenAI(api_key=api_key, timeout=60.0, **client_kwargs)
    return client, model_name


# Backwards compatibility: keep old name used across the product layer.
def create_azure_openai_client() -> Tuple[Any, str]:
    return create_openai_like_client()
