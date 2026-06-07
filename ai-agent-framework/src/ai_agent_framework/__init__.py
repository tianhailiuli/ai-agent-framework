"""AI Agent Framework — a lightweight agent framework with tool calling."""

from ai_agent_framework.core.agent_core import AgentCore
from ai_agent_framework.core.llm_client import LLMClient
from ai_agent_framework.memory.memory_manager import MemoryManager
from ai_agent_framework.streaming.stream_manager import StreamManager

__all__ = [
    "AgentCore",
    "LLMClient",
    "MemoryManager",
    "StreamManager",
]
