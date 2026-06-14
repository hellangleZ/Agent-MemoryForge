from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from agent_memory_framework.llm import CallableLLMProvider
from agent_memory_framework.llm_clients import create_azure_openai_client


try:  # pragma: no cover
    from openai import OpenAI as OpenAI  # type: ignore
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


@dataclass(frozen=True)
class ResolvedLLMProvider:
    provider: Any
    provider_name: str


def _get(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    return getattr(config, name, default)


def resolve_llm_provider_name(config: Any = None) -> Optional[str]:
    """Resolve LLM provider name with config-first, env-fallback.

    Supported:
    - config.llm_provider_name / config.llm_provider: str
    - env: LLM_PROVIDER
    """

    for key in ("llm_provider_name", "llm_provider"):
        value = _get(config, key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    env_value = os.getenv("LLM_PROVIDER")
    if env_value and env_value.strip():
        return env_value.strip()
    return None


def _has_azure_env() -> bool:
    return bool(
        os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_API_KEY")
    )


def _has_openai_like_env() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _normalize_api_style(value: str | None) -> str:
    style = (value or "auto").strip().lower().replace("_", "-")
    aliases = {
        "chat-completions": "chat",
        "chat-completion": "chat",
        "completions": "chat",
        "response": "responses",
        "response-api": "responses",
        "responses-api": "responses",
    }
    style = aliases.get(style, style)
    if style not in {"auto", "responses", "chat"}:
        raise RuntimeError(
            f"Unsupported LLM API style {value!r}. Use auto, responses, or chat."
        )
    return style


def _api_style_from_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return _normalize_api_style(value)
    return "auto"


def _responses_api_unavailable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in {404, 405, 501}:
        return True
    msg = str(exc).lower()
    return any(
        marker in msg
        for marker in [
            "not supported",
            "unsupported",
            "unknown endpoint",
            "not found",
            "no route",
            "404",
            "405",
            "501",
        ]
    )


def _chat_completion_create(client: Any, *, model: str, messages: Any, temperature: float):
    chat = getattr(client, "chat")
    completions = getattr(chat, "completions")
    return completions.create(model=model, messages=messages, temperature=temperature)


def _responses_create(client: Any, *, model: str, messages: Any, temperature: float):
    responses = getattr(client, "responses")
    return responses.create(model=model, input=messages, temperature=temperature)


def _call_openai_compatible(
    *,
    client: Any,
    model: str,
    messages: Any,
    temperature: float,
    api_style: str,
    base_url: str | None,
):
    style = _normalize_api_style(api_style)
    if style == "chat":
        return _chat_completion_create(
            client, model=model, messages=messages, temperature=temperature
        )

    try:
        return _responses_create(
            client, model=model, messages=messages, temperature=temperature
        )
    except AttributeError:
        if style == "responses":
            raise
        return _chat_completion_create(
            client, model=model, messages=messages, temperature=temperature
        )
    except Exception as exc:
        if style == "auto" and _responses_api_unavailable(exc):
            return _chat_completion_create(
                client, model=model, messages=messages, temperature=temperature
            )
        raise RuntimeError(
            "OpenAI-compatible provider failed using Responses API. "
            f"base_url={base_url!r} model={model!r} api_style={style!r}. "
            "Set OPENAI_API_STYLE=chat for Chat Completions-only providers."
        ) from exc


def _wire_azure_provider(*, temperature: float = 0.2) -> CallableLLMProvider:
    azure_client, model_name = create_azure_openai_client()
    api_style = _api_style_from_env(
        "AZURE_OPENAI_API_STYLE", "OPENAI_API_STYLE", "LLM_API_STYLE"
    )

    def _call(messages):
        return _call_openai_compatible(
            client=azure_client,
            model=model_name,
            messages=messages,
            temperature=temperature,
            api_style=api_style,
            base_url=os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("OPENAI_BASE_URL"),
        )

    return CallableLLMProvider(_call)


def _wire_openai_like_provider(*, temperature: float = 0.2) -> CallableLLMProvider:
    if OpenAI is None:  # pragma: no cover
        raise RuntimeError("openai package is required for OpenAI-like provider")

    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    api_style = _api_style_from_env("OPENAI_API_STYLE", "LLM_API_STYLE")

    client_kwargs: dict[str, Any] = {}
    if base_url:
        client_kwargs["base_url"] = base_url

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), **client_kwargs)

    def _call(messages):
        return _call_openai_compatible(
            client=client,
            model=model,
            messages=messages,
            temperature=temperature,
            api_style=api_style,
            base_url=base_url,
        )

    return CallableLLMProvider(_call)


def resolve_llm_provider(
    *,
    config: Any = None,
    explicit_llm_provider: Any = None,
    temperature: float = 0.2,
) -> ResolvedLLMProvider:
    """Resolve a wired LLM provider.

    Precedence:
    1) explicit_llm_provider (already wired instance)
    2) config/env provider selection
    3) env detection (Azure then OpenAI-like)
    """

    if explicit_llm_provider is not None and not isinstance(explicit_llm_provider, str):
        return ResolvedLLMProvider(
            provider=explicit_llm_provider, provider_name="custom"
        )

    provider_name = resolve_llm_provider_name(config)
    if provider_name:
        normalized = provider_name.strip().lower()
        if normalized in {"azure", "azure-openai", "azure_openai"}:
            return ResolvedLLMProvider(
                provider=_wire_azure_provider(temperature=temperature),
                provider_name="azure",
            )
        if normalized in {"openai", "openai-like", "openai_like"}:
            return ResolvedLLMProvider(
                provider=_wire_openai_like_provider(temperature=temperature),
                provider_name="openai-like",
            )
        raise RuntimeError(
            f"Unsupported LLM provider '{provider_name}'. "
            "Supported: azure, openai-like (or provide config.llm_provider instance)."
        )

    if _has_azure_env():
        return ResolvedLLMProvider(
            provider=_wire_azure_provider(temperature=temperature),
            provider_name="azure",
        )
    if _has_openai_like_env():
        return ResolvedLLMProvider(
            provider=_wire_openai_like_provider(temperature=temperature),
            provider_name="openai-like",
        )

    raise RuntimeError(
        "No LLM provider configured. Provide config.llm_provider (instance) or "
        "config.llm_provider_name, or set AZURE_OPENAI_* or OPENAI_API_KEY env vars."
    )
