"""Tool base class and registry."""

from abc import ABC, abstractmethod


class Tool(ABC):
    """Abstract base class for all tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool unique identifier."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for LLM system prompt."""
        pass

    @property
    @abstractmethod
    def schema(self) -> dict:
        """
        OpenAI Function Calling schema.
        Returns:
            {
                "type": "function",
                "function": {
                    "name": "...",
                    "description": "...",
                    "parameters": {"type": "object", "properties": {...}, "required": [...]}
                }
            }
        """
        pass

    @property
    def hidden(self) -> bool:
        """Whether to hide tool usage UI (for simple builtin tools like calculator)."""
        return False

    @abstractmethod
    def run(self, params: dict) -> dict:
        """
        Execute the tool.

        Returns:
            {"status": "success|error", "result": any, "message": str}
        """
        pass


class ToolRegistry:
    """Registry for managing available tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def get_tools_description(self) -> str:
        """Generate tool descriptions for LLM prompt."""
        lines = []
        for tool in self._tools.values():
            lines.append(f"- {tool.name}: {tool.description}")
        return "\n".join(lines)

    def get_schemas(self) -> list[dict]:
        """Generate OpenAI Function Calling schemas for all tools."""
        return [t.schema for t in self._tools.values()]
