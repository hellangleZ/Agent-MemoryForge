from __future__ import annotations

from agent_memory_framework import Agent, ToolRegistry
from agent_memory_framework.runtime import Runtime


class CodeAssistantAgent(Agent):
    """Template single-agent suitable for a repo-aware code assistant."""

    def __init__(self, runtime: Runtime):
        super().__init__(runtime)

    def system_prompt(self) -> str:
        return (
            "You are a helpful code assistant. Be concise, propose safe changes, "
            "and ask clarifying questions when needed."
        )

    def register_tools(self, registry: ToolRegistry) -> None:
        # Tooling is intentionally left minimal in the template.
        return


from agent_memory_framework.demo_agent import DemoAgent  # noqa: E402


class CodeAssistantDemoAgent(DemoAgent):
    """Gateway-runnable code assistant.

    The gateway product registry only runs DemoAgent subclasses; the
    CodeAssistantAgent above uses the lower-level Agent interface. This thin
    DemoAgent exposes the ``code-assistant`` key to the gateway/portal.
    """

    def system_prompt(self) -> str:
        return self.get_system_prompt()

    def register_tools(self, registry) -> None:
        self.register_domain_tools(registry)

    def register_domain_tools(self, registry) -> None:
        return

    def get_system_prompt(self) -> str:
        return (
            "You are an expert software engineering assistant. Help the user "
            "write, review, debug, and explain code. Prefer precise, working "
            "examples, call out risks and edge cases, and ask clarifying "
            "questions when requirements are ambiguous."
        )
