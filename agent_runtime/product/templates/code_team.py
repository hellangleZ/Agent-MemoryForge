from __future__ import annotations

from agent_memory_framework import Agent, ToolRegistry
from agent_memory_framework.multi_agent import MultiAgentRuntime, build_team_runtime
from agent_memory_framework.runtime import Runtime


class CodeTeamAgent(Agent):
    """Template multi-agent wrapper.

    STORY-001 provides the shell; collaboration runtime is implemented in
    STORY-008.
    """

    def __init__(self, runtime: Runtime):
        super().__init__(runtime)

    def system_prompt(self) -> str:
        return (
            "You are a multi-agent coding team coordinator. Produce a plan and "
            "delegate tasks. (Collaboration runtime is not enabled yet.)"
        )

    def register_tools(self, registry: ToolRegistry) -> None:
        return

    def build_team_runtime(self) -> MultiAgentRuntime:
        """Create a minimal collaboration runtime for this template.

        Uses the framework Agent base for all roles; providers and tools remain
        shared via the underlying Runtime.
        """

        agent_cls = type(self)
        return build_team_runtime(
            base_runtime=self.runtime,
            agent_factories={
                "planner": agent_cls,
                "implementer": agent_cls,
                "reviewer": agent_cls,
                "tester": agent_cls,
            },
            roles={
                "planner": "planner",
                "implementer": "implementer",
                "reviewer": "reviewer",
                "tester": "tester",
            },
            strategy="parallel",
        )
