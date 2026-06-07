"""Integration test for Function Calling architecture."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_agent_framework.core.tool_loop import ToolLoop
from ai_agent_framework.core.prompt_builder import PromptBuilder
from ai_agent_framework.tools import ToolRegistry, CalculatorTool
from ai_agent_framework.streaming.stream_manager import StreamManager
from ai_agent_framework.memory.memory_manager import MemoryManager


class MockLLM:
    """Mock LLM simulating Function Calling stream."""

    def __init__(self):
        self.call_count = 0

    def chat(self, messages, tools=None, stream=False):
        self.call_count += 1
        if self.call_count == 1:
            # First call: thinking + tool call
            def gen():
                yield {"type": "content", "text": "我来计算"}
                yield {"type": "tool_calls", "calls": [
                    {"name": "calculator", "arguments": '{"expression": "2+2"}'}
                ]}
                yield {"type": "done"}
            return gen()
        else:
            # Second call: final answer
            def gen():
                for ch in "2+2=4":
                    yield {"type": "content", "text": ch}
                yield {"type": "done"}
            return gen()


class TestToolLoop(unittest.TestCase):

    def test_single_tool_call(self):
        """Test function calling path (input that does NOT trigger builtin)."""
        registry = ToolRegistry()
        registry.register(CalculatorTool())
        prompt = PromptBuilder()
        llm = MockLLM()
        memory = MemoryManager(db_path=":memory:")
        stream = StreamManager()

        loop = ToolLoop(llm, registry, prompt, memory, stream)
        # Use English input to avoid builtin detection
        result = loop.run("What is 2+2?", session_id="test")

        self.assertEqual(result, "2+2=4")
        self.assertEqual(llm.call_count, 2)

    def test_builtin_calculator(self):
        """Test builtin calculator path (no function calling, no tool UI)."""
        registry = ToolRegistry()
        registry.register(CalculatorTool())
        prompt = PromptBuilder()

        class BuiltinMockLLM:
            def __init__(self):
                self.call_count = 0
            def chat(self, messages, tools=None, stream=False):
                self.call_count += 1
                def gen():
                    for ch in "结果是4":
                        yield {"type": "content", "text": ch}
                    yield {"type": "done"}
                return gen()

        llm = BuiltinMockLLM()
        memory = MemoryManager(db_path=":memory:")
        stream = StreamManager()

        loop = ToolLoop(llm, registry, prompt, memory, stream)
        result = loop.run("计算 2+2", session_id="test_builtin")

        self.assertEqual(result, "结果是4")
        self.assertEqual(llm.call_count, 1)  # Only one LLM call for final answer

    def test_no_tool_needed(self):
        registry = ToolRegistry()
        registry.register(CalculatorTool())
        prompt = PromptBuilder()
        llm = MockLLM()
        # Override to return no tool_calls
        llm.call_count = 999  # Force second branch
        memory = MemoryManager(db_path=":memory:")
        stream = StreamManager()

        def no_tool_gen(messages, tools=None, stream=False):
            def gen():
                yield {"type": "content", "text": "你好！"}
                yield {"type": "done"}
            return gen()

        llm.chat = no_tool_gen
        loop = ToolLoop(llm, registry, prompt, memory, stream)
        result = loop.run("你好", session_id="test2")
        self.assertEqual(result, "你好！")


if __name__ == "__main__":
    unittest.main()
