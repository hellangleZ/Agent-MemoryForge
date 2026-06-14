# -*- coding: utf-8 -*-
"""Minimal demo template.

Copy this file to create a new business demo quickly.
"""

from __future__ import annotations

import uuid

from config.agent_config import get_config
from agent_memory_framework.demo_agent import DemoAgent, DemoRuntime
from agent_memory_framework.llm_clients import create_azure_openai_client
from agent_runtime.product.logging_setup import setup_demo_logging
from agent_memory_lib import MemoryClient


class MyBusinessAgent(DemoAgent):
    def system_prompt(self) -> str:
        return self.get_system_prompt()

    def register_tools(self, registry) -> None:
        self.register_domain_tools(registry)

    def get_system_prompt(self) -> str:
        return "You are a helpful business agent."

    def register_domain_tools(self, registry):
        # registry.register(...)
        pass


# Expose a stable Agent subclass for discovery.
PmMinimalAgent = type(
    "PmMinimalAgent",
    (MyBusinessAgent,),
    {"__module__": __name__},
)


def _llm_call_factory(azure_client, model_name: str):
    def call(messages):
        return azure_client.responses.create(
            model=model_name,
            input=messages,
            temperature=0.2,
        )

    return call


def main() -> None:
    setup_demo_logging()
    config = get_config()

    azure_client, model_name = create_azure_openai_client()
    memory_client = MemoryClient(base_url=config.memory_service_url)

    runtime = DemoRuntime(
        agent_id=config.agent_id,
        user_id=config.user_id,
        memory_client=memory_client,
        llm_call_fn=_llm_call_factory(azure_client, model_name),
        conversation_id=f"demo_{uuid.uuid4().hex}",
        config={},
    )
    agent = MyBusinessAgent(runtime)
    print(agent.run_turn("Hello!"))


if __name__ == "__main__":
    main()
