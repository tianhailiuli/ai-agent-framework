"""Unit tests for tools."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_agent_framework.tools.calculator import CalculatorTool
from ai_agent_framework.tools.wikipedia import WikipediaTool
from ai_agent_framework.tools.file_read import FileReadTool
from ai_agent_framework.tools.file_write import FileWriteTool
from ai_agent_framework.tools.weather import WeatherTool
from ai_agent_framework.tools.base import ToolRegistry


class TestCalculatorTool(unittest.TestCase):
    def setUp(self):
        self.tool = CalculatorTool()

    def test_basic_addition(self):
        result = self.tool.run({"expression": "2+2"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"], 4)

    def test_complex_expression(self):
        result = self.tool.run({"expression": "(15 + 23) * 2"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"], 76)

    def test_invalid_expression(self):
        result = self.tool.run({"expression": "abc + 1"})
        self.assertEqual(result["status"], "error")

    def test_empty_expression(self):
        result = self.tool.run({"expression": ""})
        self.assertEqual(result["status"], "error")


class TestWikipediaTool(unittest.TestCase):
    def setUp(self):
        self.tool = WikipediaTool()

    def test_search_python(self):
        result = self.tool.run({"query": "Python programming language", "lang": "en"})
        if "timeout" in result.get("message", "").lower():
            self.skipTest("Wikipedia API timeout")
        self.assertEqual(result["status"], "success")
        self.assertTrue(len(result["result"]) > 0)

    def test_empty_query(self):
        result = self.tool.run({"query": ""})
        self.assertEqual(result["status"], "error")


class TestFileTools(unittest.TestCase):
    def setUp(self):
        self.base = os.path.join(os.path.dirname(__file__), "test_data")
        os.makedirs(self.base, exist_ok=True)
        self.read_tool = FileReadTool(base_path=self.base)
        self.write_tool = FileWriteTool(base_path=self.base)

    def tearDown(self):
        # Cleanup
        import shutil
        if os.path.exists(self.base):
            shutil.rmtree(self.base)

    def test_write_and_read(self):
        write_result = self.write_tool.run({"filepath": "hello.txt", "content": "你好"})
        self.assertEqual(write_result["status"], "success")

        read_result = self.read_tool.run({"filepath": "hello.txt"})
        self.assertEqual(read_result["status"], "success")
        self.assertEqual(read_result["result"], "你好")

    def test_path_traversal(self):
        result = self.read_tool.run({"filepath": "../../../etc/passwd"})
        self.assertEqual(result["status"], "error")
        self.assertIn("denied", result["message"])


class TestWeatherTool(unittest.TestCase):
    def setUp(self):
        self.tool = WeatherTool()

    def test_query_beijing(self):
        result = self.tool.run({"city": "Beijing"})
        self.assertEqual(result["status"], "success")
        self.assertIn("temperature", result["result"])

    def test_empty_city(self):
        result = self.tool.run({"city": ""})
        self.assertEqual(result["status"], "error")


class TestToolRegistry(unittest.TestCase):
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = CalculatorTool()
        reg.register(tool)
        self.assertEqual(reg.get("calculator"), tool)
        self.assertIn(tool, reg.list_tools())
        self.assertIn("calculator", reg.get_tools_description())


if __name__ == "__main__":
    unittest.main()
