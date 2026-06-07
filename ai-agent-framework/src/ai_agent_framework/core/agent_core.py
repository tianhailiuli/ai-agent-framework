"""Main orchestrator that wires all modules together."""

from ai_agent_framework import config
from ai_agent_framework.core.llm_client import LLMClient
from ai_agent_framework.core.prompt_builder import PromptBuilder
from ai_agent_framework.core.react_loop import ReActLoop
from ai_agent_framework.core.tool_loop import ToolLoop
from ai_agent_framework.core.multi_agent import PlannerAgent, ExecutorAgent
from ai_agent_framework.memory.memory_manager import MemoryManager
from ai_agent_framework.streaming.stream_manager import StreamManager
from ai_agent_framework.tools import (
    ToolRegistry,
    CalculatorTool,
    FileReadTool,
    FileWriteTool,
    WeatherTool,
    WebSearchTool,
)


class AgentCore:
    """Central orchestrator for the AI Agent framework."""

    def __init__(self):
        self.llm = LLMClient()
        self.tools = ToolRegistry()
        self.memory = MemoryManager()
        self.prompt_builder = PromptBuilder()
        self.stream = StreamManager()
        self._register_default_tools()

        # Mode selection
        self.mode = config.AGENT_MODE
        if self.mode == "function_calling":
            self.loop = ToolLoop(
                self.llm, self.tools, self.prompt_builder, self.memory, self.stream
            )
        else:
            self.loop = ReActLoop(
                self.llm, self.tools, self.prompt_builder, self.memory, self.stream
            )

        self.planner = PlannerAgent(self.llm, self.prompt_builder)
        self.executor = ExecutorAgent(
            self.llm, self.tools, self.prompt_builder,
            self.loop if isinstance(self.loop, ReActLoop) else None
        )

    def _register_default_tools(self):
        """Register all default tools."""
        self.tools.register(CalculatorTool())
        self.tools.register(FileReadTool(base_path=config.SAFE_FILE_BASE_PATH))
        self.tools.register(FileWriteTool(base_path=config.SAFE_FILE_BASE_PATH))
        self.tools.register(WeatherTool())
        self.tools.register(WebSearchTool())

    def _needs_multi_agent(self, user_input: str) -> bool:
        """
        Heuristic to decide if multi-agent collaboration is needed.
        Only trigger for complex planning tasks, not simple chained tool calls.
        """
        triggers = ["规划", "计划", "安排", "分步", "多个", "协作", "团队"]
        # Require explicit planning keywords OR very long + complex requests
        if any(t in user_input for t in triggers):
            return True
        if len(user_input) > 60:
            return True
        return False

    def process(self, user_input: str, session_id: str = None, stream: bool = False):
        """
        Main entry point to process user input.

        Args:
            user_input: The user's message.
            session_id: Optional session identifier.
            stream: Whether to use streaming.

        Returns:
            Final answer string (or Response if streaming via web).
        """
        if session_id is None:
            session_id = self.memory.create_session()

        if stream:
            # For web streaming, return the SSE response directly
            from flask import Response
            # Start processing in a background thread so SSE can stream
            import threading

            # Create stream queue BEFORE starting worker thread to avoid losing early events
            self.stream.create_stream(session_id)

            def _run():
                try:
                    self._execute(user_input, session_id)
                except Exception as e:
                    self.stream.push(session_id, {
                        "type": "error",
                        "content": str(e),
                        "timestamp": __import__("datetime").datetime.now().isoformat(),
                    })

            threading.Thread(target=_run, daemon=True).start()
            return self.stream.generate_sse(session_id)
        else:
            return self._execute(user_input, session_id)

    def _execute(self, user_input: str, session_id: str) -> str:
        """Internal execution logic.

        Memory management is delegated to the loop / multi-agent executor
        to avoid duplicate user/assistant entries.
        """
        # Ensure session exists in short term
        if session_id not in self.memory.short_term:
            self.memory.short_term[session_id] = __import__("collections").deque(
                maxlen=self.memory.short_term_limit
            )

        use_multi = self._needs_multi_agent(user_input)

        if use_multi:
            history = self.memory.get_short_term(session_id)
            tasks = self.planner.plan(user_input, history)
            result = self.executor.execute_plan(
                tasks, self.memory, self.stream, session_id
            )
        else:
            result = self.loop.run(
                user_input=user_input,
                session_id=session_id,
                max_iterations=config.MAX_REACT_ITERATIONS,
            )

        # Auto-persist short-term memory to long-term after each turn
        # (keeps short-term alive for current conversation context)
        self.memory.persist_without_clear(session_id)

        return result
