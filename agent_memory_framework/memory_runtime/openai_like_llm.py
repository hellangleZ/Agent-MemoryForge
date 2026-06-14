from __future__ import annotations

from dataclasses import dataclass
import random
import time
from typing import Any, Dict, List, Optional

from utils.logging_config import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class OpenAILikeLLMConfig:
    provider: str
    model: str
    temperature: float
    max_output_tokens: int

    # OpenAI-like
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    api_style: str = "auto"  # auto|responses|chat

    # Azure
    azure_api_key: Optional[str] = None
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    azure_api_version: str = "2024-02-15-preview"

    # Retry / rate limit handling
    max_attempts: int = 6
    retry_base_sleep_s: float = 0.5


def _normalize_openai_response_to_text(resp: Any) -> str:
    if hasattr(resp, "output_text"):
        return str(resp.output_text)
    try:
        choices = getattr(resp, "choices")
        if choices and hasattr(choices[0], "message"):
            return str(choices[0].message.content)
    except Exception:
        pass
    if isinstance(resp, dict):
        if "output_text" in resp:
            return str(resp["output_text"])
        if "choices" in resp and resp["choices"]:
            msg = resp["choices"][0].get("message")
            if msg and "content" in msg:
                return str(msg["content"])
    return str(resp)


def _parse_retry_after_seconds(exc: Exception) -> Optional[float]:
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) if resp is not None else None
    if headers and isinstance(headers, dict):
        ra = headers.get("retry-after") or headers.get("Retry-After")
        if ra:
            try:
                return float(str(ra).strip())
            except Exception:
                return None
    return None


def _is_rate_limit_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    msg = str(exc).lower()
    return "429" in msg or "too many requests" in msg or "rate limit" in msg


def _is_not_found_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status == 404:
        return True
    msg = str(exc).lower()
    return ("404" in msg) and ("not found" in msg or "page not found" in msg or "no route" in msg)


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
            f"Unsupported OpenAI-compatible API style {value!r}. Use auto, responses, or chat."
        )
    return style


def _is_temperature_unsupported(exc: Exception) -> bool:
    msg = str(exc).lower()
    return ("temperature" in msg) and ("not supported" in msg or "unsupported parameter" in msg)


def call_openai_like_llm(*, cfg: OpenAILikeLLMConfig, messages: List[Dict[str, Any]]) -> str:
    provider = (cfg.provider or "").strip().lower()

    max_attempts = int(getattr(cfg, "max_attempts", 6) or 6)
    base_sleep_s = float(getattr(cfg, "retry_base_sleep_s", 0.5) or 0.5)

    def _sleep_backoff(attempt: int, exc: Exception) -> None:
        retry_after = _parse_retry_after_seconds(exc)
        if retry_after is not None and retry_after > 0:
            sleep_s = retry_after
        else:
            sleep_s = min(20.0, base_sleep_s * (2 ** max(0, attempt - 1)))
            sleep_s = sleep_s * (0.8 + random.random() * 0.4)
        time.sleep(sleep_s)

    if provider in {"openai", "openai-like", "openai_like"}:
        from openai import OpenAI

        client_kwargs: Dict[str, Any] = {}
        if cfg.openai_base_url:
            client_kwargs["base_url"] = cfg.openai_base_url
        client = OpenAI(api_key=cfg.openai_api_key, **client_kwargs)

        last_exc: Exception | None = None
        api_style = _normalize_api_style(cfg.api_style)
        use_responses_api = api_style != "chat"
        allow_temperature = True
        for attempt in range(1, max_attempts + 1):
            try:
                if use_responses_api:
                    kwargs: Dict[str, Any] = {
                        "model": cfg.model,
                        "input": messages,
                        "max_output_tokens": cfg.max_output_tokens,
                    }
                    if allow_temperature:
                        kwargs["temperature"] = cfg.temperature
                    resp = client.responses.create(**kwargs)
                else:
                    kwargs = {
                        "model": cfg.model,
                        "messages": messages,
                        "max_tokens": cfg.max_output_tokens,
                    }
                    if allow_temperature:
                        kwargs["temperature"] = cfg.temperature
                    resp = client.chat.completions.create(**kwargs)  # type: ignore[attr-defined]
                return _normalize_openai_response_to_text(resp)
            except Exception as exc:
                last_exc = exc
                if allow_temperature and _is_temperature_unsupported(exc):
                    allow_temperature = False
                    continue
                if api_style == "auto" and use_responses_api and _is_not_found_error(exc):
                    logger.warning("responses API unavailable; falling back to chat.completions (openai-like)")
                    use_responses_api = False
                    continue
                if _is_rate_limit_error(exc) and attempt < max_attempts:
                    logger.warning("llm rate-limited (openai-like) attempt=%s/%s", attempt, max_attempts)
                    _sleep_backoff(attempt, exc)
                    continue
                raise
        raise RuntimeError("LLM failed after retries") from last_exc

    if provider in {"azure", "azure-openai", "azure_openai"}:
        from openai import AzureOpenAI

        if not (cfg.azure_api_key and cfg.azure_endpoint and cfg.azure_deployment):
            raise RuntimeError("Azure LLM config is incomplete")

        client = AzureOpenAI(
            api_key=cfg.azure_api_key,
            azure_endpoint=cfg.azure_endpoint,
            api_version=cfg.azure_api_version,
        )
        last_exc: Exception | None = None
        api_style = _normalize_api_style(cfg.api_style)
        use_responses_api = api_style != "chat"
        allow_temperature = True
        for attempt in range(1, max_attempts + 1):
            try:
                if use_responses_api:
                    kwargs: Dict[str, Any] = {
                        "model": cfg.azure_deployment,
                        "input": messages,
                        "max_output_tokens": cfg.max_output_tokens,
                    }
                    if allow_temperature:
                        kwargs["temperature"] = cfg.temperature
                    resp = client.responses.create(**kwargs)
                else:
                    kwargs = {
                        "model": cfg.azure_deployment,
                        "messages": messages,
                        "max_tokens": cfg.max_output_tokens,
                    }
                    if allow_temperature:
                        kwargs["temperature"] = cfg.temperature
                    resp = client.chat.completions.create(**kwargs)  # type: ignore[attr-defined]
                return _normalize_openai_response_to_text(resp)
            except Exception as exc:
                last_exc = exc
                if allow_temperature and _is_temperature_unsupported(exc):
                    allow_temperature = False
                    continue
                if api_style == "auto" and use_responses_api and _is_not_found_error(exc):
                    logger.warning("responses API unavailable; falling back to chat.completions (azure)")
                    use_responses_api = False
                    continue
                if _is_rate_limit_error(exc) and attempt < max_attempts:
                    logger.warning("llm rate-limited (azure) attempt=%s/%s", attempt, max_attempts)
                    _sleep_backoff(attempt, exc)
                    continue
                raise
        raise RuntimeError("LLM failed after retries") from last_exc

    raise RuntimeError(
        f"Unsupported provider={cfg.provider!r}. Use openai-like or azure."
    )
