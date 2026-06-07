"""Unit tests for ReAct loop."""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_agent_framework.core.react_loop import ReActLoop
from ai_agent_framework.core.prompt_builder import PromptBuilder
from ai_agent_framework.tools.base import ToolRegistry
from ai_agent_framework.tools.calculator import CalculatorTool


class MockLLMClient:
    """Mock LLM that returns predefined responses."""

    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0

    def chat(self, messages, stream=False):
        resp = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        return resp


class TestReActLoop(unittest.TestCase):
    def test_single_tool_call(self):
        registry = ToolRegistry()
        registry.register(CalculatorTool())
        prompt_builder = PromptBuilder()

        # LLM first returns Action, then Final Answer
        llm = MockLLMClient([
            "Thought: I need to calculate.\nAction: calculator\nAction Input: {\"expression\": \"15*23\"}",
            "Thought: Calculation done.\nFinal Answer: 345"
        ])

        loop = ReActLoop(llm, registry, prompt_builder)
        result = loop.run("Calculate 15*23", session_id="test")
        self.assertEqual(result, "345")

    def test_direct_final_answer(self):
        registry = ToolRegistry()
        registry.register(CalculatorTool())
        prompt_builder = PromptBuilder()

        llm = MockLLMClient([
            "Thought: No tool needed.\nFinal Answer: Hello there!"
        ])

        loop = ReActLoop(llm, registry, prompt_builder)
        result = loop.run("Say hi", session_id="test")
        self.assertEqual(result, "Hello there!")

    def test_max_iterations(self):
        registry = ToolRegistry()
        registry.register(CalculatorTool())
        prompt_builder = PromptBuilder()

        # LLM always returns an action, never final answer
        llm = MockLLMClient([
            "Thought: Loop.\nAction: calculator\nAction Input: {\"expression\": \"1+1\"}"
        ])

        loop = ReActLoop(llm, registry, prompt_builder)
        result = loop.run("Loop forever", session_id="test", max_iterations=2)
        self.assertIn("maximum", result.lower())


if __name__ == "__main__":
    unittest.main()
