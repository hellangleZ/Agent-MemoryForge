#!/usr/bin/env python3
"""D) Provider health-check ('doctor'): ping every configured LLM role (main reasoning,
distillation, context planner) and the embedding provider. Prints OK/FAIL per role and
exits non-zero if any *enabled* role fails fast-feedback so misconfig is caught at startup
instead of silently failing later (e.g. the planner 404 / distill DLQ we hit).

Run with .env sourced (start_services does this) or it will read the current environment.
"""
from __future__ import annotations
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PING = [{"role": "user", "content": "ping"}]
fails = 0


def ok(role, detail=""):
    print(f"[ OK ] {role}" + (f" -- {detail}" if detail else ""))


def fail(role, detail=""):
    global fails
    fails += 1
    print(f"[FAIL] {role}" + (f" -- {detail}" if detail else ""))


def skip(role, detail=""):
    print(f"[skip] {role}" + (f" -- {detail}" if detail else ""))


def _truthy(v):
    return str(v or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def check_main():
    role = "main LLM"
    try:
        from agent_memory_framework.memory_runtime.openai_like_llm import (
            OpenAILikeLLMConfig, call_openai_like_llm,
        )
        provider = (os.getenv("LLM_PROVIDER") or "openai-like").strip().lower()
        cfg = OpenAILikeLLMConfig(
            provider=provider,
            model=os.getenv("OPENAI_MODEL") or os.getenv("AZURE_OPENAI_DEPLOYMENT") or "",
            temperature=0.0,
            max_output_tokens=16,
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_base_url=os.getenv("OPENAI_BASE_URL"),
            api_style=os.getenv("OPENAI_API_STYLE") or os.getenv("LLM_API_STYLE") or "auto",
            azure_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            azure_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
            max_attempts=2,
        )
        t = time.time()
        call_openai_like_llm(cfg=cfg, messages=PING)
        ok(role, f"provider={provider} model={cfg.model} ({(time.time()-t):.1f}s)")
    except Exception as e:
        fail(role, f"{type(e).__name__}: {str(e)[:160]}")


def check_distill():
    role = "distill LLM"
    try:
        from agent_runtime.memory_distill.distill_settings import MemoryDistillSettings
        s = MemoryDistillSettings.from_env()
        if not s.enabled:
            return skip(role, "MEMORY_DISTILL_ENABLED off")
        from agent_memory_framework.memory_distill.llm_provider import DistillLLMConfig, call_distill_llm
        cfg = DistillLLMConfig(
            provider=s.provider, model=s.model, temperature=s.temperature,
            max_output_tokens=16, max_attempts=2, retry_base_sleep_s=s.llm_retry_base_sleep_s,
            openai_api_key=s.openai_api_key, openai_base_url=s.openai_base_url, api_style=s.api_style,
            azure_api_key=s.azure_api_key, azure_endpoint=s.azure_endpoint,
            azure_deployment=s.azure_deployment, azure_api_version=s.azure_api_version,
        )
        t = time.time()
        call_distill_llm(cfg=cfg, messages=PING)
        ok(role, f"provider={s.provider} model={s.model} ({(time.time()-t):.1f}s)")
    except Exception as e:
        fail(role, f"{type(e).__name__}: {str(e)[:160]}")


def check_planner():
    role = "context planner LLM"
    try:
        from agent_memory_framework.memory_runtime.context_planner_settings import ContextPlannerSettings
        s = ContextPlannerSettings.from_env()
        if not s.enabled:
            return skip(role, "CONTEXT_PLANNER_ENABLED off")
        from agent_memory_framework.memory_runtime.openai_like_llm import (
            OpenAILikeLLMConfig, call_openai_like_llm,
        )
        cfg = OpenAILikeLLMConfig(
            provider=s.provider, model=s.model, temperature=s.temperature,
            max_output_tokens=16, openai_api_key=s.openai_api_key, openai_base_url=s.openai_base_url,
            api_style=s.api_style,
            azure_api_key=s.azure_api_key, azure_endpoint=s.azure_endpoint,
            azure_deployment=s.azure_deployment, azure_api_version=s.azure_api_version,
            max_attempts=2,
        )
        t = time.time()
        call_openai_like_llm(cfg=cfg, messages=PING)
        ok(role, f"provider={s.provider} model={s.model} ({(time.time()-t):.1f}s)")
    except Exception as e:
        fail(role, f"{type(e).__name__}: {str(e)[:160]}")


def check_embedding():
    role = "embedding"
    try:
        from config.agent_config import AgentConfig
        from agent_memory_lib.embedding_client import embedding_client_from_env_like_config
        cfg = AgentConfig.from_env()
        ec = embedding_client_from_env_like_config(cfg)
        t = time.time()
        v = ec.embed_one("ping")
        ok(role, f"provider={cfg.embedding_provider} dim={len(v)} ({(time.time()-t):.1f}s)")
    except Exception as e:
        fail(role, f"{type(e).__name__}: {str(e)[:160]}")


def main():
    print("==== LLM/Embedding provider health-check ====")
    check_main()
    check_distill()
    check_planner()
    check_embedding()
    print(f"\n{('ALL HEALTHY' if fails == 0 else str(fails) + ' ROLE(S) FAILED')}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
