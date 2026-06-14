from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    # Tool calling fields (optional, for advanced clients)
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_arguments: Optional[Dict[str, Any]] = None


class ChatRequest(BaseModel):
    agent: str = Field(
        default="pm-minimal", description="Agent key or module:ClassName"
    )
    user_id: str
    conversation_id: Optional[str] = None
    messages: List[ChatMessage]
    temperature: float = 0.2
    max_tool_turns: int = 12
    stm_top_k: int = 5
    stm_max_summaries: int = 15
    stm_relevance_threshold: float = 0.3

    # Optional system prompt override (workspace default or per-request).
    system_prompt: Optional[str] = None


class ChatResponse(BaseModel):
    status: Literal["success", "error"]
    conversation_id: str
    trace_id: Optional[str] = None
    answer: Optional[str] = None
    messages: List[ChatMessage] = Field(default_factory=list)
    error: Optional[str] = None
