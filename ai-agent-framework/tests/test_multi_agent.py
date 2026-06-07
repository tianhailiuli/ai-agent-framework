"""Unit tests for multi-agent collaboration."""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_agent_framework.core.multi_agent import PlannerAgent, ExecutorAgent, Task
from ai_agent_framework.core.prompt_builder import PromptBuilder
from ai_agent_framework.tools.base import ToolRegistry
from ai_agent_framework.tools.calculator import CalculatorTool


class MockLLMClient:
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0

    def chat(self, messages, stream=False):
        resp = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        return resp


class TestPlannerAgent(unittest.TestCase):
    def test_plan_parsing(self):
        llm = MockLLMClient([
            '[{"task_id": "1", "description": "Search wiki", "required_tools": ["wikipedia_search"], "dependencies": []}]'
        ])
        planner = PlannerAgent(llm, PromptBuilder())
        tasks = planner.plan("Search something", [])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].task_id, "1")
        self.assertEqual(tasks[0].description, "Search wiki")

    def test_plan_fallback(self):
        llm = MockLLMClient(["Invalid JSON!!!"])
        planner = PlannerAgent(llm, PromptBuilder())
        tasks = planner.plan("Do something", [])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].description, "Do something")


class TestExecutorAgent(unittest.TestCase):
    def test_execute_task(self):
        registry = ToolRegistry()
        registry.register(CalculatorTool())
        prompt_builder = PromptBuilder()

        llm = MockLLMClient([
            "Thought: Calculate.\nAction: calculator\nAction Input: {\"expression\": \"2+2\"}",
            "Thought: Done.\nFinal Answer: 4"
        ])

        # Need a mock react loop or use real one with mock LLM
        from ai_agent_framework.core.react_loop import ReActLoop
        react = ReActLoop(llm, registry, prompt_builder)
        executor = ExecutorAgent(llm, registry, prompt_builder, react)

        task = Task(task_id="1", description="Calculate 2+2")
        result = executor.execute(task, [])
        self.assertEqual(result, "4")
        self.assertEqual(task.status, "completed")


if __name__ == "__main__":
    unittest.main()
