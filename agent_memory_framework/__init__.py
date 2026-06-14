"""Public framework package API.

This module provides a stable, minimal surface area that downstream users can
import without depending on internal demo modules.
"""

from __future__ import annotations

from agent_memory_framework.agent import Agent
from agent_memory_framework.context import ContextAssembler
from agent_memory_framework.factory import (
    AgentBuildOptions,
    AutoBuildOverrides,
    build_agent,
    build_agent_from_config,
    build_team_from_config,
    build_orchestrated_team_from_config,
)
from agent_memory_framework.llm import LLMProvider, LLMResult
from agent_memory_framework.memory import (
    MemoryProvenance,
    MemoryQuery,
    MemoryRecord,
    MemoryRef,
    MemoryScope,
    MemoryTier,
    MemoryStore,
)
from agent_memory_framework.adapters import MemoryServiceStore
from agent_memory_framework.plugins import (
    DiscoveredAgent,
    DiscoveredTool,
    discover_agents,
    discover_tools,
    discover_tools_grouped,
    load_agent_spec,
    load_agent_class_from_spec,
    load_object_from_spec,
)
from agent_memory_framework.replay import (
    PatchArtifact,
    ReplayBundle,
    ReplayRunner,
    RepoContext,
    RunRecorder,
)
from agent_memory_framework.mcp import MCPClient
from agent_memory_framework.multi_agent import CoordinationStrategy, MultiAgentRuntime
from agent_memory_framework.orchestrator import (
    ArtifactRef,
    LLMTaskGraphPlanner,
    OrchestrationResult,
    TaskGraphOrchestrator,
)
from agent_memory_framework.task_graph import (
    TaskGraph,
    TaskGraphFinal,
    TaskGraphValidationError,
    TaskGraphValidator,
    TaskNode,
)
from agent_memory_framework.runtime import Runtime
from agent_memory_framework.settings import Settings
from agent_memory_framework.tools import ToolRegistry

__all__ = [
    "Agent",
    "ContextAssembler",
    "AgentBuildOptions",
    "AutoBuildOverrides",
    "build_agent",
    "build_agent_from_config",
    "build_team_from_config",
    "build_orchestrated_team_from_config",
    "DiscoveredAgent",
    "DiscoveredTool",
    "discover_agents",
    "discover_tools",
    "discover_tools_grouped",
    "load_agent_spec",
    "load_agent_class_from_spec",
    "load_object_from_spec",
    "LLMProvider",
    "LLMResult",
    "MemoryServiceStore",
    "MemoryProvenance",
    "MemoryQuery",
    "MemoryRecord",
    "MemoryRef",
    "MemoryScope",
    "MemoryStore",
    "MemoryTier",
    "MCPClient",
    "CoordinationStrategy",
    "MultiAgentRuntime",
    "ArtifactRef",
    "LLMTaskGraphPlanner",
    "OrchestrationResult",
    "TaskGraph",
    "TaskGraphFinal",
    "TaskGraphOrchestrator",
    "TaskGraphValidationError",
    "TaskGraphValidator",
    "TaskNode",
    "PatchArtifact",
    "ReplayBundle",
    "ReplayRunner",
    "RepoContext",
    "Runtime",
    "RunRecorder",
    "Settings",
    "ToolRegistry",
]
